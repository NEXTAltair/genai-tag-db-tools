from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from genai_tag_db_tools.db import runtime
from genai_tag_db_tools.db.repository import MergedTagReader
from genai_tag_db_tools.db.schema import USER_TAG_ID_OFFSET
from genai_tag_db_tools.io import hf_downloader
from genai_tag_db_tools.models import (
    DbCacheConfig,
    DbFeedbackProposal,
    DbSourceRef,
    EnsureDbRequest,
    EnsureDbResult,
    ProposalTarget,
    RefinementReason,
    RefinementRecommendation,
    RefinementSuggestion,
    TagRecordPublic,
    TagRef,
    TagRegisterRequest,
    TagRegisterResult,
    TagSearchRequest,
    TagSearchResult,
    TagSearchRow,
    TagStatisticsResult,
)
from genai_tag_db_tools.services.tag_register import TagRegisterService
from genai_tag_db_tools.utils.cleanup_str import TagCleaner

_REFINEMENT_REASON_MESSAGES = {
    "empty_normalized_tag": "正規化後のタグが空です。",
    "normalization_changes_tag": "既存の正規化でタグ表記が変わります。",
    "broad_single_word": "単語が広すぎるため、人による確認が必要です。",
    "deprecated_tag": "非推奨タグとして扱われています。",
    "unknown_type": "タグ type が unknown です。",
    "type_correction_candidate": "タグ type の見直し候補です。",
    "status_type_conflict": "タグの用途と status/type の組み合わせに確認が必要です。",
    "training_unsuitable": "学習タグとして不向きな情報タグまたは管理用 token の可能性があります。",
    "site_info_token": "サイト情報トークンのため、通常タグとして扱うべきか確認が必要です。",
    "wrong_language_translation": "翻訳の言語が対象言語と異なる可能性があります。",
    "missing_translation": "翻訳が空です。",
    "overlong_translation": "翻訳が長すぎるため、タグ翻訳として確認が必要です。",
    "description_like_translation": "翻訳が説明文のように見えます。",
    "translation_mismatch": "翻訳が元タグと一致していない可能性があります。",
    "low_quality_translation": "翻訳品質が低い可能性があります。",
    "alias_tag": "入力タグは alias です。preferred tag の利用候補があります。",
    "non_preferred_tag": "入力タグは preferred tag ではありません。",
    "typo_alias_candidate": "近い既存タグがあり、typo alias 候補として確認できます。",
    "ambiguous_alias_candidates": "近い既存タグが複数あるため、alias 先を決め打ちできません。",
    "missing_preferred_tag": "alias/preferred 関係の preferred tag が見つかりません。",
    "translation_match_tag": "入力が既存タグの翻訳に一致しています。通常タグとして扱うべきか確認が必要です。",
    "missing_format_status": "指定 format でのタグ status が見つかりません。",
    "external_id_tag": "外部サイト ID を表す情報タグの可能性があります。",
}
_BROAD_SINGLE_WORD_TAGS = {
    "animal",
    "background",
    "building",
    "character",
    "clothes",
    "clothing",
    "flower",
    "food",
    "girl",
    "man",
    "object",
    "person",
    "plant",
    "style",
    "woman",
}
_ANGLE_BRACKET_PATTERN = re.compile(r"<[^>]+>")
_SITE_INFO_TOKEN_SUFFIXES = ("_id", " id")
_ASCII_ALPHA_PATTERN = re.compile(r"[A-Za-z]")
_ASCII_ONLY_PATTERN = re.compile(r"^[\x00-\x7f]+$")
_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_JAPANESE_KANA_PATTERN = re.compile(r"[\u3040-\u30ff]")
_JA_DESCRIPTION_PATTERN = re.compile(r"(です|ます|である|された|するため|について|。|、|:)")
_ZH_SPECIFIC_CHARS = set(
    "们这为么后发头见观蓝绿红黄龙马门风鸟鱼脸长与"
)
_LOW_QUALITY_TRANSLATIONS = {
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "undefined",
    "todo",
    "tbd",
    "不明",
    "未定",
}
_MAX_TRANSLATION_CHARS = 30
_MAX_TRANSLATION_WORDS = 8
_EXTERNAL_ID_SITES = {
    "artstation",
    "danbooru",
    "deviantart",
    "e621",
    "gelbooru",
    "instagram",
    "nijie",
    "pixiv",
    "twitter",
    "x",
}
_MANAGEMENT_TOKEN_PREFIXES = (
    "rating:",
    "score:",
    "source:",
    "parent:",
    "child:",
    "md5:",
    "file:",
    "order:",
    "user:",
)


def _refinement_reason(
    code: str,
    *,
    field: str | None = None,
    evidence: list[dict[str, str | int | float | bool | None]] | None = None,
) -> RefinementReason:
    return RefinementReason(
        code=code,
        message=_REFINEMENT_REASON_MESSAGES[code],
        field=field,
        evidence=evidence or [],
    )


def _looks_like_site_info_token(tag: str) -> bool:
    stripped = tag.strip()
    lowered = stripped.lower()
    return (
        stripped.startswith("__")
        or stripped.endswith("__")
        or lowered.endswith(_SITE_INFO_TOKEN_SUFFIXES)
    )


