import argparse
import csv
import json
import sys
import traceback
from collections.abc import Iterable
from dataclasses import dataclass

from genai_tag_db_tools import errors
from genai_tag_db_tools.core_api import (
    default_sources,
    ensure_databases,
    get_statistics,
    initialize_databases,
    register_tag,
    search_tags,
)
from genai_tag_db_tools.db import runtime
from genai_tag_db_tools.db.repository import get_default_reader, get_default_repository
from genai_tag_db_tools.introspection import (
    full_schemas,
    get_tool_spec,
    iter_tool_specs,
    model_lines,
    tool_line,
)
from genai_tag_db_tools.models import (
    AliasRegisterInput,
    DbCacheConfig,
    DbSourceRef,
    EnsureDbRequest,
    RecordRecommendRequest,
    RefinementRecommendRequest,
    TagRegisterRequest,
    TagSearchRequest,
    TagTranslationInput,
    TranslationRecommendRequest,
)
from genai_tag_db_tools.services.tag_register import TagRegisterService


@dataclass(frozen=True)
class ParsedSource:
    repo_id: str
    filename: str
    revision: str | None


def _parse_source(value: str) -> ParsedSource:
    if "@" in value:
        path_part, revision = value.rsplit("@", 1)
    else:
        path_part, revision = value, None

    if "/" not in path_part:
        raise ValueError("source must be repo_id/filename[@revision]")

    repo_id, filename = path_part.rsplit("/", 1)
    if not repo_id or not filename:
        raise ValueError("source must be repo_id/filename[@revision]")

    return ParsedSource(repo_id=repo_id, filename=filename, revision=revision)


def _build_cache_config(args: argparse.Namespace) -> DbCacheConfig:
    # Determine user_db_dir (CLI override or default)
    if hasattr(args, "user_db_dir") and args.user_db_dir:
        user_db_dir = args.user_db_dir
    else:
        from genai_tag_db_tools.io.hf_downloader import default_cache_dir

        user_db_dir = str(default_cache_dir())

    return DbCacheConfig(
        cache_dir=user_db_dir,  # Repurpose cache_dir as user_db_dir
        token=args.token if hasattr(args, "token") else None,
    )


def _emit(line: dict[str, object]) -> None:
    """1 行 = 1 つの valid JSON オブジェクトを stdout へ出力する (JSONL)。

    stdout は JSONL 専用。ログ・進捗・装飾は stderr (loguru の既定 sink) へ出す。
    """
    print(json.dumps(line, ensure_ascii=False, default=str))


def emit_item(record: object) -> None:
    """list を返すコマンドの 1 レコードを 1 行 (kind=item) で出力する。

    巨大な配列を 1 行に詰めず、レコードごとに改行する。最終行の summary は
    `emit_result` で別途出す。
    """
    payload = record.model_dump() if hasattr(record, "model_dump") else record
    if isinstance(payload, dict):
        _emit({"kind": "item", **payload})
    else:
        _emit({"kind": "item", "value": payload})


def emit_result(message: str, **output: object) -> None:
    """成功時の最終行 (kind=result) を出力する。"""
    _emit({"kind": "result", "ok": True, "message": message, **output})


def emit_event(event: str, message: str) -> None:
    """途中経過 (kind=event) を出力する。必要な場合のみ使う。"""
    _emit({"kind": "event", "event": event, "message": message})


