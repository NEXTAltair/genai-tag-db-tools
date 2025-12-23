import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass

from genai_tag_db_tools.core_api import (
    ensure_databases,
    ensure_db,
    get_statistics,
    register_tag,
    search_tags,
)
from genai_tag_db_tools.db import runtime
from genai_tag_db_tools.db.repository import TagRepository, get_default_repository
from genai_tag_db_tools.models import (
    DbCacheConfig,
    DbSourceRef,
    EnsureDbRequest,
    TagRegisterRequest,
    TagSearchRequest,
    TagTranslationInput,
)
from genai_tag_db_tools.services.app_services import TagRegisterService


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
    return DbCacheConfig(
        cache_dir=args.cache_dir,
        token=args.token,
        max_cache_bytes=args.max_cache_bytes,
    )


def _dump(obj: object) -> None:
    if hasattr(obj, "model_dump"):
        payload = obj.model_dump()
    elif isinstance(obj, list):
        payload = [item.model_dump() if hasattr(item, "model_dump") else item for item in obj]
    else:
        payload = obj

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _set_db_paths(base_db_paths: Iterable[str], user_db_dir: str | None) -> None:
    runtime.set_base_database_paths(list(base_db_paths))
    if user_db_dir:
        runtime.init_user_db(user_db_dir)


def _build_register_service() -> TagRegisterService:
    repo = TagRepository(runtime.get_user_session_factory())
    return TagRegisterService(repo)


def cmd_ensure_db(args: argparse.Namespace) -> None:
    cache = _build_cache_config(args)
    source = DbSourceRef(
        repo_id=args.repo_id,
        filename=args.filename,
        revision=args.revision,
    )
    result = ensure_db(EnsureDbRequest(source=source, cache=cache))
    _dump(result)


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
    _dump(results)


def cmd_search(args: argparse.Namespace) -> None:
    _set_db_paths(args.base_db, args.user_db_dir)
    repo = get_default_repository()
    request = TagSearchRequest(
        query=args.query,
        format_names=args.format_name or None,
        type_names=args.type_name or None,
        resolve_preferred=args.resolve_preferred,
        include_aliases=args.include_aliases,
        include_deprecated=args.include_deprecated,
        limit=args.limit,
        offset=args.offset,
    )
    result = search_tags(repo, request)
    _dump(result)


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
    _dump(result)


def cmd_stats(args: argparse.Namespace) -> None:
    _set_db_paths(args.base_db, args.user_db_dir)
    repo = get_default_repository()
    result = get_statistics(repo)
    _dump(result)


def _add_base_db_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-db",
        action="append",
        required=True,
        help="Base database path. Repeat for multiple base DBs.",
    )
    parser.add_argument(
        "--user-db-dir",
        help="User database directory. Required for register.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="genai-tag-db-tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_parser = subparsers.add_parser("ensure-db", help="Download one DB.")
    ensure_parser.add_argument("--repo-id", required=True)
    ensure_parser.add_argument("--filename", required=True)
    ensure_parser.add_argument("--revision")
    ensure_parser.add_argument("--cache-dir", required=True)
    ensure_parser.add_argument("--token")
    ensure_parser.add_argument("--max-cache-bytes", type=int)
    ensure_parser.set_defaults(func=cmd_ensure_db)

    ensure_many_parser = subparsers.add_parser("ensure-dbs", help="Download multiple DBs.")
    ensure_many_parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="repo_id/filename[@revision]. Repeat for multiple sources.",
    )
    ensure_many_parser.add_argument("--cache-dir", required=True)
    ensure_many_parser.add_argument("--token")
    ensure_many_parser.add_argument("--max-cache-bytes", type=int)
    ensure_many_parser.set_defaults(func=cmd_ensure_dbs)

    search_parser = subparsers.add_parser("search", help="Search tags.")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--format-name", action="append")
    search_parser.add_argument("--type-name", action="append")
    search_parser.add_argument("--resolve-preferred", action="store_true")
    search_parser.add_argument("--include-aliases", action="store_true")
    search_parser.add_argument("--include-deprecated", action="store_true")
    search_parser.add_argument("--limit", type=int, default=100)
    search_parser.add_argument("--offset", type=int, default=0)
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

    args = parser.parse_args()
    args.func(args)