def _looks_like_external_id_tag(tag: str) -> bool:
    lowered = tag.strip().lower().replace("-", "_").replace(" ", "_")
    if not lowered.endswith("_id"):
        return False
    return lowered[:-3] in _EXTERNAL_ID_SITES


def _looks_like_management_token(tag: str) -> bool:
    stripped = tag.strip()
    lowered = stripped.lower()
    return (
        stripped.startswith("__")
        or stripped.endswith("__")
        or lowered.startswith(_MANAGEMENT_TOKEN_PREFIXES)
    )


def _normalize_refinement_tag(tag: str) -> str:
    cleaned = TagCleaner.clean_format(tag)
    if not cleaned:
        return cleaned

    parts: list[str] = []
    position = 0
    for match in _ANGLE_BRACKET_PATTERN.finditer(cleaned):
        parts.append(cleaned[position : match.start()].lower())
        parts.append(match.group(0))
        position = match.end()
    parts.append(cleaned[position:].lower())
    return "".join(parts)


def _refinement_score(reasons: list[RefinementReason], suggestions: list[RefinementSuggestion]) -> float:
    codes = {reason.code for reason in reasons}
    if not codes:
        return 0.0
    if "empty_normalized_tag" in codes:
        return 1.0
    if "missing_preferred_tag" in codes:
        return 1.0
    if "alias_tag" in codes or "non_preferred_tag" in codes:
        return 0.9
    if any(suggestion.kind == "correction_candidate" for suggestion in suggestions):
        return 0.8
    if "typo_alias_candidate" in codes:
        return 0.7
    if "ambiguous_alias_candidates" in codes:
        return 0.5
    return 0.6


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


def default_sources() -> list[DbSourceRef]:
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
    requested_sources = sources or default_sources()
    requests = [EnsureDbRequest(source=source, cache=cache) for source in requested_sources]

    results = ensure_databases(requests)
    base_paths = [Path(result.db_path) for result in results]
    runtime.set_base_database_paths(base_paths)
    runtime.init_engine(base_paths[0])

    if init_user_db:
        runtime.init_user_db(cache_dir, format_name=format_name)

    return results


def _concrete_filter_names(names: list[str] | None) -> list[str]:
    if not names:
        return []
    return [name for name in names if name and name.lower() != "all"]


def search_tags(repo: MergedTagReader, request: TagSearchRequest) -> TagSearchResult:
    format_names = _concrete_filter_names(request.format_names)
    type_names = _concrete_filter_names(request.type_names)
    format_name = format_names[0] if len(format_names) == 1 else None

    common_kwargs = {
        "partial": request.partial,
        "format_names": format_names or None,
        "type_names": type_names or None,
        "alias": None if request.include_aliases else False,
        "deprecated": None if request.include_deprecated else False,
        "min_usage": request.min_usage,
        "max_usage": request.max_usage,
        "resolve_preferred": request.resolve_preferred,
    }

    # フィルタの正本は repository (filtered_tag_ids) に一元化する。core_api 側で行を再フィルタ
    # しない: build_row は単一 format でないと usage_count/deprecated 等を 0/False で返すため、
    # Python 側で再判定すると repository が正しく拾った行を落としてしまう (#45)。
    if request.limit is not None:
        page = repo.search_tags(
            request.query,
            **common_kwargs,
            limit=request.limit,
            offset=request.offset,
        )
        total: int | None = None  # bounded fetch のため全件数は不明
    else:
        rows = repo.search_tags(
            request.query,
            **common_kwargs,
            limit=None,
            offset=0,
        )
        total = len(rows)
        page = rows[request.offset :] if request.offset else rows

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
        for row in page
    ]
    return TagSearchResult(items=items, total=total)


def register_tag(service: TagRegisterService, request: TagRegisterRequest) -> TagRegisterResult:
    return service.register_tag(request)


def _tag_scope(tag_id: int) -> str:
    return "user" if tag_id >= USER_TAG_ID_OFFSET else "base"


def _resolve_recommendation_format_id(repo: MergedTagReader, format_name: str) -> int | None:
    try:
        format_id = repo.get_format_id(format_name)
    except ValueError:
        return None
    return format_id or None


def _effective_recommendation_format_name(repo: MergedTagReader, format_name: str) -> str:
    if format_name != "unknown":
        return format_name
    if _resolve_recommendation_format_id(repo, "danbooru") is not None:
        return "danbooru"
    return format_name


def _search_exact_recommendation_rows(
    repo: MergedTagReader,
    tag: str,
    *,
    format_name: str,
    format_id: int | None,
) -> list[TagSearchRow]:
    effective_format_name = format_name if format_id is not None else None
    return repo.search_tags(
        tag,
        partial=False,
        format_name=effective_format_name,
        resolve_preferred=False,
    )


def _canonical_exact_recommendation_rows(rows: list[TagSearchRow], tag: str) -> list[TagSearchRow]:
    normalized = tag.casefold()
    return [
        row
        for row in rows
        if row["tag"].casefold() == normalized
        or (row["source_tag"] is not None and row["source_tag"].casefold() == normalized)
    ]


def _preferred_tag_for_status(repo: MergedTagReader, preferred_tag_id: int):
    return repo.get_tag_by_id(preferred_tag_id)


