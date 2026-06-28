"""Validate base DB correction patches before apply (issue #58).

This module validates the minimal base correction patch envelope. It never mutates any
DB. When a ``repo`` (read-only :class:`MergedTagReader`-like object) is supplied, the
validator additionally resolves format names, tag names, type names, and alias cycles.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from genai_tag_db_tools.services.base_patch.models import (
    ALLOWED_STATUS_FIELDS,
    FORMAT_DEPENDENT_PATCH_TYPES,
    REJECTED_PATCH_TYPES,
    SCHEMA_VERSION,
    SUPPORTED_PATCH_TYPES,
    TARGET_TYPE_BY_PATCH_TYPE,
    BaseCorrectionPatch,
    PatchValidationIssue,
    PatchValidationItemResult,
    PatchValidationResult,
    compute_patch_id,
)
from genai_tag_db_tools.services.base_patch.report import ReportFormat, write_report

# validation report の列順。
REPORT_COLUMNS = (
    "line_number",
    "patch_id",
    "patch_type",
    "target_type",
    "target_tag",
    "format_name",
    "status",
    "error_code",
    "message",
)


class _Issues:
    """error / warning を蓄積するヘルパー。"""

    def __init__(self) -> None:
        self.errors: list[PatchValidationIssue] = []
        self.warnings: list[PatchValidationIssue] = []

    def error(self, code: str, message: str, *, field: str | None = None) -> None:
        self.errors.append(PatchValidationIssue(code=code, message=message, field=field))

    def warn(self, code: str, message: str, *, field: str | None = None) -> None:
        self.warnings.append(PatchValidationIssue(code=code, message=message, field=field))


def validate_base_patch(
    patch: BaseCorrectionPatch,
    *,
    repo: Any | None = None,
    line_number: int | None = None,
) -> PatchValidationItemResult:
    """1 つの base correction patch を検証する。DB は変更しない。"""
    issues = _Issues()

    if patch.schema_version != SCHEMA_VERSION:
        issues.error(
            "unsupported_schema_version",
            f"schema_version must be {SCHEMA_VERSION}, got {patch.schema_version}",
            field="schema_version",
        )

    _validate_scope(patch, issues)
    _validate_approval_metadata(patch, issues)

    if patch.patch_id is None:
        issues.warn("missing_patch_id", "patch_id is missing; it will be computed", field="patch_id")

    patch_type = patch.patch_type
    if patch_type in REJECTED_PATCH_TYPES:
        issues.error(
            "unsupported_patch_type",
            f"patch_type {patch_type!r} is not an apply patch type",
            field="patch_type",
        )
    elif patch_type not in SUPPORTED_PATCH_TYPES:
        issues.error(
            "unsupported_patch_type",
            f"unknown patch_type {patch_type!r}",
            field="patch_type",
        )
    else:
        _validate_target_type(patch, issues)
        _dispatch_patch_type(patch, repo, issues)

    status = "invalid" if issues.errors else ("warning" if issues.warnings else "valid")
    return PatchValidationItemResult(
        line_number=line_number,
        patch_id=patch.patch_id or _safe_patch_id(patch),
        patch_type=patch_type,
        target_type=patch.target_type,
        target_tag=patch.target_tag,
        format_name=patch.format_name,
        status=status,
        errors=issues.errors,
        warnings=issues.warnings,
    )


def validate_base_patch_file(
    path: str | Path,
    *,
    repo: Any | None = None,
    report: str | Path | None = None,
    report_format: ReportFormat | None = None,
) -> PatchValidationResult:
    """JSONL patch file を読み込んで全行を検証する。

    必須キー欠落で patch を構築できない行は ``missing_required_field`` として invalid に
    する (ファイル全体の読み込みは止めない)。
    """
    path = Path(path)
    items: list[PatchValidationItemResult] = []
    with path.open(encoding="utf-8") as fh:
        for line_number, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            items.append(_validate_line(stripped, line_number, repo))

    result = PatchValidationResult(items=items)
    if report is not None:
        write_validation_report(result, report, report_format=report_format)
    return result


def write_validation_report(
    result: PatchValidationResult,
    path: str | Path,
    *,
    report_format: ReportFormat | None = None,
) -> None:
    """validation report を TSV / JSONL で出力する。issue ごとに 1 行。"""
    rows: list[dict[str, object]] = []
    for item in result.items:
        base = {
            "line_number": item.line_number,
            "patch_id": item.patch_id,
            "patch_type": item.patch_type,
            "target_type": item.target_type,
            "target_tag": item.target_tag,
            "format_name": item.format_name,
            "status": item.status,
        }
        issues = item.errors or item.warnings
        if not issues:
            rows.append({**base, "error_code": None, "message": None})
            continue
        for issue in issues:
            rows.append({**base, "error_code": issue.code, "message": issue.message})
    write_report(Path(path), REPORT_COLUMNS, rows, report_format=report_format)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _validate_line(stripped: str, line_number: int, repo: Any | None) -> PatchValidationItemResult:
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return PatchValidationItemResult(
            line_number=line_number,
            status="invalid",
            errors=[PatchValidationIssue(code="invalid_json", message=f"invalid JSON: {exc}")],
        )
    if not isinstance(data, dict):
        return PatchValidationItemResult(
            line_number=line_number,
            status="invalid",
            errors=[
                PatchValidationIssue(code="missing_required_field", message="patch must be a JSON object")
            ],
        )
    try:
        patch = BaseCorrectionPatch.model_validate(data)
    except ValidationError as exc:
        return _missing_field_result(data, line_number, exc)
    return validate_base_patch(patch, repo=repo, line_number=line_number)


def _missing_field_result(
    data: dict[str, Any], line_number: int, exc: ValidationError
) -> PatchValidationItemResult:
    issues: list[PatchValidationIssue] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        code = "missing_required_field" if err["type"] in ("missing", "none_required") else "invalid_field"
        issues.append(PatchValidationIssue(code=code, message=f"{loc}: {err['msg']}", field=loc or None))
    if not issues:
        issues.append(PatchValidationIssue(code="missing_required_field", message=str(exc)))
    patch_type = data.get("patch_type") if isinstance(data.get("patch_type"), str) else None
    return PatchValidationItemResult(
        line_number=line_number,
        patch_type=patch_type,
        status="invalid",
        errors=issues,
    )


def _validate_scope(patch: BaseCorrectionPatch, issues: _Issues) -> None:
    scope = patch.scope
    if scope is None:
        return
    if scope in ("user", "local"):
        issues.error("invalid_scope", f"scope {scope!r} is not a base patch", field="scope")
    elif scope != "base":
        issues.error("invalid_scope", f"scope {scope!r} is not supported", field="scope")


def _validate_approval_metadata(patch: BaseCorrectionPatch, issues: _Issues) -> None:
    if patch.approved is False:
        issues.error("explicitly_unapproved", "approved=false patches are rejected", field="approved")
    if patch.validated is False:
        issues.error("explicitly_unvalidated", "validated=false patches are rejected", field="validated")
    if patch.approved is True and (not patch.approved_by or not patch.approved_at):
        issues.warn(
            "missing_approval_metadata",
            "approved=true without approved_by/approved_at",
            field="approved_by",
        )


def _validate_target_type(patch: BaseCorrectionPatch, issues: _Issues) -> None:
    expected = TARGET_TYPE_BY_PATCH_TYPE.get(patch.patch_type)
    if expected is None:
        return
    actual = patch.target_type
    if actual is not None and actual != expected:
        issues.error(
            "invalid_target_type",
            f"target.target_type {actual!r} does not match patch_type {patch.patch_type!r} "
            f"(expected {expected!r})",
            field="target.target_type",
        )


def _dispatch_patch_type(patch: BaseCorrectionPatch, repo: Any | None, issues: _Issues) -> None:
    if patch.patch_type in FORMAT_DEPENDENT_PATCH_TYPES:
        _validate_format(patch, repo, issues)

    match patch.patch_type:
        case "alias_addition":
            _validate_alias_addition(patch, repo, issues)
        case "preferred_tag_correction":
            _validate_preferred_correction(patch, repo, issues)
        case "translation_correction":
            _validate_translation(patch, issues)
        case "type_correction":
            _validate_type_correction(patch, repo, issues)
        case "status_correction":
            _validate_status_correction(patch, issues)
        case "tag_name_correction":
            _validate_tag_name_correction(patch, repo, issues)


def _validate_format(patch: BaseCorrectionPatch, repo: Any | None, issues: _Issues) -> None:
    format_name = patch.target.get("format_name")
    if not isinstance(format_name, str) or not format_name:
        issues.error(
            "missing_format_name",
            "format-dependent patch requires target.format_name",
            field="target.format_name",
        )
        return
    if format_name == "unknown":
        return
    if repo is not None and _resolve_format_id(repo, format_name) is None:
        issues.error(
            "invalid_format_name",
            f"format_name {format_name!r} could not be resolved",
            field="target.format_name",
        )


def _validate_alias_addition(patch: BaseCorrectionPatch, repo: Any | None, issues: _Issues) -> None:
    tag = patch.target_tag
    if tag is None:
        issues.error("missing_target_tag", "alias_addition requires target.tag", field="target.tag")
    if patch.proposed.get("alias") is not True:
        issues.error(
            "invalid_target_type", "alias_addition requires proposed.alias=true", field="proposed.alias"
        )
    preferred = _proposed_str(patch, "preferred_tag")
    if preferred is None:
        issues.error(
            "missing_preferred_tag",
            "alias_addition requires proposed.preferred_tag",
            field="proposed.preferred_tag",
        )
        return
    _check_alias_relation(tag, preferred, patch, repo, issues)


def _validate_preferred_correction(patch: BaseCorrectionPatch, repo: Any | None, issues: _Issues) -> None:
    tag = patch.target_tag
    if tag is None:
        issues.error(
            "missing_target_tag", "preferred_tag_correction requires target.tag", field="target.tag"
        )
    preferred = _proposed_str(patch, "preferred_tag")
    if preferred is None:
        issues.error(
            "missing_preferred_tag",
            "preferred_tag_correction requires proposed.preferred_tag",
            field="proposed.preferred_tag",
        )
        return
    _check_alias_relation(tag, preferred, patch, repo, issues)


def _check_alias_relation(
    tag: str | None,
    preferred: str,
    patch: BaseCorrectionPatch,
    repo: Any | None,
    issues: _Issues,
) -> None:
    if tag is not None and tag == preferred:
        issues.error(
            "self_alias", "alias tag and preferred tag must differ", field="proposed.preferred_tag"
        )
        return
    if repo is None or tag is None:
        return
    format_name = patch.format_name
    if format_name is None:
        return
    if _has_alias_cycle(repo, alias_tag=tag, preferred_tag=preferred, format_name=format_name):
        issues.error(
            "alias_cycle", f"alias {tag!r} -> {preferred!r} forms a cycle", field="proposed.preferred_tag"
        )


def _validate_translation(patch: BaseCorrectionPatch, issues: _Issues) -> None:
    if patch.target_tag is None:
        issues.error("missing_target_tag", "translation_correction requires target.tag", field="target.tag")
    field = patch.field
    if not field:
        issues.error(
            "invalid_field",
            "translation_correction requires target.field (e.g. translation.ja)",
            field="target.field",
        )
    translation = patch.proposed.get("translation")
    if not isinstance(translation, str) or not translation.strip():
        issues.error(
            "empty_translation",
            "proposed.translation must be a non-empty string",
            field="proposed.translation",
        )
    field_lang = _field_language(field)
    proposed_lang = patch.proposed.get("language")
    if field_lang and isinstance(proposed_lang, str) and proposed_lang and proposed_lang != field_lang:
        issues.error(
            "translation_language_mismatch",
            f"proposed.language {proposed_lang!r} does not match field language {field_lang!r}",
            field="proposed.language",
        )
    elif (
        field_lang == "ja"
        and isinstance(translation, str)
        and translation.strip()
        and _has_cjk_but_no_japanese(translation)
    ):
        # #54 の軽量チェック: ja 欄に CJK があるのに仮名/和文が無い値 (中国語語彙の疑い)。
        # 誤検出を避けるため warning に留める (romaji 等を error にしない)。
        issues.warn(
            "translation_language_mismatch",
            "translation.ja value contains CJK characters but no kana",
            field="proposed.translation",
        )


def _validate_type_correction(patch: BaseCorrectionPatch, repo: Any | None, issues: _Issues) -> None:
    if patch.target_tag is None:
        issues.error("missing_target_tag", "type_correction requires target.tag", field="target.tag")
    type_name = _proposed_str(patch, "type_name")
    if type_name is None:
        issues.error(
            "invalid_type_name", "type_correction requires proposed.type_name", field="proposed.type_name"
        )
        return
    format_name = patch.format_name
    if repo is None or format_name is None or format_name == "unknown":
        return
    format_id = _resolve_format_id(repo, format_name)
    if format_id is None:
        return
    if _resolve_type_id(repo, type_name, format_id) is None:
        issues.warn(
            "type_mapping_will_be_created",
            f"type_name {type_name!r} has no mapping for format {format_name!r}; builder may create it",
            field="proposed.type_name",
        )


def _validate_status_correction(patch: BaseCorrectionPatch, issues: _Issues) -> None:
    if patch.target_tag is None:
        issues.error("missing_target_tag", "status_correction requires target.tag", field="target.tag")
    field = patch.field
    if field not in ALLOWED_STATUS_FIELDS:
        issues.error(
            "status_field_not_allowed",
            f"status_correction field must be one of {sorted(ALLOWED_STATUS_FIELDS)}, got {field!r}",
            field="target.field",
        )
    deprecated = patch.proposed.get("deprecated")
    if not isinstance(deprecated, bool):
        issues.error(
            "invalid_deprecated_value", "proposed.deprecated must be a boolean", field="proposed.deprecated"
        )


def _validate_tag_name_correction(patch: BaseCorrectionPatch, repo: Any | None, issues: _Issues) -> None:
    source = patch.target.get("source_tag") or patch.target.get("tag")
    if not isinstance(source, str) or not source:
        issues.error(
            "missing_target_tag",
            "tag_name_correction requires target.source_tag or target.tag",
            field="target.source_tag",
        )
    proposed_tag = _proposed_str(patch, "tag")
    if proposed_tag is None:
        issues.error(
            "empty_proposed_tag",
            "tag_name_correction requires non-empty proposed.tag",
            field="proposed.tag",
        )
        return
    if proposed_tag != proposed_tag.strip() or "  " in proposed_tag:
        issues.warn("missing_patch_id", "proposed.tag is not normalized", field="proposed.tag")
    # MVP: 既存 TAGS.tag の rename は保守的に rejected にする。
    if repo is not None and isinstance(source, str) and source and source != proposed_tag:
        if _resolve_tag_id(repo, source) is not None:
            issues.error(
                "empty_proposed_tag",
                f"tag_name_correction would rename existing tag {source!r}; rejected in MVP",
                field="target.tag",
            )


# ---------------------------------------------------------------------------
# reader / parsing helpers
# ---------------------------------------------------------------------------


def _proposed_str(patch: BaseCorrectionPatch, key: str) -> str | None:
    value = patch.proposed.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _field_language(field: str | None) -> str | None:
    if field and field.startswith("translation."):
        return field.split(".", 1)[1] or None
    return None


def _has_cjk_but_no_japanese(text: str) -> bool:
    """CJK 表意文字を含むのに仮名が 1 つも無い (中国語の疑い) なら True。"""
    has_cjk = False
    has_kana = False
    for char in text:
        code = ord(char)
        if 0x4E00 <= code <= 0x9FFF:  # CJK Unified Ideographs
            has_cjk = True
        elif (0x3040 <= code <= 0x30FF) or (0xFF66 <= code <= 0xFF9D):  # Hiragana / Katakana
            has_kana = True
    return has_cjk and not has_kana


def _resolve_format_id(repo: Any, format_name: str) -> int | None:
    getter = getattr(repo, "get_format_id", None)
    if getter is None:
        return None
    try:
        format_id = int(getter(format_name))
    except ValueError:
        return None
    return format_id if format_id > 0 else None


def _resolve_tag_id(repo: Any, tag: str) -> int | None:
    getter = getattr(repo, "get_tag_id_by_name", None)
    if getter is None:
        return None
    try:
        return getter(tag, partial=False)
    except ValueError:
        return None


def _resolve_type_id(repo: Any, type_name: str, format_id: int) -> int | None:
    getter = getattr(repo, "get_type_id_for_format", None)
    if getter is None:
        return None
    return getter(type_name, format_id)


def _has_alias_cycle(repo: Any, *, alias_tag: str, preferred_tag: str, format_name: str) -> bool:
    """preferred tag の alias chain を辿り、alias_tag に戻れば cycle とみなす。"""
    format_id = _resolve_format_id(repo, format_name)
    get_status = getattr(repo, "get_tag_status", None)
    if format_id is None or get_status is None:
        return False
    current = preferred_tag
    seen: set[str] = set()
    for _ in range(64):
        if current == alias_tag:
            return True
        if current in seen:
            return False
        seen.add(current)
        tag_id = _resolve_tag_id(repo, current)
        if tag_id is None:
            return False
        status = get_status(tag_id, format_id)
        if status is None or not getattr(status, "alias", False):
            return False
        preferred_id = getattr(status, "preferred_tag_id", None)
        if preferred_id is None or preferred_id == tag_id:
            return False
        next_tag = _tag_name_by_id(repo, preferred_id)
        if next_tag is None:
            return False
        current = next_tag
    return False


def _tag_name_by_id(repo: Any, tag_id: int) -> str | None:
    getter = getattr(repo, "get_tag_by_id", None)
    if getter is None:
        return None
    tag = getter(tag_id)
    return getattr(tag, "tag", None) if tag is not None else None


def _safe_patch_id(patch: BaseCorrectionPatch) -> str | None:
    try:
        return compute_patch_id(patch)
    except (TypeError, ValueError):
        return None
