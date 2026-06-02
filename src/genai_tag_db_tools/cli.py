import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass

from genai_tag_db_tools.core_api import (
    ensure_databases,
    get_statistics,
    initialize_databases,
    register_tag,
    search_tags,
)
from genai_tag_db_tools.db import runtime
from genai_tag_db_tools.db.repository import get_default_reader, get_default_repository
from genai_tag_db_tools.models import (
    DbCacheConfig,
    DbSourceRef,
    EnsureDbRequest,
    TagRegisterRequest,
    TagSearchRequest,
    TagTranslationInput,
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
    requests = [
        EnsureDbRequest(
            source=DbSourceRef(
                repo_id=parsed.repo_id,
                filename=parsed.filename,
                revision=parsed.revision,
            ),
            cache=cache,
        )
        for parsed in (_parse_source(value) for value in args.source)
    ]
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
    if not args.user_db_dir:
        raise ValueError("--user-db-dir is required for register")

    _set_db_paths(args.base_db, args.user_db_dir)
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


def _add_base_db_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-db",
        action="append",
        help="Base DB sqlite path. Repeat for multiple. Omit to auto-download default sources from HF.",
    )
    parser.add_argument(
        "--user-db-dir",
        help="User database directory. Required for register.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="genai-tag-db-tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_many_parser = subparsers.add_parser("ensure-dbs", help="Download multiple DBs.")
    ensure_many_parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="repo_id/filename[@revision]. Repeat for multiple sources.",
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

    args = parser.parse_args()
    args.func(args)