def _status_from_row_for_unknown_format(row: TagSearchRow) -> tuple[bool, int | None, bool]:
    alias_preferred_tag_id = _alias_preferred_tag_id_from_format_status(row)
    if row["alias"] or alias_preferred_tag_id is not None:
        return (
            True,
            alias_preferred_tag_id or _preferred_tag_id_from_format_status(row) or row["tag_id"],
            _deprecated_from_format_status(row),
        )
    preferred_tag_id = _preferred_tag_id_from_format_status(row)
    if preferred_tag_id is not None and preferred_tag_id != row["tag_id"]:
        return False, preferred_tag_id, _deprecated_from_format_status(row)
    return False, None, _deprecated_from_format_status(row)


def _alias_preferred_tag_id_from_format_status(row: TagSearchRow) -> int | None:
    for status in (row.get("format_statuses") or {}).values():
        if not isinstance(status, Mapping) or status.get("alias") is not True:
            continue
        preferred_tag_id = status.get("preferred_tag_id")
        if isinstance(preferred_tag_id, int):
            return preferred_tag_id
    return None


def _preferred_tag_id_from_format_status(row: TagSearchRow) -> int | None:
    for status in (row.get("format_statuses") or {}).values():
        if not isinstance(status, Mapping):
            continue
        preferred_tag_id = status.get("preferred_tag_id")
        if isinstance(preferred_tag_id, int):
            return preferred_tag_id
    return None


def _deprecated_from_format_status(row: TagSearchRow) -> bool:
    if row["deprecated"]:
        return True
    return any(
        isinstance(status, Mapping) and status.get("deprecated") is True
        for status in (row.get("format_statuses") or {}).values()
    )


def _db_feedback_alias_proposal(
    *,
    source_tag: str,
    normalized_tag: str,
    preferred_tag_id: int,
    preferred_tag: str,
    format_name: str,
    reason_code: str,
    confidence: float,
) -> DbFeedbackProposal:
    return DbFeedbackProposal(
        kind="alias_addition",
        target=ProposalTarget(
            kind="alias",
            target_scope="user",
            target_tag_id=None,
            format_name=format_name,
            preferred_scope=_tag_scope(preferred_tag_id),
            preferred_tag_id=preferred_tag_id,
        ),
        current=None,
        proposed={
            "alias": True,
            "alias_tag": normalized_tag,
            "preferred_tag": preferred_tag,
            "preferred_scope": _tag_scope(preferred_tag_id),
            "preferred_tag_id": preferred_tag_id,
        },
        confidence=confidence,
        source="recommend_manual_refinement",
        reason_codes=[reason_code],
        evidence=[{"source_tag": source_tag, "normalized_tag": normalized_tag}],
    )


def _edit_distance_at_most(left: str, right: str, limit: int) -> int | None:
    if abs(len(left) - len(right)) > limit:
        return None
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        row_min = i
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return None
        previous = current
    distance = previous[-1]
    return distance if distance <= limit else None


def _typo_distance_limit(tag: str) -> int:
    return 1 if len(tag) <= 5 else 2


def _candidate_sort_key(input_tag: str, candidate: tuple[int, str, int]) -> tuple[int, float, str]:
    tag_id, tag, distance = candidate
    return (distance, -SequenceMatcher(None, input_tag, tag).ratio(), tag, tag_id)


def _recommendation_statuses_by_tag(
    repo: MergedTagReader,
    format_id: int | None,
) -> dict[int, list[Any]]:
    statuses = repo.list_tag_statuses()
    result: dict[int, list[object]] = {}
    for status in statuses:
        if format_id is not None and status.format_id != format_id:
            continue
        result.setdefault(status.tag_id, []).append(status)
    return result


def _is_typo_candidate_status_usable(
    statuses_by_tag: dict[int, list[Any]],
    tag_id: int,
    *,
    format_id: int | None,
) -> bool:
    statuses = statuses_by_tag.get(tag_id, [])
    if format_id is not None and not statuses:
        return False
    if not statuses:
        return True
    return not any(status.alias or status.deprecated for status in statuses)


def _find_typo_candidates(
    repo: MergedTagReader,
    normalized_tag: str,
    *,
    format_id: int | None,
    limit: int = 3,
) -> list[tuple[int, str, int]]:
    if not normalized_tag:
        return []

    distance_limit = _typo_distance_limit(normalized_tag)
    candidates: list[tuple[int, str, int]] = []
    seen_tags: set[str] = set()
    statuses_by_tag = _recommendation_statuses_by_tag(repo, format_id)
    for tag_obj in repo.list_tags():
        candidate_tag = tag_obj.tag
        if not candidate_tag:
            continue
        candidate_key = candidate_tag.lower()
        if candidate_key == normalized_tag.lower() or candidate_key in seen_tags:
            continue
        seen_tags.add(candidate_key)

        if not _is_typo_candidate_status_usable(
            statuses_by_tag,
            tag_obj.tag_id,
            format_id=format_id,
        ):
            continue
        distance = _edit_distance_at_most(normalized_tag.lower(), candidate_key, distance_limit)
        if distance is None:
            continue
        candidates.append((tag_obj.tag_id, candidate_tag, distance))

    return sorted(candidates, key=lambda candidate: _candidate_sort_key(normalized_tag, candidate))[
        :limit
    ]


