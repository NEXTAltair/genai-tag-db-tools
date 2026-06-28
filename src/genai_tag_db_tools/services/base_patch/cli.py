"""CLI wiring for the base DB correction patch pipeline.

Adds the ``feedback`` subcommand group to the ``tag-db`` CLI:

- ``tag-db feedback validate-base-patches`` (#58)
- ``tag-db feedback export-base-patches`` (#61)
- ``tag-db feedback apply-base-patches`` (#60)

Emit helpers are imported lazily from :mod:`genai_tag_db_tools.cli` to avoid an import
cycle (the main CLI registers this module at parser-build time).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from genai_tag_db_tools.services.base_patch.apply import apply_base_patch_file
from genai_tag_db_tools.services.base_patch.export import export_base_patch_file
from genai_tag_db_tools.services.base_patch.validate import validate_base_patch_file


def _reader_for_base_db(args: argparse.Namespace) -> Any | None:
    """``--base-db`` が指定されていれば read-only reader を返す。"""
    if not getattr(args, "base_db", None):
        return None
    from genai_tag_db_tools.cli import _set_db_paths
    from genai_tag_db_tools.db.repository import get_default_reader

    _set_db_paths(args.base_db, getattr(args, "user_db_dir", None))
    return get_default_reader()


def cmd_validate_base_patches(args: argparse.Namespace) -> None:
    from genai_tag_db_tools.cli import emit_item, emit_result

    reader = _reader_for_base_db(args)
    result = validate_base_patch_file(args.file, repo=reader, report=args.report)
    for item in result.items:
        emit_item(item)
    emit_result(
        "base patches validated",
        ok=result.ok,
        valid=result.valid_count,
        warning=result.warning_count,
        invalid=result.invalid_count,
        report=args.report,
    )


def cmd_export_base_patches(args: argparse.Namespace) -> None:
    from genai_tag_db_tools.cli import emit_item, emit_result

    reader = _reader_for_base_db(args)
    result = export_base_patch_file(
        args.input,
        args.output,
        reader=reader,
        validate=args.validate,
        report=args.report,
    )
    for row in result.rows:
        emit_item(row)
    emit_result(
        "base patches exported",
        output=args.output,
        exported=result.exported_count,
        skipped=result.skipped_count,
        failed=result.failed_count,
        validated=args.validate,
        report=args.report,
    )


def cmd_apply_base_patches(args: argparse.Namespace) -> None:
    from genai_tag_db_tools.cli import emit_item, emit_result
    from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
    from genai_tag_db_tools.db.runtime import create_session_factory

    if not args.base_db or len(args.base_db) != 1:
        raise ValueError("apply-base-patches requires exactly one --base-db (the build output)")

    factory = create_session_factory(Path(args.base_db[0]))
    reader = MergedTagReader(base_repo=TagReader(session_factory=factory))
    repository = TagRepository(session_factory=factory, reader=reader)

    dry_run = not args.apply
    result = apply_base_patch_file(
        [Path(p) for p in args.file],
        repository=repository,
        reader=reader,
        dry_run=dry_run,
        report=args.report,
    )
    for row in result.rows:
        emit_item(row)
    emit_result(
        "dry-run complete" if dry_run else "base patches applied",
        dry_run=dry_run,
        ok=result.ok,
        applied=result.applied_count,
        already_applied=result.already_applied_count,
        skipped=result.skipped_count,
        rejected=result.rejected_count,
        report=args.report,
    )


def register_feedback_commands(subparsers: argparse._SubParsersAction) -> None:
    """``tag-db feedback ...`` サブコマンドを登録する。"""
    feedback_parser = subparsers.add_parser("feedback", help="Base DB correction patch pipeline.")
    feedback_subs = feedback_parser.add_subparsers(dest="feedback_command", required=True)

    validate_parser = feedback_subs.add_parser(
        "validate-base-patches",
        help="Validate a base DB correction patch JSONL before apply (#58).",
    )
    validate_parser.add_argument("--file", required=True, help="Patch JSONL file path.")
    validate_parser.add_argument("--report", help="Optional validation report path (.tsv or .jsonl).")
    validate_parser.add_argument(
        "--base-db",
        action="append",
        help="Optional base DB sqlite path for name/format/type resolution. Repeat for multiple.",
    )
    validate_parser.add_argument("--user-db-dir", help=argparse.SUPPRESS)
    validate_parser.set_defaults(func=cmd_validate_base_patches)

    export_parser = feedback_subs.add_parser(
        "export-base-patches",
        help="Export base DB correction patches from approved feedback JSONL (#61).",
    )
    export_parser.add_argument("--input", required=True, help="Approved feedback JSONL file path.")
    export_parser.add_argument("--output", required=True, help="Output patch JSONL file path.")
    export_parser.add_argument(
        "--validate",
        action="store_true",
        default=False,
        help="Validate exported patches and mark valid ones as validated.",
    )
    export_parser.add_argument("--report", help="Optional export report path (.tsv or .jsonl).")
    export_parser.add_argument(
        "--base-db",
        action="append",
        help="Optional base DB sqlite path for name/format/type resolution. Repeat for multiple.",
    )
    export_parser.add_argument("--user-db-dir", help=argparse.SUPPRESS)
    export_parser.set_defaults(func=cmd_export_base_patches)

    apply_parser = feedback_subs.add_parser(
        "apply-base-patches",
        help="Apply validated base correction patches to a base DB build source (#60).",
    )
    apply_parser.add_argument(
        "--file",
        required=True,
        action="append",
        help="Patch JSONL file path. Repeat for multiple patch files.",
    )
    apply_parser.add_argument(
        "--base-db",
        action="append",
        required=True,
        help="Base DB sqlite build output to write to (exactly one).",
    )
    apply_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write to the base DB. Omit for dry-run (default).",
    )
    apply_parser.add_argument("--report", help="Optional apply report path (.tsv or .jsonl).")
    apply_parser.set_defaults(func=cmd_apply_base_patches)
