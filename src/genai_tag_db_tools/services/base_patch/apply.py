"""Apply approved correction patches to base DB build sources (issue #60).

This module reads a validated base correction patch JSONL and applies each patch to a base
DB (the SQLite that the dataset-builder produces). It re-runs the minimal validation from
#58 before applying and writes an apply report. It never touches a user-local overlay DB.

The service is intentionally decoupled from runtime globals: it takes a writer
(:class:`TagRepository`-like) and a read-only ``reader`` so it can be pointed at any build
output / build source DB.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from genai_tag_db_tools.services.base_patch.models import (
    BaseCorrectionPatch,
    PatchValidationItemResult,
)
from genai_tag_db_tools.services.base_patch.report import ReportFormat, write_report
from genai_tag_db_tools.services.base_patch.validate import validate_base_patch

REPORT_COLUMNS = (
    "patch_id",
    "patch_type",
    "target_type",
    "target_tag",
    "format_name",
    "field",
    "status",
    "reason",
    "db_changes",
)

ApplyStatus = Literal["applied", "skipped", "rejected", "already_applied"]


class BasePatchApplyRow(BaseModel):
    """apply report の 1 行。"""

    patch_id: str | None = None
    patch_type: str | None = None
    target_type: str | None = None
    target_tag: str | None = None
    format_name: str | None = None
    field: str | None = None
    status: ApplyStatus
    reason: str | None = None
    db_changes: list[str] = Field(default_factory=list)


class BasePatchApplyResult(BaseModel):
    """apply 結果のコンテナ。"""

    rows: list[BasePatchApplyRow] = Field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.rejected_count == 0

    @property
    def applied_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "applied")

    @property
    def already_applied_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "already_applied")

    @property
    def skipped_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "skipped")

    @property
    def rejected_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "rejected")


class _ApplyReject(ValueError):
    """patch を rejected にすべき状況で投げる内部例外。"""


class BasePatchApplyService:
    """validated base correction patch を base DB build source に反映する。"""

    def __init__(self, repository: Any, reader: Any, *, dry_run: bool = False) -> None:
        self._repo = repository
        self._reader = reader
        self._dry_run = dry_run
        # TagRepository.create_tag は self._reader を使う。未注入なら補う。
        if getattr(repository, "_reader", None) is None:
            try:
                repository._reader = reader
            except AttributeError:
                pass

    def apply_patch(self, patch: BaseCorrectionPatch) -> BasePatchApplyRow:
        item = validate_base_patch(patch, repo=self._reader)
        if item.status == "invalid":
            return self._row(patch, "rejected", _validation_reason(item))

        try:
            changes = self._dispatch(patch)
        except _ApplyReject as exc:
            return self._row(patch, "rejected", str(exc))

        status: ApplyStatus = "applied"
        reason: str | None = None
        if changes is None:
            status, reason, changes = "already_applied", "patch already reflected", []
        return self._row(patch, status, reason, changes)

    def apply_patches(self, patches: list[BaseCorrectionPatch]) -> BasePatchApplyResult:
        result = BasePatchApplyResult(dry_run=self._dry_run)
        for patch in patches:
            result.rows.append(self.apply_patch(patch))
        return result

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, patch: BaseCorrectionPatch) -> list[str] | None:
        match patch.patch_type:
            case "alias_addition":
                return self._apply_alias_addition(patch)
            case "preferred_tag_correction":
                return self._apply_preferred_correction(patch)
            case "translation_correction":
                return self._apply_translation(patch)
            case "type_correction":
                return self._apply_type_correction(patch)
            case "status_correction":
                return self._apply_status_correction(patch)
            case "tag_name_correction":
                return self._apply_tag_name(patch)
            case _:  # pragma: no cover - guarded by validation
                raise _ApplyReject(f"unsupported patch_type {patch.patch_type!r}")

    def _apply_alias_addition(self, patch: BaseCorrectionPatch) -> list[str] | None:
        alias_tag = _require(patch.target_tag, "target.tag")
        preferred_tag = _require(_proposed_str(patch, "preferred_tag"), "proposed.preferred_tag")
        format_id = self._resolve_or_create_format(patch.format_name)

        preferred_id = self._ensure_tag(preferred_tag)
        alias_id = self._ensure_tag(alias_tag)
        if alias_id == preferred_id:
            raise _ApplyReject("alias tag and preferred tag resolve to the same tag")

        existing = self._tag_status(alias_id, format_id)
        if existing is not None and existing.alias and existing.preferred_tag_id == preferred_id:
            return None
        type_id = self._alias_type_id(existing, preferred_id, format_id)
        if self._dry_run:
            return [f"TAG_STATUS.alias tag_id={alias_id} -> preferred_tag_id={preferred_id}"]
        self._repo.update_tag_status(
            tag_id=alias_id,
            format_id=format_id,
            alias=True,
            preferred_tag_id=preferred_id,
            type_id=type_id,
        )
        return [f"TAG_STATUS.alias tag_id={alias_id} -> preferred_tag_id={preferred_id}"]

    def _apply_preferred_correction(self, patch: BaseCorrectionPatch) -> list[str] | None:
        alias_tag = _require(patch.target_tag, "target.tag")
        preferred_tag = _require(_proposed_str(patch, "preferred_tag"), "proposed.preferred_tag")
        format_id = self._resolve_or_create_format(patch.format_name)

        alias_id = self._resolve_tag_id(alias_tag)
        if alias_id is None:
            raise _ApplyReject(f"target alias tag {alias_tag!r} does not exist")
        preferred_id = self._ensure_tag(preferred_tag)
        if alias_id == preferred_id:
            raise _ApplyReject("alias tag and preferred tag resolve to the same tag")

        existing = self._tag_status(alias_id, format_id)
        if existing is not None and existing.alias and existing.preferred_tag_id == preferred_id:
            return None
        type_id = self._alias_type_id(existing, preferred_id, format_id)
        if self._dry_run:
            return [f"TAG_STATUS.preferred_tag_id tag_id={alias_id} -> {preferred_id}"]
        self._repo.update_tag_status(
            tag_id=alias_id,
            format_id=format_id,
            alias=True,
            preferred_tag_id=preferred_id,
            type_id=type_id,
        )
        return [f"TAG_STATUS.preferred_tag_id tag_id={alias_id} -> {preferred_id}"]

    def _apply_translation(self, patch: BaseCorrectionPatch) -> list[str] | None:
        tag = _require(patch.target_tag, "target.tag")
        language = _require(_field_language(patch.field), "target.field")
        translation = _require(_proposed_str(patch, "translation"), "proposed.translation")
        tag_id = self._ensure_tag(tag)
        if self._translation_exists(tag_id, language, translation):
            return None
        if self._dry_run:
            return [f"TAG_TRANSLATIONS tag_id={tag_id} +{language}"]
        self._repo.add_or_update_translation(tag_id, language, translation)
        return [f"TAG_TRANSLATIONS tag_id={tag_id} +{language}"]

    def _apply_type_correction(self, patch: BaseCorrectionPatch) -> list[str] | None:
        tag = _require(patch.target_tag, "target.tag")
        type_name = _require(_proposed_str(patch, "type_name"), "proposed.type_name")
        format_id = self._resolve_or_create_format(patch.format_name)
        tag_id = self._ensure_tag(tag)

        type_id = self._resolve_or_create_type_id(format_id, type_name)
        existing = self._tag_status(tag_id, format_id)
        if existing is not None and existing.type_id == type_id:
            return None
        alias, preferred_id, deprecated = self._existing_or_default(existing, tag_id)
        if self._dry_run:
            return [f"TAG_STATUS.type_id tag_id={tag_id} -> {type_id}"]
        self._repo.update_tag_status(
            tag_id=tag_id,
            format_id=format_id,
            alias=alias,
            preferred_tag_id=preferred_id,
            type_id=type_id,
            deprecated=deprecated,
        )
        return [f"TAG_STATUS.type_id tag_id={tag_id} -> {type_id}"]

    def _apply_status_correction(self, patch: BaseCorrectionPatch) -> list[str] | None:
        tag = _require(patch.target_tag, "target.tag")
        deprecated = patch.proposed.get("deprecated")
        if not isinstance(deprecated, bool):
            raise _ApplyReject("proposed.deprecated must be a boolean")
        format_id = self._resolve_or_create_format(patch.format_name)
        tag_id = self._ensure_tag(tag)

        existing = self._tag_status(tag_id, format_id)
        if existing is not None and bool(existing.deprecated) == deprecated:
            return None
        alias, preferred_id, _ = self._existing_or_default(existing, tag_id)
        type_id = existing.type_id if existing is not None else self._unknown_type_id(format_id)
        deprecated_at = datetime.now(UTC) if deprecated else None
        if self._dry_run:
            return [f"TAG_STATUS.deprecated tag_id={tag_id} -> {deprecated}"]
        self._repo.update_tag_status(
            tag_id=tag_id,
            format_id=format_id,
            alias=alias,
            preferred_tag_id=preferred_id,
            type_id=type_id,
            deprecated=deprecated,
            deprecated_at=deprecated_at,
        )
        return [f"TAG_STATUS.deprecated tag_id={tag_id} -> {deprecated}"]

    def _apply_tag_name(self, patch: BaseCorrectionPatch) -> list[str] | None:
        source_tag = patch.target.get("source_tag") or patch.target.get("tag")
        proposed_tag = _require(_proposed_str(patch, "tag"), "proposed.tag")
        if not isinstance(source_tag, str) or not source_tag:
            raise _ApplyReject("tag_name_correction requires target.source_tag or target.tag")
        if self._resolve_tag_id(proposed_tag) is not None:
            return None
        if self._dry_run:
            return [f"TAGS +{proposed_tag!r}"]
        tag_id = self._repo.create_tag(source_tag, proposed_tag)
        return [f"TAGS +{proposed_tag!r} (tag_id={tag_id})"]

    # ------------------------------------------------------------------
    # reader / writer helpers
    # ------------------------------------------------------------------

    def _resolve_tag_id(self, tag: str) -> int | None:
        try:
            return self._reader.get_tag_id_by_name(tag, partial=False)
        except ValueError:
            return None

    def _ensure_tag(self, tag: str) -> int:
        tag_id = self._resolve_tag_id(tag)
        if tag_id is not None:
            return tag_id
        if self._dry_run:
            return -1
        return self._repo.create_tag(tag, tag)

    def _tag_status(self, tag_id: int, format_id: int) -> Any | None:
        if tag_id < 0:
            return None
        getter = getattr(self._reader, "get_tag_status", None)
        return getter(tag_id, format_id) if getter is not None else None

    def _translation_exists(self, tag_id: int, language: str, translation: str) -> bool:
        if tag_id < 0:
            return False
        getter = getattr(self._reader, "get_translations", None)
        if getter is None:
            return False
        for row in getter(tag_id):
            if (
                getattr(row, "language", None) == language
                and getattr(row, "translation", None) == translation
            ):
                return True
        return False

    def _resolve_or_create_format(self, format_name: str | None) -> int:
        if not format_name:
            raise _ApplyReject("format-dependent patch requires format_name")
        try:
            format_id = int(self._reader.get_format_id(format_name))
        except ValueError:
            format_id = 0
        if format_id > 0:
            return format_id
        if self._dry_run:
            return -1
        return self._repo.create_format_if_not_exists(format_name)

    def _resolve_or_create_type_id(self, format_id: int, type_name: str) -> int:
        getter = getattr(self._reader, "get_type_id_for_format", None)
        if getter is not None and format_id > 0:
            resolved = getter(type_name, format_id)
            if resolved is not None:
                return int(resolved)
        if self._dry_run:
            return -1
        type_name_id = self._repo.create_type_name_if_not_exists(type_name)
        candidate = self._next_type_id(format_id)
        return self._repo.create_type_format_mapping_if_not_exists(format_id, candidate, type_name_id)

    def _unknown_type_id(self, format_id: int) -> int:
        return self._resolve_or_create_type_id(format_id, "unknown")

    def _alias_type_id(self, existing: Any | None, preferred_id: int, format_id: int) -> int:
        if existing is not None:
            return int(existing.type_id)
        preferred_status = self._tag_status(preferred_id, format_id)
        if preferred_status is not None:
            return int(preferred_status.type_id)
        return self._unknown_type_id(format_id)

    def _next_type_id(self, format_id: int) -> int:
        getter = getattr(self._reader, "list_tag_statuses", None)
        # 既存 mapping を直接列挙する API が無いため、保守的に 0 から空き探索させる。
        # create_type_format_mapping_if_not_exists が衝突時に繰り上げる。
        if getter is None:
            return 0
        return 0

    @staticmethod
    def _existing_or_default(existing: Any | None, tag_id: int) -> tuple[bool, int, bool]:
        if existing is not None:
            return bool(existing.alias), int(existing.preferred_tag_id), bool(existing.deprecated)
        return False, tag_id, False

    def _row(
        self,
        patch: BaseCorrectionPatch,
        status: ApplyStatus,
        reason: str | None,
        db_changes: list[str] | None = None,
    ) -> BasePatchApplyRow:
        return BasePatchApplyRow(
            patch_id=patch.patch_id,
            patch_type=patch.patch_type,
            target_type=patch.target_type,
            target_tag=patch.target_tag,
            format_name=patch.format_name,
            field=patch.field,
            status=status,
            reason=reason,
            db_changes=db_changes or [],
        )


def apply_base_patch_file(
    paths: str | Path | list[str | Path],
    *,
    repository: Any,
    reader: Any,
    dry_run: bool = False,
    report: str | Path | None = None,
    report_format: ReportFormat | None = None,
) -> BasePatchApplyResult:
    """1 つ以上の base patch JSONL を読み込み、build source に適用する。"""
    if not isinstance(paths, list):
        paths = [paths]
    service = BasePatchApplyService(repository, reader, dry_run=dry_run)
    result = BasePatchApplyResult(dry_run=dry_run)
    for path in paths:
        for patch, parse_error in _iter_patches(Path(path)):
            if parse_error is not None:
                result.rows.append(BasePatchApplyRow(status="rejected", reason=parse_error))
                continue
            assert patch is not None
            result.rows.append(service.apply_patch(patch))
    if report is not None:
        write_apply_report(result, report, report_format=report_format)
    return result


def write_apply_report(
    result: BasePatchApplyResult,
    path: str | Path,
    *,
    report_format: ReportFormat | None = None,
) -> None:
    rows = [row.model_dump() for row in result.rows]
    write_report(Path(path), REPORT_COLUMNS, rows, report_format=report_format)


def _iter_patches(path: Path):
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                yield None, f"invalid JSON: {exc}"
                continue
            if not isinstance(data, dict):
                yield None, "patch must be a JSON object"
                continue
            try:
                yield BaseCorrectionPatch.model_validate(data), None
            except ValidationError as exc:
                yield None, f"missing_required_field: {exc}"


def _require(value: Any, field: str) -> Any:
    if value is None:
        raise _ApplyReject(f"{field} is required")
    return value


def _proposed_str(patch: BaseCorrectionPatch, key: str) -> str | None:
    value = patch.proposed.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _field_language(field: str | None) -> str | None:
    if field and field.startswith("translation."):
        return field.split(".", 1)[1] or None
    return None


def _validation_reason(item: PatchValidationItemResult) -> str:
    return "; ".join(issue.code for issue in item.errors) or "validation failed"