def _recommend_from_db(
    *,
    repo: MergedTagReader,
    source_tag: str,
    normalized_tag: str,
    format_name: str,
) -> RefinementRecommendation | None:
    effective_format_name = _effective_recommendation_format_name(repo, format_name)
    format_id = _resolve_recommendation_format_id(repo, effective_format_name)
    exact_rows = _search_exact_recommendation_rows(
        repo,
        normalized_tag,
        format_name=effective_format_name,
        format_id=format_id,
    )
    raw_exact_rows = exact_rows
    exact_rows = _canonical_exact_recommendation_rows(exact_rows, normalized_tag)

    if raw_exact_rows and not exact_rows:
        reasons = [_refinement_reason("translation_match_tag")]
        return RefinementRecommendation(
            source_tag=source_tag,
            normalized_tag=normalized_tag,
            needs_refinement=True,
            score=_refinement_score(reasons, []),
            reasons=reasons,
            suggestions=[RefinementSuggestion(kind="review_only")],
        )

    if exact_rows:
        row = exact_rows[0]
        if format_id is None:
            alias, preferred_tag_id, deprecated = _status_from_row_for_unknown_format(row)
            if deprecated and not alias:
                reasons = [_refinement_reason("deprecated_tag")]
                return RefinementRecommendation(
                    source_tag=source_tag,
                    normalized_tag=normalized_tag,
                    needs_refinement=True,
                    score=_refinement_score(reasons, []),
                    reasons=reasons,
                    suggestions=[RefinementSuggestion(kind="review_only")],
                )
            if preferred_tag_id is not None and (alias or preferred_tag_id != row["tag_id"]):
                preferred_tag = _preferred_tag_for_status(repo, preferred_tag_id)
                if preferred_tag is None:
                    reasons = [_refinement_reason("missing_preferred_tag")]
                    return RefinementRecommendation(
                        source_tag=source_tag,
                        normalized_tag=normalized_tag,
                        needs_refinement=True,
                        score=_refinement_score(reasons, []),
                        reasons=reasons,
                        suggestions=[RefinementSuggestion(kind="review_only")],
                    )
                reason_code = "alias_tag" if alias else "non_preferred_tag"
                reasons = [_refinement_reason(reason_code)]
                suggestions = [
                    RefinementSuggestion(kind="correction_candidate", tag=preferred_tag.tag)
                ]
                return RefinementRecommendation(
                    source_tag=source_tag,
                    normalized_tag=normalized_tag,
                    needs_refinement=True,
                    score=_refinement_score(reasons, suggestions),
                    reasons=reasons,
                    suggestions=suggestions,
                )
            return RefinementRecommendation(
                source_tag=source_tag,
                normalized_tag=normalized_tag,
                needs_refinement=False,
                score=0.0,
            )
        status = repo.get_tag_status(row["tag_id"], format_id)
        if status is None:
            reasons = [_refinement_reason("missing_format_status")]
            return RefinementRecommendation(
                source_tag=source_tag,
                normalized_tag=normalized_tag,
                needs_refinement=True,
                score=_refinement_score(reasons, []),
                reasons=reasons,
                suggestions=[RefinementSuggestion(kind="review_only")],
            )
        if status.deprecated and not status.alias:
            reasons = [_refinement_reason("deprecated_tag")]
            return RefinementRecommendation(
                source_tag=source_tag,
                normalized_tag=normalized_tag,
                needs_refinement=True,
                score=_refinement_score(reasons, []),
                reasons=reasons,
                suggestions=[RefinementSuggestion(kind="review_only")],
            )
        if not status.alias and status.preferred_tag_id in (None, row["tag_id"]):
            return RefinementRecommendation(
                source_tag=source_tag,
                normalized_tag=normalized_tag,
                needs_refinement=False,
                score=0.0,
            )

        preferred_tag = _preferred_tag_for_status(repo, status.preferred_tag_id)
        if preferred_tag is None:
            reasons = [_refinement_reason("missing_preferred_tag")]
            return RefinementRecommendation(
                source_tag=source_tag,
                normalized_tag=normalized_tag,
                needs_refinement=True,
                score=_refinement_score(reasons, []),
                reasons=reasons,
                suggestions=[RefinementSuggestion(kind="review_only")],
            )

        reason_code = "alias_tag" if status.alias else "non_preferred_tag"
        reasons = [_refinement_reason(reason_code)]
        suggestions = [RefinementSuggestion(kind="correction_candidate", tag=preferred_tag.tag)]
        return RefinementRecommendation(
            source_tag=source_tag,
            normalized_tag=normalized_tag,
            needs_refinement=True,
            score=_refinement_score(reasons, suggestions),
            reasons=reasons,
            suggestions=suggestions,
        )

    candidates = _find_typo_candidates(repo, normalized_tag, format_id=format_id)
    if not candidates:
        return None

    best_distance = candidates[0][2]
    best_candidates = [candidate for candidate in candidates if candidate[2] == best_distance]
    if len(best_candidates) == 1:
        tag_id, candidate_tag, _distance = best_candidates[0]
        reasons = [_refinement_reason("typo_alias_candidate")]
        suggestions = [RefinementSuggestion(kind="correction_candidate", tag=candidate_tag)]
        return RefinementRecommendation(
            source_tag=source_tag,
            normalized_tag=normalized_tag,
            needs_refinement=True,
            score=_refinement_score(reasons, suggestions),
            reasons=reasons,
            suggestions=suggestions,
            proposals=[
                _db_feedback_alias_proposal(
                    source_tag=source_tag,
                    normalized_tag=normalized_tag,
                    preferred_tag_id=tag_id,
                    preferred_tag=candidate_tag,
                    format_name=effective_format_name,
                    reason_code="typo_alias_candidate",
                    confidence=0.7,
                )
            ],
        )

    reasons = [_refinement_reason("ambiguous_alias_candidates")]
    suggestions = [
        RefinementSuggestion(kind="correction_candidate", tag=candidate_tag)
        for _tag_id, candidate_tag, _distance in best_candidates
    ]
    return RefinementRecommendation(
        source_tag=source_tag,
        normalized_tag=normalized_tag,
        needs_refinement=True,
        score=_refinement_score(reasons, suggestions),
        reasons=reasons,
        suggestions=suggestions,
    )