def emit_error(
    code: str,
    message: str,
    *,
    retryable: bool,
    user_action_required: bool,
    hint: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    """失敗時の最終行 (kind=error) を出力する。

    stderr の文字列パースに依存させず、stdout の JSONL 最終行に構造化エラーを出す。
    """
    line: dict[str, object] = {
        "kind": "error",
        "ok": False,
        "code": code,
        "message": message,
        "retryable": retryable,
        "user_action_required": user_action_required,
    }
    if hint:
        line["hint"] = hint
    if details:
        line["details"] = details
    _emit(line)


def _set_db_paths(base_db_paths: Iterable[str] | None, user_db_dir: str | None) -> None:
    from pathlib import Path

    if base_db_paths:
        runtime.set_base_database_paths([Path(p) for p in base_db_paths])
    else:
        initialize_databases(
            user_db_dir=user_db_dir,
            init_user_db=bool(user_db_dir),
        )
        return
    if user_db_dir:
        runtime.init_user_db(Path(user_db_dir))


def _build_register_service() -> TagRegisterService:
    repo = get_default_repository()
    return TagRegisterService(repository=repo)


def cmd_ensure_dbs(args: argparse.Namespace) -> None:
    cache = _build_cache_config(args)
    if args.source:
        sources = [
            DbSourceRef(
                repo_id=parsed.repo_id,
                filename=parsed.filename,
                revision=parsed.revision,
            )
            for parsed in (_parse_source(value) for value in args.source)
        ]
    else:
        sources = default_sources()

    requests = [EnsureDbRequest(source=source, cache=cache) for source in sources]
    results = ensure_databases(requests)
    for result in results:
        emit_item(result)
    emit_result("databases ensured", count=len(results))


def cmd_search(args: argparse.Namespace) -> None:
    _set_db_paths(args.base_db, args.user_db_dir)
    repo = get_default_reader()
    # --limit 0 は無制限の明示 opt-in。それ以外は CLI 既定 (50) を適用する。
    # 既定値は CLI 層に置き、TagSearchRequest.limit の既定 (None) は変更しない
    # (core_api を直呼びする利用側の挙動を壊さないため)。
    limit = None if args.limit == 0 else args.limit
    request = TagSearchRequest(
        query=args.query,
        partial=not args.exact,
        format_names=args.format_name or None,
        type_names=args.type_name or None,
        resolve_preferred=args.resolve_preferred,
        include_aliases=args.include_aliases,
        include_deprecated=args.include_deprecated,
        limit=limit,
        offset=args.offset,
    )
    result = search_tags(repo, request)
    for item in result.items:
        emit_item(item)
    emit_result(
        "search completed",
        query=args.query,
        count=len(result.items),
        total=result.total,
        limit=limit,
        offset=args.offset,
    )


def cmd_register(args: argparse.Namespace) -> None:
    # #25 案A: register も未指定時は default_cache_dir() 配下の user DB へフォールバックする
    # (他コマンドと挙動を揃え、エージェント/自動化がゼロコンフィグで動くようにする)。
    if args.user_db_dir:
        user_db_dir = args.user_db_dir
    else:
        from genai_tag_db_tools.io.hf_downloader import default_cache_dir

        user_db_dir = str(default_cache_dir())

    _set_db_paths(args.base_db, user_db_dir)
    translations = [TagTranslationInput(language=lang, translation=text) for lang, text in args.translation]
    request = TagRegisterRequest(
        tag=args.tag,
        source_tag=args.source_tag,
        format_name=args.format_name,
        type_name=args.type_name,
        alias=args.alias,
        preferred_tag=args.preferred_tag,
        translations=translations or None,
    )
    service = _build_register_service()
    result = register_tag(service, request)
    emit_result(
        "tag registered" if result.created else "tag already exists",
        created=result.created,
        tag_id=result.tag_id,
    )


def cmd_stats(args: argparse.Namespace) -> None:
    _set_db_paths(args.base_db, args.user_db_dir)
    repo = get_default_reader()
    result = get_statistics(repo)
    emit_result("statistics", **result.model_dump())


def _parse_alias_file(file_path: str) -> list[AliasRegisterInput]:
    """JSONL または CSV から AliasRegisterInput のリストを返す。"""
    import json as _json
    from pathlib import Path as _Path

    path = _Path(file_path)
    entries: list[AliasRegisterInput] = []

    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                entries.append(
                    AliasRegisterInput(
                        alias=row["alias"],
                        preferred=row["preferred"],
                        format_name=row["format_name"],
                        type_name=row.get("type_name") or "unknown",
                    )
                )
    else:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = _json.loads(line)
                entries.append(AliasRegisterInput(**data))

    return entries


def cmd_aliases_register(args: argparse.Namespace) -> None:
    """aliases register サブコマンドのハンドラ。"""
    from pathlib import Path

    if args.user_db_dir:
        user_db_dir = args.user_db_dir
    else:
        from genai_tag_db_tools.io.hf_downloader import default_cache_dir

        user_db_dir = str(default_cache_dir())

    # --base-db が user DB と同一ファイルを指す場合は拒否 (Issue #49)
    user_db_path = Path(user_db_dir).resolve() / "user_tags.sqlite"
    if args.base_db:
        for base_db in args.base_db:
            if Path(base_db).resolve() == user_db_path:
                emit_error(
                    errors.INVALID_INPUT,
                    "--base-db must not point to the same user_tags.sqlite as --user-db-dir for aliases register",
                    retryable=False,
                    user_action_required=True,
                )
                sys.exit(2)

    _set_db_paths(args.base_db, user_db_dir)
    service = _build_register_service()
    dry_run = not args.apply

    entries = _parse_alias_file(args.file)

    total = created = skipped = conflicts = missing_preferred = 0
    for entry in entries:
        total += 1
        item_result = service.register_alias_entry(entry, dry_run=dry_run)
        emit_item(item_result)
        if item_result.status in ("would_create", "created"):
            created += 1
        elif item_result.status == "skipped":
            skipped += 1
        elif item_result.status == "conflict":
            conflicts += 1
        elif item_result.status == "missing_preferred":
            missing_preferred += 1

    emit_result(
        "dry-run complete" if dry_run else "aliases registered",
        dry_run=dry_run,
        total=total,
        created=created,
        skipped=skipped,
        conflicts=conflicts,
        missing_preferred=missing_preferred,
    )


def cmd_convert(args: argparse.Namespace) -> None:
    """Convert tags to specified format."""
    from genai_tag_db_tools.core_api import convert_tags

    _set_db_paths(args.base_db, args.user_db_dir)
    repo = get_default_reader()

    converted = convert_tags(repo, args.tags, args.format_name, separator=args.separator)

    # 出力は JSONL 一本化。--json は後方互換のため受理するが無視する (deprecated)。
    emit_result(
        "tags converted",
        input=args.tags,
        output=converted,
        format=args.format_name,
    )


def _clean_tag_lines(lines: Iterable[str]) -> list[str]:
    """1 行 1 タグ。前後空白を除去し、空行は捨てる。"""
    return [stripped for line in lines if (stripped := line.strip())]


def _collect_recommend_tags(args: argparse.Namespace) -> list[str]:
    """`recommend tag` の入力を解決する。

    優先順位: ``--tag``（カンマ区切り / 複数指定可）> ``--file``（1行1タグ）>
    stdin（パイプ時のみ、1行1タグ）。いずれも無ければ空リスト。
    """
    if args.tag:
        tags: list[str] = []
        for value in args.tag:
            tags.extend(part.strip() for part in value.split(",") if part.strip())
        return tags
    if args.file:
        from pathlib import Path

        return _clean_tag_lines(Path(args.file).read_text(encoding="utf-8").splitlines())
    if not sys.stdin.isatty():
        return _clean_tag_lines(sys.stdin)
    return []


def cmd_recommend_tag(args: argparse.Namespace) -> None:
    """`recommend tag`: タグの手動 refinement を advisory 判定する (read-only, batch)。

    ロジックは core_api に委譲する薄いアダプタ。base DB のヒットが無ければ
    rule-only の理由付けへ自動フォールバックする (core 側の repo 経路)。
    """
    from genai_tag_db_tools.core_api import recommend_manual_refinement

    tags = _collect_recommend_tags(args)
    if not tags:
        emit_error(
            errors.INVALID_INPUT,
            "no tags provided (use --tag, --file, or pipe via stdin)",
            retryable=False,
            user_action_required=True,
        )
        sys.exit(2)

    # introspection 契約 (RefinementRecommendRequest) で format_name を検証/正規化。
    request = RefinementRecommendRequest(
        tags=",".join(tags),
        format_name=args.format_name,
        rule_only=args.rule_only,
    )

    repo = None
    if not request.rule_only:
        _set_db_paths(args.base_db, args.user_db_dir)
        repo = get_default_reader()

    needs_refinement_count = 0
    for tag in tags:
        recommendation = recommend_manual_refinement(tag, repo, format_name=request.format_name)
        emit_item(recommendation)
        if recommendation.needs_refinement:
            needs_refinement_count += 1

    # advisory: 要 refinement が出ても exit 0。判定件数は result 行に載せる (#102)。
    emit_result(
        "recommendations completed",
        total=len(tags),
        needs_refinement_count=needs_refinement_count,
    )


def cmd_recommend_translation(args: argparse.Namespace) -> None:
    """`recommend translation`: 翻訳品質を advisory 判定する (rule-only, DB 非依存)。"""
    from genai_tag_db_tools.core_api import recommend_translation_quality

    request = TranslationRecommendRequest(
        source_tag=args.source_tag,
        translation=args.translation,
        language=args.language,
        target_scope=args.target_scope,
        target_tag_id=args.target_tag_id,
    )
    recommendation = recommend_translation_quality(
        request.source_tag,
        request.translation,
        language=request.language,
        target_scope=request.target_scope,
        target_tag_id=request.target_tag_id,
    )
    emit_result("translation recommendation", **recommendation.model_dump())


def _iter_recommend_record_rows(lines: Iterable[str]) -> Iterable[dict[str, object]]:
    """Yield `kind:item` JSONL payloads from `search` output.

    Search result summaries and events are ignored. Structured error lines are treated
    as invalid input because recommendation output would otherwise hide upstream failure.
    """
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL on stdin at line {line_number}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"stdin line {line_number} must be a JSON object")

        kind = payload.get("kind")
        if kind == "item":
            row = dict(payload)
            row.pop("kind", None)
            yield row
        elif kind == "error":
            raise ValueError(f"stdin line {line_number} is an upstream error line")
        elif kind in {"event", "result"}:
            continue
        else:
            raise ValueError(f"stdin line {line_number} has unsupported kind: {kind!r}")


