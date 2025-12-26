from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genai_tag_db_tools.db.repository import MergedTagReader
from genai_tag_db_tools.io import hf_downloader
from genai_tag_db_tools.models import (
    DbCacheConfig,
    DbSourceRef,
    EnsureDbRequest,
    EnsureDbResult,
    TagRecordPublic,
    TagRegisterRequest,
    TagRegisterResult,
    TagSearchRequest,
    TagSearchResult,
    TagSearchRow,
    TagStatisticsResult,
)
from genai_tag_db_tools.services.app_services import TagRegisterService
from genai_tag_db_tools.utils.cleanup_str import TagCleaner


@dataclass(frozen=True)
class _ManifestSignature:
    etag: str | None
    path: str | None
    downloaded_at: str | None


def _manifest_signature(manifest: dict[str, Any] | None) -> _ManifestSignature | None:
    if not manifest:
        return None
    return _ManifestSignature(
        etag=manifest.get("etag"),
        path=manifest.get("path"),
        downloaded_at=manifest.get("downloaded_at"),
    )


def _compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _to_spec(source: DbSourceRef) -> hf_downloader.HFDatasetSpec:
    return hf_downloader.HFDatasetSpec(
        repo_id=source.repo_id,
        filename=source.filename,
        revision=source.revision,
    )


def _to_cache_dir(cache: DbCacheConfig) -> Path:
    return Path(cache.cache_dir)


def build_downloaded_at_utc() -> str:
    return datetime.now(UTC).isoformat()


def ensure_db(request: EnsureDbRequest) -> EnsureDbResult:
    spec = _to_spec(request.source)
    dest_dir = _to_cache_dir(request.cache)
    manifest_path = hf_downloader._manifest_path(dest_dir, spec)
    before = _manifest_signature(hf_downloader._load_manifest(manifest_path))

    db_path = hf_downloader.ensure_db_ready(spec, dest_dir=dest_dir, token=request.cache.token)

    after = _manifest_signature(hf_downloader._load_manifest(manifest_path))
    downloaded = after is not None and after != before
    sha256 = _compute_sha256(db_path)
    return EnsureDbResult(db_path=str(db_path), downloaded=downloaded, sha256=sha256)


def ensure_databases(requests: list[EnsureDbRequest]) -> list[EnsureDbResult]:
    if not requests:
        raise ValueError("requests は空にできません")

    cache_dir = requests[0].cache.cache_dir
    token = requests[0].cache.token
    for req in requests[1:]:
        if req.cache.cache_dir != cache_dir:
            raise ValueError("cache_dir は全てのリクエストで一致させてください")
        if req.cache.token != token:
            raise ValueError("token は全てのリクエストで一致させてください")

    specs = [_to_spec(req.source) for req in requests]
    dest_dir = _to_cache_dir(requests[0].cache)

    before = {
        spec: _manifest_signature(
            hf_downloader._load_manifest(hf_downloader._manifest_path(dest_dir, spec))
        )
        for spec in specs
    }

    paths = hf_downloader.ensure_databases_ready(specs, dest_dir=dest_dir, token=token)

    results: list[EnsureDbResult] = []
    for spec, path in zip(specs, paths, strict=True):
        after = _manifest_signature(
            hf_downloader._load_manifest(hf_downloader._manifest_path(dest_dir, spec))
        )
        downloaded = after is not None and after != before.get(spec)
        results.append(
            EnsureDbResult(
                db_path=str(path),
                downloaded=downloaded,
                sha256=_compute_sha256(path),
            )
        )

    return results


def _filter_rows(rows: list[TagSearchRow], request: TagSearchRequest) -> list[TagSearchRow]:
    filtered: list[TagSearchRow] = []
    format_names = set(request.format_names or [])
    type_names = set(request.type_names or [])

    for row in rows:
        usage_count = row["usage_count"] or 0
        if not request.include_aliases and row["alias"] is True:
            continue
        if not request.include_deprecated and row["deprecated"] is True:
            continue
        if format_names:
            format_statuses = row.get("format_statuses") or {}
            if not any(fmt in format_statuses for fmt in format_names):
                continue
        if type_names and row["type_name"] not in type_names:
            continue
        if request.min_usage is not None and usage_count < request.min_usage:
            continue
        if request.max_usage is not None and usage_count > request.max_usage:
            continue
        filtered.append(row)
    return filtered