def recommend_manual_refinement(
    tag: str,
    repo: MergedTagReader | None = None,
    *,
    format_name: str = "unknown",
) -> RefinementRecommendation:
    """Recommend whether a tag needs manual refinement before registration.

    Without a repo this remains deterministic and DB independent. When a merged
    reader is supplied, exact DB aliases/preferred relations and typo alias
    candidates are read through the overlay-aware repository without mutating DBs.
    """
    normalized_tag = _normalize_refinement_tag(tag)
    source_candidate = tag.strip()
    reasons: list[RefinementReason] = []
    suggestions: list[RefinementSuggestion] = []
    source_site_info_token = _looks_like_site_info_token(tag) or _looks_like_management_token(tag)
    source_external_id_token = (not source_site_info_token) and _looks_like_external_id_tag(tag)

    if repo is not None and not source_site_info_token and not source_external_id_token:
        db_recommendation = _recommend_from_db(
            repo=repo,
            source_tag=tag,
            normalized_tag=normalized_tag,
            format_name=format_name,
        )
        if db_recommendation is not None:
            return db_recommendation

    if not normalized_tag:
        reasons.append(_refinement_reason("empty_normalized_tag"))
        suggestions.append(RefinementSuggestion(kind="review_only"))
    elif source_site_info_token:
        reasons.append(_refinement_reason("site_info_token"))
        suggestions.append(RefinementSuggestion(kind="review_only"))
    elif source_external_id_token:
        reasons.append(_refinement_reason("external_id_tag"))
        suggestions.append(RefinementSuggestion(kind="review_only"))
    else:
        if normalized_tag != source_candidate:
            reasons.append(_refinement_reason("normalization_changes_tag"))
            suggestions.append(RefinementSuggestion(kind="correction_candidate", tag=normalized_tag))
        if normalized_tag.lower() in _BROAD_SINGLE_WORD_TAGS and " " not in normalized_tag:
            reasons.append(_refinement_reason("broad_single_word"))
            suggestions.append(RefinementSuggestion(kind="review_only"))

    return RefinementRecommendation(
        source_tag=tag,
        normalized_tag=normalized_tag,
        needs_refinement=bool(reasons),
        score=_refinement_score(reasons, suggestions),
        reasons=reasons,
        suggestions=suggestions,
    )


def needs_manual_refinement(tag: str) -> bool:
    """Compatibility helper returning only the recommendation boolean."""
    return recommend_manual_refinement(tag).needs_refinement


def recommend_translation_quality(
    source_tag: str,
    translation: str | None,
    *,
    language: str = "ja",
    target_scope: Literal["base", "user"] | None = None,
    target_tag_id: int | None = None,
    tag_ref: TagRef | None = None,
) -> RefinementRecommendation:
    """Advisory translation quality recommendation.

    The helper is DB independent and does not apply or validate overlay changes.
    When a target is supplied, proposals target the future
    USER_TAG_TRANSLATION_PATCH shape through target_scope + target_tag_id.
    """
    target_scope, target_tag_id = _resolve_translation_target(target_scope, target_tag_id, tag_ref)
    field = f"translation.{language}"
    observed = "" if translation is None else translation
    stripped = observed.strip()
    evidence_base: dict[str, str | int | float | bool | None] = {
        "field": field,
        "language": language,
        "source_tag": source_tag,
        "translation": observed,
    }
    if target_scope is not None and target_tag_id is not None:
        evidence_base["target_scope"] = target_scope
        evidence_base["target_tag_id"] = target_tag_id

    reasons: list[RefinementReason] = []
    suggestions: list[RefinementSuggestion] = []

    if not stripped:
        reasons.append(_translation_reason("missing_translation", field, evidence_base))
    else:
        reason_codes = _detect_translation_quality_reasons(
            source_tag=source_tag,
            translation=stripped,
            language=language,
        )
        reasons.extend(_translation_reason(code, field, evidence_base) for code in reason_codes)

    if reasons:
        suggestions.append(RefinementSuggestion(kind="review_only"))

    score = _translation_quality_score(reasons)
    proposals = _translation_quality_proposals(
        target_scope=target_scope,
        target_tag_id=target_tag_id,
        language=language,
        field=field,
        current_translation=observed,
        reason_codes=[reason.code for reason in reasons],
        evidence=[evidence_base],
        confidence=score,
    )

    return RefinementRecommendation(
        source_tag=source_tag,
        normalized_tag=_normalize_refinement_tag(source_tag),
        needs_refinement=bool(reasons),
        score=score,
        reasons=reasons,
        suggestions=suggestions,
        proposals=proposals,
    )


