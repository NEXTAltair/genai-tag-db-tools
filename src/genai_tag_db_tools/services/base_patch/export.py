"""Export base DB correction proposals from approved refinement feedback (issue #61).

This module converts approved, overlay/id-based :class:`DbFeedbackProposal` objects into
name-based base correction patches (the same envelope the builder consumes in #60) and
writes them as JSONL. It never applies anything to the base DB.

Tag names are resolved from name hints carried in the proposal (``current`` / ``proposed``
/ ``evidence``) and, when an optional read-only ``reader`` is supplied, from the base DB
by ``tag_id``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from genai_tag_db_tools.models import ApprovedDbFeedback, DbFeedbackProposal, ProposalTarget
from genai_tag_db_tools.services.base_patch.models import (
    SCHEMA_VERSION,
    BaseCorrectionPatch,
    compute_patch_id,
)
from genai_tag_db_tools.services.base_patch.report import ReportFormat, write_report
from genai_tag_db_tools.services.base_patch.validate import validate_base_patch

# tools が base patch に export する proposal kind。usage_correction は base patch
# 対象外 (#60 の対応 patch 種類に含まれない)。
EXPORTABLE_KINDS: frozenset[str] = frozenset(
    {
        "alias_addition",
        "preferred_tag_correction",
        "translation_correction",
        "type_correction",
        "status_correction",
        "tag_name_correction",
    }
)

# review-only として export しない proposal kind。
REVIEW_ONLY_KINDS: frozenset[str] = frozenset({"format_relation_review"})

_TARGET_TYPE_BY_PROPOSAL_KIND: dict[str, str] = {
    "alias_addition": "alias",
    "preferred_tag_correction": "alias",
    "translation_correction": "translation",
    "type_correction": "tag_type",
    "status_correction": "tag_status",
    "tag_name_correction": "tag_name",
}

REPORT_COLUMNS = (
    "patch_id",
    "patch_type",
    "target_type",
    "target_tag",
    "format_name",
    "field",
    "status",
    "reason",
)

ExportStatus = Literal[
    "exported",
    "skipped_user_scope",
    "skipped_review_only",
    "skipped_unsupported_type",
    "validation_failed",
]


class BasePatchExportRow(BaseModel):
    """export report の 1 行。"""

    patch_id: str | None = None
    patch_type: str | None = None
    target_type: str | None = None
    target_tag: str | None = None
    format_name: str | None = None
    field: str | None = None
    status: ExportStatus
    reason: str | None = None


class BasePatchExportResult(BaseModel):
    """export 結果のコンテナ。"""

    patches: list[BaseCorrectionPatch] = Field(default_factory=list)
    rows: list[BasePatchExportRow] = Field(default_factory=list)

    @property
    def exported_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "exported")

    @property
    def skipped_count(self) -> int:
        return sum(1 for row in self.rows if row.status.startswith("skipped_"))

    @property
    def failed_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "validation_failed")


class _ExportError(ValueError):
    """name 解決などで export 不能になったときに投げる内部例外。"""


def export_base_patches(
    feedbacks: Iterable[ApprovedDbFeedback],
    *,
    reader: Any | None = None,
    validate: bool = False,
    validate_repo: Any | None = None,
) -> BasePatchExportResult:
    """approved feedback の列から base correction patch を生成する。"""
    result = BasePatchExportResult()
    repo = validate_repo if validate_repo is not None else reader
    for feedback in feedbacks:
        _export_one(feedback, reader=reader, validate=validate, repo=repo, result=result)
    return result


def export_base_patch_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    reader: Any | None = None,
    validate: bool = False,
    validate_repo: Any | None = None,
    report: str | Path | None = None,
    report_format: ReportFormat | None = None,
) -> BasePatchExportResult:
    """approved-feedback JSONL を読み、base patch JSONL を書き出す。"""
    input_path = Path(input_path)
    result = BasePatchExportResult()
    repo = validate_repo if validate_repo is not None else reader

    with input_path.open(encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            feedback = _load_feedback(stripped, result)
            if feedback is None:
                continue
            _export_one(feedback, reader=reader, validate=validate, repo=repo, result=result)

    _write_patches(result.patches, Path(output_path))
    if report is not None:
        write_export_report(result, report, report_format=report_format)
    return result


def write_export_report(
    result: BasePatchExportResult,
    path: str | Path,
    *,
    report_format: ReportFormat | None = None,
) -> None:
    rows = [row.model_dump() for row in result.rows]
    write_report(Path(path), REPORT_COLUMNS, rows, report_format=report_format)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _load_feedback(stripped: str, result: BasePatchExportResult) -> ApprovedDbFeedback | None:
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        result.rows.append(BasePatchExportRow(status="validation_failed", reason="invalid JSON"))
        return None
    if not isinstance(data, dict):
        result.rows.append(
            BasePatchExportRow(status="validation_failed", reason="feedback must be an object")
        )
        return None
    if data.get("approved") is not True:
        result.rows.append(
            BasePatchExportRow(status="skipped_review_only", reason="feedback is not approved")
        )
        return None
    try:
        return ApprovedDbFeedback.model_validate(data)
    except ValidationError as exc:
        result.rows.append(
            BasePatchExportRow(status="validation_failed", reason=f"invalid feedback: {exc}")
        )
        return None


def _export_one(
    feedback: ApprovedDbFeedback,
    *,
    reader: Any | None,
    validate: bool,
    repo: Any | None,
    result: BasePatchExportResult,
) -> None:
    proposal = feedback.proposal

    skip = _skip_status(proposal)
    if skip is not None:
        status, reason = skip
        result.rows.append(
            BasePatchExportRow(
                patch_type=proposal.kind,
                target_type=proposal.target.kind,
                format_name=proposal.target.format_name,
                status=status,
                reason=reason,
            )
        )
        return

    try:
        patch = _build_patch(feedback, reader=reader)
    except _ExportError as exc:
        result.rows.append(
            BasePatchExportRow(
                patch_type=proposal.kind,
                target_type=proposal.target.kind,
                format_name=proposal.target.format_name,
                status="validation_failed",
                reason=str(exc),
            )
        )
        return

    if validate:
        item = validate_base_patch(patch, repo=repo)
        if item.status == "invalid":
            result.rows.append(
                BasePatchExportRow(
                    patch_id=patch.patch_id,
                    patch_type=patch.patch_type,
                    target_type=patch.target_type,
                    target_tag=patch.target_tag,
                    format_name=patch.format_name,
                    field=patch.field,
                    status="validation_failed",
                    reason="; ".join(issue.code for issue in item.errors),
                )
            )
            return
        patch.validated = True
        patch.validated_at = _now_iso()

    result.patches.append(patch)
    result.rows.append(
        BasePatchExportRow(
            patch_id=patch.patch_id,
            patch_type=patch.patch_type,
            target_type=patch.target_type,
            target_tag=patch.target_tag,
            format_name=patch.format_name,
            field=patch.field,
            status="exported",
            reason=None,
        )
    )


def _skip_status(proposal: DbFeedbackProposal) -> tuple[ExportStatus, str] | None:
    if proposal.kind in REVIEW_ONLY_KINDS:
        return "skipped_review_only", f"{proposal.kind} is review-only"
    if proposal.kind not in EXPORTABLE_KINDS:
        return "skipped_unsupported_type", f"{proposal.kind} is not a base patch type"
    if proposal.target.target_scope != "base":
        return "skipped_user_scope", f"target_scope={proposal.target.target_scope!r} is not base"
    return None


def _build_patch(feedback: ApprovedDbFeedback, *, reader: Any | None) -> BaseCorrectionPatch:
    proposal = feedback.proposal
    target_type = _TARGET_TYPE_BY_PROPOSAL_KIND[proposal.kind]
    target, proposed = _build_target_and_proposed(proposal, target_type, reader)

    patch = BaseCorrectionPatch(
        schema_version=SCHEMA_VERSION,
        scope="base",
        patch_type=proposal.kind,
        target=target,
        proposed=proposed,
        current=proposal.current,
        approved=True,
        approved_by=feedback.approved_by,
        approved_at=_to_iso(feedback.approved_at),
        # validated は export 直後は付けない (#61)。--validate 時のみ True を立てる。
        source_proposal={"proposal_type": proposal.kind},
        reason_codes=list(proposal.reason_codes),
        evidence=_merge_evidence(proposal.evidence),
        note=feedback.approval_note,
    )
    patch.patch_id = compute_patch_id(patch)
    return patch


def _build_target_and_proposed(
    proposal: DbFeedbackProposal,
    target_type: str,
    reader: Any | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target: dict[str, Any] = {"target_type": target_type}
    proposed: dict[str, Any] = {}

    if proposal.kind in ("alias_addition", "preferred_tag_correction"):
        tag = _resolve_tag_name(proposal, reader)
        target.update({"tag": tag, "format_name": _require_format(proposal.target)})
        preferred = _resolve_preferred_name(proposal, reader)
        proposed["preferred_tag"] = preferred
        if proposal.kind == "alias_addition":
            proposed["alias"] = True
    elif proposal.kind == "translation_correction":
        tag = _resolve_tag_name(proposal, reader)
        language = _translation_language(proposal)
        target.update({"tag": tag, "field": f"translation.{language}"})
        proposed["translation"] = _require_proposed_str(proposal, "translation")
        proposed["language"] = language
    elif proposal.kind == "type_correction":
        tag = _resolve_tag_name(proposal, reader)
        target.update({"tag": tag, "format_name": _require_format(proposal.target)})
        proposed["type_name"] = _require_proposed_str(proposal, "type_name")
    elif proposal.kind == "status_correction":
        tag = _resolve_tag_name(proposal, reader)
        target.update(
            {
                "tag": tag,
                "format_name": _require_format(proposal.target),
                "field": "TAG_STATUS.deprecated",
            }
        )
        proposed["deprecated"] = _require_proposed_bool(proposal, "deprecated")
    elif proposal.kind == "tag_name_correction":
        source_tag = _source_tag(proposal)
        target.update({"source_tag": source_tag})
        proposed["tag"] = _require_proposed_str(proposal, "tag")
    else:  # pragma: no cover - guarded by EXPORTABLE_KINDS
        raise _ExportError(f"unsupported proposal kind {proposal.kind!r}")

    return target, proposed


def _resolve_tag_name(proposal: DbFeedbackProposal, reader: Any | None) -> str:
    for source in (proposal.proposed, proposal.current):
        name = _name_from_mapping(source, ("tag", "alias_tag", "source_tag"))
        if name is not None:
            return name
    name = _name_from_evidence(proposal.evidence, ("tag", "alias_tag", "source_tag"))
    if name is not None:
        return name
    resolved = _name_by_tag_id(reader, proposal.target.target_tag_id)
    if resolved is not None:
        return resolved
    raise _ExportError("could not resolve target tag name")


def _resolve_preferred_name(proposal: DbFeedbackProposal, reader: Any | None) -> str:
    name = _name_from_mapping(proposal.proposed, ("preferred_tag",))
    if name is not None:
        return name
    name = _name_from_evidence(proposal.evidence, ("preferred_tag", "candidate"))
    if name is not None:
        return name
    resolved = _name_by_tag_id(reader, proposal.target.preferred_tag_id)
    if resolved is not None:
        return resolved
    raise _ExportError("could not resolve preferred tag name")


def _source_tag(proposal: DbFeedbackProposal) -> str:
    name = _name_from_mapping(proposal.current, ("source_tag", "tag"))
    if name is not None:
        return name
    name = _name_from_mapping(proposal.proposed, ("source_tag",))
    if name is not None:
        return name
    name = _name_from_evidence(proposal.evidence, ("source_tag",))
    if name is not None:
        return name
    raise _ExportError("tag_name_correction requires a source_tag")


def _translation_language(proposal: DbFeedbackProposal) -> str:
    if proposal.target.language:
        return proposal.target.language
    if proposal.proposed and isinstance(proposal.proposed.get("language"), str):
        return str(proposal.proposed["language"])
    if proposal.current and isinstance(proposal.current.get("language"), str):
        return str(proposal.current["language"])
    raise _ExportError("translation_correction requires a language")


def _require_format(target: ProposalTarget) -> str:
    if not target.format_name:
        raise _ExportError("format-dependent proposal requires format_name")
    return target.format_name


def _require_proposed_str(proposal: DbFeedbackProposal, key: str) -> str:
    if proposal.proposed is None:
        raise _ExportError(f"{proposal.kind} requires proposed values")
    value = proposal.proposed.get(key)
    if isinstance(value, str) and value.strip():
        return value
    raise _ExportError(f"{proposal.kind} requires non-empty proposed.{key}")


def _require_proposed_bool(proposal: DbFeedbackProposal, key: str) -> bool:
    if proposal.proposed is None:
        raise _ExportError(f"{proposal.kind} requires proposed values")
    value = proposal.proposed.get(key)
    if isinstance(value, bool):
        return value
    raise _ExportError(f"{proposal.kind} requires boolean proposed.{key}")


def _name_from_mapping(mapping: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    if not mapping:
        return None
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _name_from_evidence(evidence: list[dict[str, Any]] | None, keys: tuple[str, ...]) -> str | None:
    for entry in evidence or []:
        name = _name_from_mapping(entry, keys)
        if name is not None:
            return name
    return None


def _name_by_tag_id(reader: Any | None, tag_id: int | None) -> str | None:
    if reader is None or tag_id is None:
        return None
    getter = getattr(reader, "get_tag_by_id", None)
    if getter is None:
        return None
    tag = getter(tag_id)
    name = getattr(tag, "tag", None) if tag is not None else None
    return name if isinstance(name, str) and name else None


def _merge_evidence(evidence: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not evidence:
        return None
    merged: dict[str, Any] = {}
    for entry in evidence:
        if isinstance(entry, dict):
            merged.update(entry)
    return merged or None


def _write_patches(patches: list[BaseCorrectionPatch], output_path: Path) -> None:
    if output_path.parent and not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for patch in patches:
            payload = patch.model_dump(mode="json", exclude_none=True)
            fh.write(json.dumps(payload, ensure_ascii=False))
            fh.write("\n")


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