def search_tags(repo: MergedTagReader, request: TagSearchRequest) -> TagSearchResult:
    format_name = (
        request.format_names[0] if request.format_names and len(request.format_names) == 1 else None
    )
    type_name = request.type_names[0] if request.type_names and len(request.type_names) == 1 else None

    rows = repo.search_tags(
        request.query,
        partial=True,
        format_name=format_name,
        type_name=type_name,
        resolve_preferred=request.resolve_preferred,
    )
    rows = _filter_rows(rows, request)
    items = [
        TagRecordPublic(
            tag=row["tag"],
            source_tag=row["source_tag"],
            format_name=format_name,
            type_id=row["type_id"],
            type_name=row["type_name"],
            alias=row["alias"],
            deprecated=row["deprecated"],
            usage_count=row["usage_count"],
            translations=row["translations"],
            format_statuses=row["format_statuses"],
        )
        for row in rows
    ]
    return TagSearchResult(items=items, total=len(items))


def register_tag(service: TagRegisterService, request: TagRegisterRequest) -> TagRegisterResult:
    return service.register_tag(request)


def get_statistics(repo: MergedTagReader) -> TagStatisticsResult:
    tag_statuses = repo.list_tag_statuses()
    alias_tag_ids = {status.tag_id for status in tag_statuses if status.alias}
    return TagStatisticsResult(
        total_tags=len(repo.list_tags()),
        total_aliases=len(alias_tag_ids),
        total_formats=len(repo.get_tag_formats()),
        total_types=len(repo.get_all_types()),
    )


def _normalize_prompt_tags(tags: str) -> list[str]:
    normalized_text = TagCleaner.clean_format(tags)
    raw_tags = [tag.strip() for tag in normalized_text.split(",") if tag.strip()]
    cleaned_tags: list[str] = []
    for tag in raw_tags:
        cleaned = TagCleaner.clean_tags(tag)
        if cleaned:
            cleaned_tags.extend([item.strip() for item in cleaned.split(",") if item.strip()])
    return cleaned_tags


def _lookup_tags(repo: MergedTagReader, tags: list[str], format_name: str) -> dict[str, str]:
    unique_tags = list(dict.fromkeys(tags))
    if not unique_tags:
        return {}

    if hasattr(repo, "search_tags_bulk"):
        rows_by_tag = repo.search_tags_bulk(
            unique_tags,
            format_name=format_name,
            resolve_preferred=True,
        )
        return {
            tag: rows_by_tag[tag]["tag"]
            for tag in unique_tags
            if tag in rows_by_tag and rows_by_tag[tag].get("tag")
        }

    tag_map: dict[str, str] = {}
    for tag in unique_tags:
        rows = repo.search_tags(tag, partial=False, format_name=format_name, resolve_preferred=True)
        if rows:
            tag_map[tag] = rows[0]["tag"]
    return tag_map


def convert_tags(repo: MergedTagReader, tags: str, format_name: str, separator: str = ", ") -> str:
    """Convert comma-separated tags to the specified format.
    - Normalize input before lookup
    - Use batch lookup when available
    """
    if not tags.strip():
        return tags

    format_id = repo.get_format_id(format_name)
    if format_id is None:
        return tags

    normalized_tags = _normalize_prompt_tags(tags)
    if not normalized_tags:
        return tags

    tag_map = _lookup_tags(repo, normalized_tags, format_name)
    word_map: dict[str, str] = {}
    converted_list: list[str] = []

    for tag in normalized_tags:
        converted = tag_map.get(tag)
        if converted:
            converted_list.append(converted)
            continue

        if " " in tag:
            words = [word for word in tag.split(" ") if word]
            missing = [word for word in words if word not in word_map]
            if missing:
                word_map.update(_lookup_tags(repo, missing, format_name))
            converted_list.extend([word_map.get(word, word) for word in words])
            continue

        converted_list.append(tag)

    return separator.join(converted_list)


def get_tag_formats(repo: MergedTagReader) -> list[str]:
    """利用可能なフォーマット一覧を取得します。
    Args:
        repo: MergedTagReader インスタンス

    Returns:
        list[str]: フォーマット名リスト（例: ["danbooru", "e621", ...]）
    """
    return repo.get_tag_formats()