def _resolve_translation_target(
    target_scope: Literal["base", "user"] | None,
    target_tag_id: int | None,
    tag_ref: TagRef | None,
) -> tuple[Literal["base", "user"] | None, int | None]:
    if tag_ref is not None:
        if target_scope is not None and target_scope != tag_ref.scope:
            raise ValueError("target_scope conflicts with tag_ref.scope")
        if target_tag_id is not None and target_tag_id != tag_ref.tag_id:
            raise ValueError("target_tag_id conflicts with tag_ref.tag_id")
        return tag_ref.scope, tag_ref.tag_id
    if (target_scope is None) != (target_tag_id is None):
        raise ValueError("target_scope and target_tag_id must be provided together")
    return target_scope, target_tag_id


def _translation_reason(
    code: str,
    field: str,
    evidence: dict[str, str | int | float | bool | None],
) -> RefinementReason:
    return _refinement_reason(code, field=field, evidence=[evidence])


def _detect_translation_quality_reasons(source_tag: str, translation: str, language: str) -> list[str]:
    reasons: list[str] = []
    lowered = translation.lower()
    compact_translation = _compact_for_translation_compare(translation)
    compact_source = _compact_for_translation_compare(source_tag)

    if language == "ja" and _looks_like_chinese_for_ja(translation):
        reasons.append("wrong_language_translation")
    elif language == "ja" and _looks_like_english_only(translation):
        reasons.append("wrong_language_translation")

    if _is_overlong_translation(translation):
        reasons.append("overlong_translation")
    if _looks_description_like_translation(translation):
        reasons.append("description_like_translation")
    if compact_translation and compact_translation == compact_source and _ASCII_ALPHA_PATTERN.search(source_tag):
        reasons.append("translation_mismatch")
    if lowered in _LOW_QUALITY_TRANSLATIONS or _is_punctuation_only(translation):
        reasons.append("low_quality_translation")

    return reasons


def _looks_like_english_only(value: str) -> bool:
    return bool(_ASCII_ALPHA_PATTERN.search(value) and _ASCII_ONLY_PATTERN.fullmatch(value))


def _looks_like_chinese_for_ja(value: str) -> bool:
    if not _CJK_PATTERN.search(value) or _JAPANESE_KANA_PATTERN.search(value):
        return False
    return any(char in _ZH_SPECIFIC_CHARS for char in value)


def _is_overlong_translation(value: str) -> bool:
    return len(value) > _MAX_TRANSLATION_CHARS or len(value.split()) > _MAX_TRANSLATION_WORDS


def _looks_description_like_translation(value: str) -> bool:
    if _JA_DESCRIPTION_PATTERN.search(value):
        return True
    return len(value.split()) > 3 and _looks_like_english_only(value)


def _is_punctuation_only(value: str) -> bool:
    return bool(value) and not any(char.isalnum() for char in value)


def _compact_for_translation_compare(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.ASCII).lower()


def _translation_quality_score(reasons: list[RefinementReason]) -> float:
    if not reasons:
        return 0.0
    weights = {
        "missing_translation": 1.0,
        "wrong_language_translation": 0.9,
        "translation_mismatch": 0.8,
        "description_like_translation": 0.7,
        "overlong_translation": 0.6,
        "low_quality_translation": 0.6,
    }
    return max(weights.get(reason.code, 0.5) for reason in reasons)


def _translation_quality_proposals(
    *,
    target_scope: Literal["base", "user"] | None,
    target_tag_id: int | None,
    language: str,
    field: str,
    current_translation: str,
    reason_codes: list[str],
    evidence: list[dict[str, str | int | float | bool | None]],
    confidence: float,
) -> list[DbFeedbackProposal]:
    if target_scope is None or target_tag_id is None or not reason_codes:
        return []
    return [
        DbFeedbackProposal(
            kind="translation_correction",
            target=ProposalTarget(
                kind="translation",
                target_scope=target_scope,
                target_tag_id=target_tag_id,
                language=language,
            ),
            current={"field": field, "language": language, "translation": current_translation},
            proposed=None,
            confidence=confidence,
            source="translation_quality_recommendation",
            reason_codes=reason_codes,
            evidence=evidence,
        )
    ]