def cmd_recommend_record(args: argparse.Namespace) -> None:
    """`recommend record`: `search` JSONL item rows の refinement を advisory 判定する。"""
    from genai_tag_db_tools.core_api import recommend_tag_record_refinement

    if sys.stdin.isatty():
        emit_error(
            errors.INVALID_INPUT,
            "no JSONL records provided on stdin (pipe tag-db search output)",
            retryable=False,
            user_action_required=True,
        )
        sys.exit(2)

    request = RecordRecommendRequest(
        format_name=args.format_name,
        target_scope=args.target_scope,
    )
    repo = None
    if args.base_db or args.user_db_dir:
        _set_db_paths(args.base_db, args.user_db_dir)
        repo = get_default_reader()

    total = 0
    needs_refinement_count = 0
    for row in _iter_recommend_record_rows(sys.stdin):
        recommendation = recommend_tag_record_refinement(
            row,
            format_name=request.format_name,
            target_scope=request.target_scope,
            repo=repo,
        )
        emit_item(recommendation)
        total += 1
        if recommendation.needs_refinement:
            needs_refinement_count += 1

    if total == 0:
        emit_error(
            errors.INVALID_INPUT,
            "no item records found on stdin",
            retryable=False,
            user_action_required=True,
        )
        sys.exit(2)

    emit_result(
        "record recommendations completed",
        total=total,
        needs_refinement_count=needs_refinement_count,
    )


