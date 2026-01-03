from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from genai_tag_db_tools.db import runtime
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
from genai_tag_db_tools.services.tag_register import TagRegisterService
from genai_tag_db_tools.utils.cleanup_str import TagCleaner


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


def build_downloaded_at_utc() -> str:
    return datetime.now(UTC).isoformat()


def _default_sources() -> list[DbSourceRef]:
    return [
        DbSourceRef(
            repo_id="NEXTAltair/genai-image-tag-db",
            filename="genai-image-tag-db-cc0.sqlite",
        ),
        DbSourceRef(
            repo_id="NEXTAltair/genai-image-tag-db-mit",
            filename="genai-image-tag-db-mit.sqlite",
        ),
        DbSourceRef(
            repo_id="NEXTAltair/genai-image-tag-db-CC4",
            filename="genai-image-tag-db-cc4.sqlite",
        ),
    ]


def ensure_databases(requests: list[EnsureDbRequest]) -> list[EnsureDbResult]:
    if not requests:
        raise ValueError("requests は空にできません")

    results: list[EnsureDbResult] = []
    for req in requests:
        spec = _to_spec(req.source)
        db_path, is_cached = hf_downloader.download_with_offline_fallback(spec, token=req.cache.token)

        results.append(
            EnsureDbResult(
                db_path=str(db_path),
                sha256=_compute_sha256(db_path),
                revision=None,
                cached=is_cached,
            )
        )

    return results


def initialize_databases(
    user_db_dir: Path | str | None = None,
    sources: list[DbSourceRef] | None = None,
    token: str | None = None,
    *,
    init_user_db: bool | None = None,
    format_name: str | None = None,
) -> list[EnsureDbResult]:
    """Download base DBs (if needed) and initialize runtime.

    Args:
        user_db_dir: User DB directory (user_tags.sqlite). If None, defaults to OS cache dir
            when init_user_db is True.
        sources: Optional list of DbSourceRef. If None, default sources are used.
        token: Hugging Face access token (optional).
        init_user_db: Whether to initialize the user DB. Defaults to True when user_db_dir
            is provided, otherwise False.
        format_name: Format name for user DB (e.g., "Lorairo", "MyApp").
            If None, defaults to "tag-db".
    """
    resolved_user_db_dir = Path(user_db_dir) if user_db_dir is not None else None
    if init_user_db is None:
        init_user_db = resolved_user_db_dir is not None

    cache_dir = resolved_user_db_dir or hf_downloader.default_cache_dir()
    cache = DbCacheConfig(cache_dir=str(cache_dir), token=token)
    requested_sources = sources or _default_sources()
    requests = [EnsureDbRequest(source=source, cache=cache) for source in requested_sources]

    results = ensure_databases(requests)
    base_paths = [Path(result.db_path) for result in results]
    runtime.set_base_database_paths(base_paths)
    runtime.init_engine(base_paths[0])

    if init_user_db:
        runtime.init_user_db(cache_dir, format_name=format_name)

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
        partial=request.partial,
        format_name=format_name,
        type_name=type_name,
        resolve_preferred=request.resolve_preferred,
    )
    rows = _filter_rows(rows, request)
    items = [
        TagRecordPublic(
            tag=row["tag"],
            source_tag=row["source_tag"],
            tag_id=row["tag_id"],
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
    if not format_id:
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


def get_all_type_names(repo: MergedTagReader) -> list[str]:
    """全てのtype_name一覧を取得します。

    Args:
        repo: MergedTagReader インスタンス

    Returns:
        list[str]: type_name リスト（例: ["character", "general", "meta", ...]）

    Example:
        >>> from genai_tag_db_tools import get_all_type_names
        >>> from genai_tag_db_tools.db.runtime import get_default_reader
        >>> reader = get_default_reader()
        >>> all_types = get_all_type_names(reader)
        >>> print(all_types)
        ["character", "general", "meta", "unknown"]
    """
    return repo.get_all_types()


def get_format_type_names(repo: MergedTagReader, format_id: int) -> list[str]:
    """指定されたformat_idで利用可能なtype_name一覧を取得します。

    Args:
        repo: MergedTagReader インスタンス
        format_id: Format ID

    Returns:
        list[str]: 指定formatで利用可能なtype_nameリスト

    Example:
        >>> from genai_tag_db_tools import get_format_type_names
        >>> from genai_tag_db_tools.db.runtime import get_default_reader
        >>> reader = get_default_reader()
        >>> format_types = get_format_type_names(reader, format_id=1000)
        >>> print(format_types)
        ["unknown", "character", "general"]
    """
    return repo.get_tag_types(format_id)


def get_unknown_type_tags(repo: MergedTagReader, format_id: int) -> list[TagRecordPublic]:
    """指定されたformat_idでtype_name="unknown"のタグ一覧を取得します。

    Args:
        repo: MergedTagReader インスタンス
        format_id: Format ID

    Returns:
        list[TagRecordPublic]: unknown typeタグのリスト

    Example:
        >>> from genai_tag_db_tools import get_unknown_type_tags
        >>> from genai_tag_db_tools.db.runtime import get_default_reader
        >>> reader = get_default_reader()
        >>> unknown_tags = get_unknown_type_tags(reader, format_id=1000)
        >>> print(f"Found {len(unknown_tags)} unknown type tags")
    """
    tag_ids = repo.get_unknown_type_tag_ids(format_id)
    if not tag_ids:
        return []

    # Get format_name for this format_id
    format_name = repo.get_format_name(format_id)

    # Get tag details for each tag_id
    results: list[TagRecordPublic] = []
    for tag_id in tag_ids:
        tag = repo.get_tag_by_id(tag_id)
        if not tag:
            continue

        tag_status = repo.get_tag_status(tag_id, format_id)
        if not tag_status:
            continue

        # Get type_name (should be "unknown")
        type_name = repo.get_type_name_by_format_type_id(format_id, tag_status.type_id)

        results.append(
            TagRecordPublic(
                tag=tag.tag,
                source_tag=tag.source_tag,
                tag_id=tag.tag_id,
                format_name=format_name,
                type_id=tag_status.type_id,
                type_name=type_name or "unknown",
                alias=tag_status.alias,
                deprecated=tag_status.deprecated,
                usage_count=None,
                translations={},
                format_statuses={},
            )
        )

    return results


def update_tags_type_batch(repo_writer, tag_updates: list, format_id: int) -> None:
    """複数のタグのtype_idを一括更新します。

    この関数は、指定されたタグリストに対してtype_nameからtype_idへの変換と更新を
    一括で行います。type_nameが未登録の場合は自動的に作成され、format内でのtype_idも
    自動採番されます。全ての更新は単一トランザクション内で実行されるため、
    途中でエラーが発生した場合は全てロールバックされます。

    Args:
        repo_writer: TagRepository インスタンス（書き込み権限が必要）
        tag_updates: TagTypeUpdate オブジェクトのリスト
        format_id: Format ID

    Raises:
        ValueError: 無効なformat_idまたはtag_idが指定された場合
        Exception: トランザクションが失敗した場合

    Example:
        >>> from genai_tag_db_tools import update_tags_type_batch
        >>> from genai_tag_db_tools.models import TagTypeUpdate
        >>> from genai_tag_db_tools.db.runtime import get_default_repository
        >>> repo = get_default_repository()
        >>> updates = [
        ...     TagTypeUpdate(tag_id=123, type_name="character"),
        ...     TagTypeUpdate(tag_id=456, type_name="general"),
        ... ]
        >>> update_tags_type_batch(repo, updates, format_id=1000)
    """
    repo_writer.update_tags_type_batch(tag_updates, format_id)