def _row_mapping(row: TagSearchRow | TagRecordPublic | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(row, TagRecordPublic):
        return row.model_dump()
    return row


def _infer_target_scope(tag_id: int, target_scope: Literal["base", "user"] | None) -> Literal["base", "user"]:
    if target_scope is not None:
        return target_scope
    return "user" if tag_id >= USER_TAG_ID_OFFSET else "base"


def _format_status(
    row: Mapping[str, Any],
    format_name: str,
    format_id: int | None = None,
) -> Mapping[str, Any]:
    format_statuses = row.get("format_statuses") or {}
    if isinstance(format_statuses, Mapping):
        keys = [format_name]
        if format_id is not None:
            keys.append(str(format_id))
        for key in keys:
            status = format_statuses.get(key)
            if isinstance(status, Mapping):
                return status
    return {}


def _status_value(row: Mapping[str, Any], status: Mapping[str, Any], key: str) -> Any:
    return status.get(key, row.get(key))


def _repo_tag_status(
    repo: MergedTagReader | None,
    tag_id: int,
    format_id: int | None,
) -> Any:
    if repo is None or format_id is None or not hasattr(repo, "get_tag_status"):
        return None
    return repo.get_tag_status(tag_id, format_id)


def _type_name_for_format(
    repo: MergedTagReader | None,
    format_id: int | None,
    type_id: Any,
) -> str | None:
    if repo is None or format_id is None or not isinstance(type_id, int):
        return None
    if not hasattr(repo, "get_type_name_by_format_type_id"):
        return None
    return repo.get_type_name_by_format_type_id(format_id, type_id)


def _has_format_type(repo: MergedTagReader | None, format_name: str, type_name: str) -> bool:
    if repo is None or format_name == "unknown":
        return False
    try:
        format_id = repo.get_format_id(format_name)
    except ValueError:
        return False
    return repo.get_type_id_for_format(type_name, format_id) is not None


def _type_id_for_format(repo: MergedTagReader | None, format_name: str, type_name: str) -> int | None:
    if repo is None or format_name == "unknown":
        return None
    try:
        format_id = repo.get_format_id(format_name)
    except ValueError:
        return None
    return repo.get_type_id_for_format(type_name, format_id)


def _proposal_target(
    *,
    kind: Literal["tag_type", "tag_status"],
    target_scope: Literal["base", "user"],
    target_tag_id: int,
    format_name: str,
) -> ProposalTarget:
    return ProposalTarget(
        kind=kind,
        target_scope=target_scope,
        target_tag_id=target_tag_id,
        format_name=format_name,
    )


def recommend_tag_record_refinement(
    row: TagSearchRow | TagRecordPublic | Mapping[str, Any],
    *,
    format_name: str | None = None,
    target_scope: Literal["base", "user"] | None = None,
    repo: MergedTagReader | None = None,
) -> RefinementRecommendation:
    """Recommend DB-backed tag status/type refinements without mutating any DB.

    The detector consumes an already overlay-composed search/status row. Format-specific
    values are read from ``format_statuses[format_name]`` when available, then fall back
    to the row-level fields. Unknown formats are represented as ``format_name="unknown"``
    rather than ``None`` so proposals can still target USER_TAG_STATUS_PATCH shape.
    """
    data = _row_mapping(row)
    source_tag_value = str(data.get("source_tag") or "")
    tag = str(data.get("tag") or source_tag_value)
    target_tag_id = int(data["tag_id"])
    resolved_scope = _infer_target_scope(target_tag_id, target_scope)
    resolved_format_name = format_name or data.get("format_name") or "unknown"
    resolved_format_id = _resolve_recommendation_format_id(repo, resolved_format_name) if repo else None
    status = _format_status(data, resolved_format_name, resolved_format_id)
    repo_status = _repo_tag_status(repo, target_tag_id, resolved_format_id)
    has_explicit_format_statuses = "format_statuses" in data
    if (
        resolved_format_name != "unknown"
        and resolved_scope == "user"
        and repo_status is None
        and not status
        and has_explicit_format_statuses
        and (resolved_format_id is not None or bool(data.get("format_statuses") or {}))
    ):
        missing_status_reasons = [_refinement_reason("missing_format_status")]
        missing_status_suggestions = [RefinementSuggestion(kind="review_only")]
        return RefinementRecommendation(
            source_tag=tag,
            normalized_tag=_normalize_refinement_tag(tag),
            needs_refinement=True,
            score=_refinement_score(missing_status_reasons, missing_status_suggestions),
            reasons=missing_status_reasons,
            suggestions=missing_status_suggestions,
        )

    type_id = repo_status.type_id if repo_status is not None else _status_value(data, status, "type_id")
    type_name_value = _status_value(data, status, "type_name")
    resolved_type_name = _type_name_for_format(repo, resolved_format_id, type_id)
    type_name = str(resolved_type_name or type_name_value or "").lower()
    deprecated = bool(
        repo_status.deprecated if repo_status is not None else _status_value(data, status, "deprecated")
    )

    reasons: list[RefinementReason] = []
    suggestions: list[RefinementSuggestion] = []
    proposals: list[DbFeedbackProposal] = []
    evidence: list[dict[str, str | int | float | bool | None]] = [
        {
            "tag": tag,
            "target_scope": resolved_scope,
            "target_tag_id": target_tag_id,
            "format_name": resolved_format_name,
            "type_id": type_id if isinstance(type_id, int) else None,
            "type_name": type_name or None,
            "deprecated": deprecated,
        }
    ]

    def add_reason(code: str) -> None:
        if code not in {reason.code for reason in reasons}:
            reasons.append(_refinement_reason(code))

    if deprecated:
        add_reason("deprecated_tag")
        suggestions.append(RefinementSuggestion(kind="review_only"))

    unknown_type = type_name == "unknown" or (type_id == 0 and not type_name)
    if unknown_type:
        add_reason("unknown_type")
        suggestions.append(RefinementSuggestion(kind="review_only"))

    token_values = [tag]
    if source_tag_value and source_tag_value != tag:
        token_values.append(source_tag_value)
    site_info = any(
        _looks_like_site_info_token(value) or _looks_like_management_token(value)
        for value in token_values
    )
    external_id = any(_looks_like_external_id_tag(value) for value in token_values)
    training_unsuitable = site_info or external_id
    if site_info:
        add_reason("site_info_token")
    if external_id:
        add_reason("external_id_tag")
    if training_unsuitable:
        add_reason("training_unsuitable")
        suggestions.append(RefinementSuggestion(kind="review_only"))
        if not deprecated:
            add_reason("status_type_conflict")
            proposals.append(
                DbFeedbackProposal(
                    kind="status_correction",
                    target=_proposal_target(
                        kind="tag_status",
                        target_scope=resolved_scope,
                        target_tag_id=target_tag_id,
                        format_name=resolved_format_name,
                    ),
                    current={"deprecated": deprecated},
                    proposed={"deprecated": True},
                    confidence=0.7,
                    source="tag_record_refinement",
                    reason_codes=["training_unsuitable"],
                    evidence=evidence,
                )
            )

    if training_unsuitable and type_name not in {"", "meta"} and _has_format_type(
        repo, resolved_format_name, "meta"
    ):
        proposed_type_id = _type_id_for_format(repo, resolved_format_name, "meta")
        add_reason("type_correction_candidate")
        proposals.append(
            DbFeedbackProposal(
                kind="type_correction",
                target=_proposal_target(
                    kind="tag_type",
                    target_scope=resolved_scope,
                    target_tag_id=target_tag_id,
                    format_name=resolved_format_name,
                ),
                current={
                    "type_id": type_id if isinstance(type_id, int) else None,
                    "type_name": type_name or None,
                },
                proposed={"type_id": proposed_type_id, "type_name": "meta"},
                confidence=0.55,
                source="tag_record_refinement",
                reason_codes=["type_correction_candidate"],
                evidence=evidence,
            )
        )

    score = 0.0
    if reasons:
        score = 0.9 if deprecated else 0.7 if training_unsuitable else 0.5

    return RefinementRecommendation(
        source_tag=tag,
        normalized_tag=tag,
        needs_refinement=bool(reasons),
        score=score,
        reasons=reasons,
        suggestions=suggestions,
        proposals=proposals,
    )


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


def _lookup_tag_rows(repo: MergedTagReader, tags: list[str], format_name: str) -> dict[str, TagSearchRow]:
    """入力タグを DB で検索し、keyword → 検索結果行の辞書を返す。

    完全一致検索 (partial=False) は repository 層で大文字小文字を無視する
    (COLLATE NOCASE / lower 照合) ため、入力の case が DB と異なっても解決される。

    Args:
        repo: タグ検索に用いる MergedTagReader。
        tags: 検索対象のタグ文字列リスト。
        format_name: 変換先フォーマット名。

    Returns:
        ヒットしたタグについて keyword をキー、TagSearchRow を値とする辞書。
        ``tag`` フィールドが空の行は除外する。
    """
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
            tag: rows_by_tag[tag]
            for tag in unique_tags
            if tag in rows_by_tag and rows_by_tag[tag].get("tag")
        }

    tag_rows: dict[str, TagSearchRow] = {}
    for tag in unique_tags:
        rows = repo.search_tags(tag, partial=False, format_name=format_name, resolve_preferred=True)
        if rows:
            tag_rows[tag] = rows[0]
    return tag_rows