def cmd_describe(args: argparse.Namespace) -> None:
    spec = get_tool_spec(args.target_command)
    if args.schema == "json_schema":
        # 文書化された例外 (ADR 0005): kind 付き JSONL ではなく、人間向け # note 1 行 +
        # 各モデルの model_json_schema() を生の 1 行 JSON で出力する。
        print("# Full JSON Schema (one model per line, raw model_json_schema; not kind-wrapped JSONL)")
        for schema in full_schemas([spec]):
            print(json.dumps(schema, ensure_ascii=False))
        return
    _emit(tool_line(spec))
    for line in model_lines(spec):
        _emit(line)
    emit_result("command described", command=spec.name)


def cmd_list_commands(args: argparse.Namespace) -> None:
    specs = list(iter_tool_specs())
    for spec in specs:
        _emit(tool_line(spec))
    emit_result("commands listed", count=len(specs))


def _add_base_db_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-db",
        action="append",
        help="Base DB sqlite path. Repeat for multiple. Omit to auto-download default sources from HF.",
    )
    parser.add_argument(
        "--user-db-dir",
        help="User database directory (defaults to OS-specific cache dir).",
    )


def build_parser(prog: str = "tag-db") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_many_parser = subparsers.add_parser("ensure-dbs", help="Download multiple DBs.")
    ensure_many_parser.add_argument(
        "--source",
        action="append",
        help="repo_id/filename[@revision]. Repeat for multiple sources. Omit to use default sources.",
    )
    ensure_many_parser.add_argument(
        "--user-db-dir", help="User database directory (defaults to OS-specific cache)"
    )
    ensure_many_parser.add_argument("--token")
    ensure_many_parser.set_defaults(func=cmd_ensure_dbs)

    search_parser = subparsers.add_parser("search", help="Search tags.")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--format-name", action="append")
    search_parser.add_argument("--type-name", action="append")
    search_parser.add_argument("--resolve-preferred", action="store_true")
    search_parser.add_argument("--include-aliases", action="store_true")
    search_parser.add_argument("--include-deprecated", action="store_true")
    search_parser.add_argument(
        "--exact",
        action="store_true",
        help="Use exact matching (partial match is default).",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of items to return (default: 50). Use 0 for unlimited.",
    )
    search_parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Number of items to skip (default: 0).",
    )
    _add_base_db_args(search_parser)
    search_parser.set_defaults(func=cmd_search)

    register_parser = subparsers.add_parser("register", help="Register a tag.")
    register_parser.add_argument("--tag", required=True)
    register_parser.add_argument("--source-tag")
    register_parser.add_argument("--format-name", required=True)
    register_parser.add_argument("--type-name", required=True)
    register_parser.add_argument("--alias", action="store_true")
    register_parser.add_argument("--preferred-tag")
    register_parser.add_argument(
        "--translation",
        action="append",
        default=[],
        type=lambda value: tuple(value.split(":", 1)),
        help="LANG:TEXT. Repeat for multiple translations.",
    )
    _add_base_db_args(register_parser)
    register_parser.set_defaults(func=cmd_register)

    stats_parser = subparsers.add_parser("stats", help="Show statistics.")
    _add_base_db_args(stats_parser)
    stats_parser.set_defaults(func=cmd_stats)

    convert_parser = subparsers.add_parser("convert", help="Convert tags to format.")
    convert_parser.add_argument("--tags", required=True, help="Comma-separated tags")
    convert_parser.add_argument("--format-name", required=True, help="Target format (e.g., danbooru, e621)")
    convert_parser.add_argument("--separator", default=", ", help="Tag separator (default: ', ')")
    convert_parser.add_argument(
        "--json",
        action="store_true",
        help="Deprecated: output is always JSONL. Accepted but ignored.",
    )
    _add_base_db_args(convert_parser)
    convert_parser.set_defaults(func=cmd_convert)

    describe_parser = subparsers.add_parser(
        "describe",
        help="Emit machine-readable metadata for one command.",
    )
    describe_parser.add_argument("target_command", choices=[spec.name for spec in iter_tool_specs()])
    describe_parser.add_argument(
        "--schema",
        choices=["compact", "json_schema"],
        default="compact",
        help="compact (default) for short field notation, json_schema for the full schema.",
    )
    describe_parser.set_defaults(func=cmd_describe)

    aliases_parser = subparsers.add_parser("aliases", help="Manage tag aliases.")
    aliases_subs = aliases_parser.add_subparsers(dest="aliases_command", required=True)

    aliases_register_parser = aliases_subs.add_parser(
        "register",
        help="Bulk-register alias entries from JSONL/CSV file (dry-run by default).",
    )
    aliases_register_parser.add_argument(
        "--file",
        required=True,
        help="Input file path (.jsonl or .csv).",
    )
    aliases_register_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write to user DB. Omit for dry-run (default).",
    )
    _add_base_db_args(aliases_register_parser)
    aliases_register_parser.set_defaults(func=cmd_aliases_register)

    recommend_parser = subparsers.add_parser(
        "recommend",
        help="Advisory refinement recommendations (read-only, non-blocking).",
    )
    recommend_subs = recommend_parser.add_subparsers(dest="recommend_command", required=True)

    recommend_tag_parser = recommend_subs.add_parser(
        "tag",
        help="Recommend manual refinement for one or more tags (batch).",
    )
    recommend_tag_parser.add_argument(
        "--tag",
        action="append",
        help="Tag to evaluate. Comma-separated values and/or repeated flags are accepted.",
    )
    recommend_tag_parser.add_argument(
        "--file",
        help="Input file path (one tag per line).",
    )
    recommend_tag_parser.add_argument(
        "--format-name",
        default="unknown",
        help="Target format name for DB-backed reasons (default: unknown).",
    )
    recommend_tag_parser.add_argument(
        "--rule-only",
        action="store_true",
        help="Bypass DB reads and use deterministic rule-only recommendation logic.",
    )
    _add_base_db_args(recommend_tag_parser)
    recommend_tag_parser.set_defaults(func=cmd_recommend_tag)

    recommend_translation_parser = recommend_subs.add_parser(
        "translation",
        help="Recommend translation quality for a source tag (rule-only, no DB).",
    )
    recommend_translation_parser.add_argument("--source-tag", required=True)
    recommend_translation_parser.add_argument(
        "--translation",
        help="Observed translation. Omit or pass empty for a missing-translation check.",
    )
    recommend_translation_parser.add_argument(
        "--language",
        default="ja",
        help="Translation language code (default: ja).",
    )
    recommend_translation_parser.add_argument(
        "--target-scope",
        choices=["base", "user"],
        help="Patch target scope for proposal output. Must be paired with --target-tag-id.",
    )
    recommend_translation_parser.add_argument(
        "--target-tag-id",
        type=int,
        help="Patch target tag id for proposal output. Must be paired with --target-scope.",
    )
    recommend_translation_parser.set_defaults(func=cmd_recommend_translation)

    recommend_record_parser = recommend_subs.add_parser(
        "record",
        help="Recommend refinement for tag search JSONL item records from stdin.",
    )
    recommend_record_parser.add_argument(
        "--format-name",
        help="Target format name. Defaults to each input row format_name or unknown.",
    )
    recommend_record_parser.add_argument(
        "--target-scope",
        choices=["base", "user"],
        help="Override proposal target scope. Defaults to inference from tag_id.",
    )
    _add_base_db_args(recommend_record_parser)
    recommend_record_parser.set_defaults(func=cmd_recommend_record)

    list_commands_parser = subparsers.add_parser(
        "list-commands",
        help="Emit machine-readable metadata for all commands.",
    )
    list_commands_parser.set_defaults(func=cmd_list_commands)

    # Base DB correction patch pipeline (#58 / #60 / #61).
    from genai_tag_db_tools.services.base_patch.cli import register_feedback_commands

    register_feedback_commands(subparsers)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    # argparse の失敗 (必須引数欠落・不正サブコマンド・型不正) も契約どおり JSONL の
    # error 行 + exit code 2 で返す。--help や正常終了 (code 0) はそのまま通す。
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            emit_error(
                errors.INVALID_INPUT,
                "invalid command-line arguments (see stderr or --help)",
                retryable=False,
                user_action_required=True,
            )
        raise
    # CLI 境界: あらゆる失敗を構造化エラー行 (kind=error) + exit code へマッピングする。
    # traceback だけで終わらせず、stdout の JSONL 最終行に必ず error を出す (#31)。
    try:
        args.func(args)
    except Exception as exc:  # CLI top-level error boundary (see #31)
        info = errors.classify_exception(exc)
        emit_error(
            info.code,
            str(exc) or type(exc).__name__,
            retryable=info.retryable,
            user_action_required=info.user_action_required,
            hint=errors.hint_for(info.code),
        )
        # 予期しない内部エラーのみ、診断用に traceback を stderr へ (stdout は JSONL 専用)。
        if info.code == errors.INTERNAL_ERROR:
            traceback.print_exc(file=sys.stderr)
        sys.exit(info.exit_code)