def _is_excluded_type(row: TagSearchRow, exclude_types_lower: set[str]) -> bool:
    """検索結果行の type_name が除外対象なら True を返す。"""
    if not exclude_types_lower:
        return False
    type_name = row.get("type_name")
    if not type_name:
        return False
    return type_name.lower() in exclude_types_lower


def convert_tags(
    repo: MergedTagReader,
    tags: str,
    format_name: str,
    separator: str = ", ",
    *,
    exclude_types: list[str] | None = None,
) -> str:
    """Convert comma-separated tags to the specified format.

    - Normalize input before lookup
    - Use batch lookup when available
    - Exact-match lookup is case-insensitive (see ``_lookup_tag_rows``)

    Args:
        repo: タグ検索に用いる MergedTagReader。
        tags: カンマ区切りの入力タグ文字列。
        format_name: 変換先フォーマット名 (例: "danbooru")。
        separator: 出力タグの結合文字列。
        exclude_types: 出力から除外する type_name のリスト (例: ["meta"])。
            None の場合は除外しない (デフォルト挙動)。指定タグが該当 type に
            解決された場合、そのタグは出力から取り除かれる。

    Returns:
        変換後のタグ文字列。
    """
    if not tags.strip():
        return tags

    format_id = repo.get_format_id(format_name)
    if not format_id:
        return tags

    normalized_tags = _normalize_prompt_tags(tags)
    if not normalized_tags:
        return tags

    exclude_types_lower = {t.lower() for t in exclude_types} if exclude_types else set()

    tag_rows = _lookup_tag_rows(repo, normalized_tags, format_name)
    word_rows: dict[str, TagSearchRow] = {}
    converted_list: list[str] = []

    for tag in normalized_tags:
        row = tag_rows.get(tag)
        if row is not None and row.get("tag"):
            if _is_excluded_type(row, exclude_types_lower):
                continue
            converted_list.append(row["tag"])
            continue

        if " " in tag:
            words = [word for word in tag.split(" ") if word]
            missing = [word for word in words if word not in word_rows]
            if missing:
                word_rows.update(_lookup_tag_rows(repo, missing, format_name))
            for word in words:
                word_row = word_rows.get(word)
                if word_row is not None and word_row.get("tag"):
                    if _is_excluded_type(word_row, exclude_types_lower):
                        continue
                    converted_list.append(word_row["tag"])
                else:
                    converted_list.append(word)
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
