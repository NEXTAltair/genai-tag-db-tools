from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

from genai_tag_db_tools.db.schema import LocalFeedbackApplication
from genai_tag_db_tools.db.user_tag_repository import UserTagRepository
from genai_tag_db_tools.models import (
    ApprovedDbFeedback,
    DbFeedbackProposal,
    LocalFeedbackApplicationRecord,
    LocalFeedbackApplyResult,
    ProposalTarget,
    ProposalValue,
)


class LocalFeedbackApplyService:
    """承認済み DB feedback proposal を user-local overlay DB に反映する。"""

    _SUPPORTED_KINDS: ClassVar[set[str]] = {
        "alias_addition",
        "preferred_tag_correction",
        "translation_correction",
        "usage_correction",
        "type_correction",
        "status_correction",
        "tag_name_correction",
    }

    def __init__(self, user_repository: UserTagRepository, reader: Any | None = None) -> None:
        self._user_repository = user_repository
        self._reader = reader

    def apply(self, feedback: ApprovedDbFeedback, *, dry_run: bool = False) -> LocalFeedbackApplyResult:
        proposal = feedback.proposal
        proposal_hash = proposal_hash_for(proposal)
        proposal_json = _json_dumps(proposal.model_dump(mode="json"))

        self._validate_feedback(feedback)
        if proposal.kind not in self._SUPPORTED_KINDS:
            raise ValueError(f"local apply unsupported proposal kind: {proposal.kind}")
        if proposal.kind == "format_relation_review":
            raise ValueError("format_relation_review is review-only and cannot be applied")
        self._validate_proposal(proposal)

        if self._user_repository.has_applied_feedback(proposal_hash):
            return LocalFeedbackApplyResult(
                ok=True,
                status="skipped",
                dry_run=dry_run,
                proposal_hash=proposal_hash,
                proposal_kind=proposal.kind,
                message="proposal is already applied",
            )

        before = self._snapshot_before(proposal)
        changes = self._planned_changes(proposal)
        after = {"changes": changes}

        if dry_run:
            self._prepare_proposal(proposal)
        else:
            self._apply_proposal(proposal)

        application = self._record_application(
            feedback,
            proposal_hash=proposal_hash,
            proposal_json=proposal_json,
            status="dry_run" if dry_run else "applied",
            dry_run=dry_run,
            before=before,
            after=after,
            error_message=None,
        )
        return LocalFeedbackApplyResult(
            ok=True,
            status="dry_run" if dry_run else "applied",
            dry_run=dry_run,
            proposal_hash=proposal_hash,
            proposal_kind=proposal.kind,
            message="dry-run complete" if dry_run else "feedback applied",
            changes=changes,
            application=application,
        )

    def list_applications(self) -> list[LocalFeedbackApplicationRecord]:
        return [_application_record(row) for row in self._user_repository.list_feedback_applications()]

    def _validate_feedback(self, feedback: ApprovedDbFeedback) -> None:
        if not feedback.approved:
            raise ValueError("feedback must be approved before local apply")
        if not feedback.approved_by.strip():
            raise ValueError("approved_by is required")
        if feedback.approved_at is None:
            raise ValueError("approved_at is required")

    def _apply_proposal(self, proposal: DbFeedbackProposal) -> None:
        match proposal.kind:
            case "translation_correction":
                self._apply_translation(proposal)
            case "status_correction":
                self._apply_status(proposal)
            case "type_correction":
                self._apply_type(proposal)
            case "usage_correction":
                self._apply_usage(proposal)
            case "alias_addition":
                self._apply_alias_addition(proposal)
            case "preferred_tag_correction":
                self._apply_preferred_correction(proposal)
            case "tag_name_correction":
                self._apply_tag_name(proposal)
            case _:
                raise ValueError(f"local apply unsupported proposal kind: {proposal.kind}")

    def _prepare_proposal(self, proposal: DbFeedbackProposal) -> None:
        match proposal.kind:
            case "translation_correction":
                self._prepare_translation(proposal)
            case "status_correction":
                self._prepare_status(proposal, create=False)
            case "type_correction":
                self._prepare_type(proposal, create=False)
            case "usage_correction":
                self._prepare_usage(proposal, create=False)
            case "alias_addition":
                self._prepare_alias_addition(proposal, create=False)
            case "preferred_tag_correction":
                self._prepare_preferred_correction(proposal, create=False)
            case "tag_name_correction":
                self._prepare_tag_name(proposal)
            case _:
                raise ValueError(f"local apply unsupported proposal kind: {proposal.kind}")

    def _apply_translation(self, proposal: DbFeedbackProposal) -> None:
        target, language, translation = self._prepare_translation(proposal)
        self._user_repository.write_translation_patch(
            target_scope=target.target_scope,
            target_tag_id=target.target_tag_id,
            language=language,
            translation=translation,
        )

    def _prepare_translation(self, proposal: DbFeedbackProposal) -> tuple[ProposalTarget, str, str]:
        target = _require_target_tag(proposal.target)
        proposed = _require_proposed(proposal)
        language = _string_value(proposed, "language", fallback=proposal.target.language)
        translation = _string_value(proposed, "translation")
        current_translation = _optional_mapping_string(proposal.current, "translation")
        if current_translation is not None and current_translation != translation:
            raise ValueError("translation_correction cannot replace existing translation with current overlay schema")
        return target, language, translation

    def _apply_status(self, proposal: DbFeedbackProposal) -> None:
        target, format_id, status, proposed = self._prepare_status(proposal, create=True)
        deprecated = _bool_value(proposed, "deprecated")
        self._user_repository.write_patch(
            target_scope=target.target_scope,
            target_tag_id=target.target_tag_id,
            format_id=format_id,
            type_id=status["type_id"],
            alias=status["alias"],
            preferred_scope=status["preferred_scope"],
            preferred_tag_id=status["preferred_tag_id"],
            deprecated=deprecated,
        )

    def _prepare_status(
        self, proposal: DbFeedbackProposal, *, create: bool
    ) -> tuple[ProposalTarget, int, dict[str, Any], Mapping[str, ProposalValue]]:
        target = _require_target_tag(proposal.target)
        proposed = _require_proposed(proposal)
        format_id = self._format_id(target, create=create)
        existing = self._user_repository.get_status_patch(target.target_scope, target.target_tag_id, format_id)
        status = self._status_values(target, format_id, existing, proposal.current)
        return target, format_id, status, proposed

    def _apply_type(self, proposal: DbFeedbackProposal) -> None:
        target, format_id, type_id, status = self._prepare_type(proposal, create=True)
        self._user_repository.write_patch(
            target_scope=target.target_scope,
            target_tag_id=target.target_tag_id,
            format_id=format_id,
            type_id=type_id,
            alias=status["alias"],
            preferred_scope=status["preferred_scope"],
            preferred_tag_id=status["preferred_tag_id"],
            deprecated=status["deprecated"],
        )

    def _prepare_type(self, proposal: DbFeedbackProposal, *, create: bool) -> tuple[ProposalTarget, int, int, dict[str, Any]]:
        target = _require_target_tag(proposal.target)
        proposed = _require_proposed(proposal)
        format_id = self._format_id(target, create=create)
        type_name = _required_type_name_or_id(proposed)
        proposed_type_id = _optional_int_value(proposed, "type_id")
        type_id = self._resolve_type_id(target, format_id, type_name, proposed_type_id, create=create)
        existing = self._user_repository.get_status_patch(target.target_scope, target.target_tag_id, format_id)
        status = self._status_values(target, format_id, existing, proposal.current)
        return target, format_id, type_id, status

    def _apply_usage(self, proposal: DbFeedbackProposal) -> None:
        target, format_id, count = self._prepare_usage(proposal, create=True)
        self._user_repository.write_usage_patch(
            target_scope=target.target_scope,
            target_tag_id=target.target_tag_id,
            format_id=format_id,
            count=count,
        )

    def _prepare_usage(self, proposal: DbFeedbackProposal, *, create: bool) -> tuple[ProposalTarget, int, int]:
        target = _require_target_tag(proposal.target)
        proposed = _require_proposed(proposal)
        count = _non_negative_int_value(proposed, "count")
        return target, self._format_id(target, create=create), count

    def _apply_alias_addition(self, proposal: DbFeedbackProposal) -> None:
        target, format_id, type_id, proposed = self._prepare_alias_addition(proposal, create=True)
        alias_tag_id = target.target_tag_id
        if alias_tag_id is None:
            alias_tag = _string_value(proposed, "alias_tag", fallback=_optional_string_value(proposed, "tag"))
            source_tag = _optional_string_value(proposed, "source_tag") or alias_tag
            alias_tag_id = self._user_repository.create_user_tag(source_tag, alias_tag)
            target_scope = "user"
        else:
            target_scope = target.target_scope

        self._user_repository.write_patch(
            target_scope=target_scope,
            target_tag_id=alias_tag_id,
            format_id=format_id,
            type_id=type_id,
            alias=True,
            preferred_scope=target.preferred_scope,
            preferred_tag_id=target.preferred_tag_id,
            deprecated=_optional_bool_value(proposed, "deprecated") or False,
        )

    def _prepare_alias_addition(
        self, proposal: DbFeedbackProposal, *, create: bool
    ) -> tuple[ProposalTarget, int, int, Mapping[str, ProposalValue]]:
        target = proposal.target
        proposed = _require_proposed(proposal)
        if target.preferred_scope is None or target.preferred_tag_id is None:
            raise ValueError("alias_addition requires preferred_scope and preferred_tag_id")
        format_id = self._format_id(target, create=create)
        type_name = _optional_type_name(proposed)
        proposed_type_id = _optional_int_value(proposed, "type_id")
        if type_name is None and proposed_type_id is None:
            proposed_type_id = self._preferred_type_id(target, format_id)
            if proposed_type_id is None:
                raise ValueError("alias_addition requires type_name, type_id, or resolvable preferred tag status")
        type_id = self._resolve_type_id(
            target,
            format_id,
            type_name,
            proposed_type_id,
            create=create,
        )
        return target, format_id, type_id, proposed

    def _apply_preferred_correction(self, proposal: DbFeedbackProposal) -> None:
        target, format_id, status = self._prepare_preferred_correction(proposal, create=True)
        self._user_repository.write_patch(
            target_scope=target.target_scope,
            target_tag_id=target.target_tag_id,
            format_id=format_id,
            type_id=status["type_id"],
            alias=True,
            preferred_scope=target.preferred_scope,
            preferred_tag_id=target.preferred_tag_id,
            deprecated=status["deprecated"],
        )

    def _prepare_preferred_correction(
        self, proposal: DbFeedbackProposal, *, create: bool
    ) -> tuple[ProposalTarget, int, dict[str, Any]]:
        target = _require_target_tag(proposal.target)
        if target.preferred_scope is None or target.preferred_tag_id is None:
            raise ValueError("preferred_tag_correction requires preferred_scope and preferred_tag_id")
        format_id = self._format_id(target, create=create)
        existing = self._user_repository.get_status_patch(target.target_scope, target.target_tag_id, format_id)
        status = self._status_values(target, format_id, existing, proposal.current)
        return target, format_id, status

    def _apply_tag_name(self, proposal: DbFeedbackProposal) -> None:
        tag, source_tag = self._prepare_tag_name(proposal)
        self._user_repository.create_user_tag(source_tag, tag)

    def _prepare_tag_name(self, proposal: DbFeedbackProposal) -> tuple[str, str]:
        if proposal.target.target_tag_id is not None:
            raise ValueError("tag_name_correction can only create a new user tag locally")
        proposed = _require_proposed(proposal)
        tag = _string_value(proposed, "tag")
        source_tag = (
            _optional_string_value(proposed, "source_tag")
            or _optional_mapping_string(proposal.current, "source_tag")
            or tag
        )
        return tag, source_tag

    def _format_id(self, target: ProposalTarget, *, create: bool) -> int:
        if target.format_name is None:
            raise ValueError("format-dependent local apply requires format_name")
        base_format_id = self._reader_format_id(target.format_name)
        if base_format_id is not None:
            if create:
                return self._user_repository.get_or_create_format_id(target.format_name, base_format_id)
            return base_format_id

        existing_user_format_id = self._user_repository.get_format_id(target.format_name)
        if existing_user_format_id is not None:
            return existing_user_format_id

        if target.target_scope == "base" and target.format_name != "unknown":
            raise ValueError("base-scope format-dependent local apply requires reader-resolved format_id")
        if self._reader is None and target.format_name != "unknown":
            raise ValueError("format-dependent local apply requires reader or existing local format")
        if not create:
            return 0
        return self._user_repository.get_or_create_format_id(target.format_name)

    def _reader_format_id(self, format_name: str) -> int | None:
        if self._reader is None:
            return None
        try:
            format_id = int(self._reader.get_format_id(format_name))
        except ValueError:
            return None
        return format_id if format_id > 0 else None

    def _reader_type_id(self, type_name: str, format_id: int) -> int | None:
        if self._reader is None or not hasattr(self._reader, "get_type_id_for_format"):
            return None
        type_id = self._reader.get_type_id_for_format(type_name, format_id)
        return int(type_id) if type_id is not None else None

    def _reader_status(self, target: ProposalTarget, format_id: int) -> Any | None:
        if self._reader is None or target.target_tag_id is None:
            return None
        if not hasattr(self._reader, "get_tag_status"):
            return None
        return self._reader.get_tag_status(target.target_tag_id, format_id)

    def _preferred_type_id(self, target: ProposalTarget, format_id: int) -> int | None:
        if target.preferred_scope is None or target.preferred_tag_id is None:
            return None
        existing = self._user_repository.get_status_patch(target.preferred_scope, target.preferred_tag_id, format_id)
        if existing is not None:
            return int(existing.type_id)
        if self._reader is None or not hasattr(self._reader, "get_tag_status"):
            return None
        status = self._reader.get_tag_status(target.preferred_tag_id, format_id)
        return int(status.type_id) if status is not None else None

    def _resolve_type_id(
        self,
        target: ProposalTarget,
        format_id: int,
        type_name: str | None,
        proposed_type_id: int | None,
        *,
        create: bool,
    ) -> int:
        if type_name is None:
            if proposed_type_id is None:
                raise ValueError("type_name or type_id is required")
            return proposed_type_id

        reader_type_id = self._reader_type_id(type_name, format_id)
        if proposed_type_id is not None and reader_type_id is not None and proposed_type_id != reader_type_id:
            raise ValueError(
                f"proposed type_id={proposed_type_id} does not match reader type_id={reader_type_id} "
                f"for {target.format_name}/{type_name}"
            )
        if reader_type_id is not None:
            return reader_type_id
        if target.target_scope == "base" and target.format_name != "unknown" and proposed_type_id is None:
            raise ValueError(f"base-scope type correction requires resolvable type_id for {type_name!r}")
        if not create:
            existing_type_id = self._user_repository.get_type_id(format_id, type_name)
            if existing_type_id is not None:
                return existing_type_id
            if proposed_type_id is not None:
                owner_name = self._user_repository.get_type_name_for_type_id(format_id, proposed_type_id)
                if owner_name is not None and owner_name != type_name:
                    raise ValueError(
                        f"type_id={proposed_type_id} for format_id={format_id} already belongs to "
                        f"type_name={owner_name!r}"
                    )
                return proposed_type_id
            if target.target_scope == "base" and target.format_name != "unknown":
                raise ValueError(f"type correction requires resolvable type_id for {type_name!r}")
            return 0
        if proposed_type_id is not None:
            owner_name = self._user_repository.get_type_name_for_type_id(format_id, proposed_type_id)
            if owner_name is not None and owner_name != type_name:
                raise ValueError(
                    f"type_id={proposed_type_id} for format_id={format_id} already belongs to "
                    f"type_name={owner_name!r}"
                )
        return self._user_repository.get_or_create_type_id(format_id, type_name, proposed_type_id)

    def _status_values(
        self,
        target: ProposalTarget,
        format_id: int,
        existing: Any | None,
        current: Mapping[str, ProposalValue] | None,
    ) -> dict[str, Any]:
        if existing is not None:
            return {
                "type_id": existing.type_id,
                "alias": existing.alias,
                "preferred_scope": existing.preferred_scope,
                "preferred_tag_id": existing.preferred_tag_id,
                "deprecated": existing.deprecated,
            }

        reader_status = self._reader_status(target, format_id)
        if reader_status is not None:
            preferred_tag_id = int(reader_status.preferred_tag_id)
            return {
                "type_id": int(reader_status.type_id),
                "alias": bool(reader_status.alias),
                "preferred_scope": "user" if preferred_tag_id >= 1_000_000_000 else "base",
                "preferred_tag_id": preferred_tag_id,
                "deprecated": bool(reader_status.deprecated),
            }

        current_values = current or {}
        return {
            "type_id": _optional_int_value(current_values, "type_id") or 0,
            "alias": _optional_bool_value(current_values, "alias") or False,
            "preferred_scope": _optional_string_value(current_values, "preferred_scope") or target.target_scope,
            "preferred_tag_id": _optional_int_value(current_values, "preferred_tag_id") or target.target_tag_id,
            "deprecated": _optional_bool_value(current_values, "deprecated") or False,
        }

    def _validate_proposal(self, proposal: DbFeedbackProposal) -> None:
        match proposal.kind:
            case "translation_correction":
                _require_target_tag(proposal.target)
                proposed = _require_proposed(proposal)
                _string_value(proposed, "language", fallback=proposal.target.language)
                _string_value(proposed, "translation")
            case "status_correction":
                target = _require_target_tag(proposal.target)
                _bool_value(_require_proposed(proposal), "deprecated")
                _require_format_name(target)
            case "type_correction":
                target = _require_target_tag(proposal.target)
                _required_type_name_or_id(_require_proposed(proposal))
                _require_format_name(target)
            case "usage_correction":
                target = _require_target_tag(proposal.target)
                _non_negative_int_value(_require_proposed(proposal), "count")
                _require_format_name(target)
            case "alias_addition":
                target = proposal.target
                proposed = _require_proposed(proposal)
                if target.preferred_scope is None or target.preferred_tag_id is None:
                    raise ValueError("alias_addition requires preferred_scope and preferred_tag_id")
                _require_format_name(target)
                if target.target_tag_id is None:
                    _string_value(proposed, "alias_tag", fallback=_optional_string_value(proposed, "tag"))
            case "preferred_tag_correction":
                target = _require_target_tag(proposal.target)
                if target.preferred_scope is None or target.preferred_tag_id is None:
                    raise ValueError("preferred_tag_correction requires preferred_scope and preferred_tag_id")
                _require_format_name(target)
            case "tag_name_correction":
                if proposal.target.target_tag_id is not None:
                    raise ValueError("tag_name_correction can only create a new user tag locally")
                _string_value(_require_proposed(proposal), "tag")
            case _:
                raise ValueError(f"local apply unsupported proposal kind: {proposal.kind}")

    def _snapshot_before(self, proposal: DbFeedbackProposal) -> dict[str, ProposalValue]:
        return {
            "kind": proposal.kind,
            "target_scope": proposal.target.target_scope,
            "target_tag_id": proposal.target.target_tag_id,
            "format_name": proposal.target.format_name,
        }

    def _planned_changes(self, proposal: DbFeedbackProposal) -> list[dict[str, ProposalValue]]:
        return [
            {
                "proposal_kind": proposal.kind,
                "target_kind": proposal.target.kind,
                "target_scope": proposal.target.target_scope,
                "target_tag_id": proposal.target.target_tag_id,
                "format_name": proposal.target.format_name,
            }
        ]

    def _record_application(
        self,
        feedback: ApprovedDbFeedback,
        *,
        proposal_hash: str,
        proposal_json: str,
        status: str,
        dry_run: bool,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        error_message: str | None,
    ) -> LocalFeedbackApplicationRecord:
        proposal = feedback.proposal
        row = self._user_repository.record_feedback_application(
            proposal_hash=proposal_hash,
            proposal_kind=proposal.kind,
            target_kind=proposal.target.kind,
            target_scope=proposal.target.target_scope,
            target_tag_id=proposal.target.target_tag_id,
            format_name=proposal.target.format_name,
            field=_target_field(proposal),
            approved_by=feedback.approved_by,
            approved_at=feedback.approved_at,
            status=status,
            dry_run=dry_run,
            proposal_json=proposal_json,
            before_json=_json_dumps(before) if before is not None else None,
            after_json=_json_dumps(after) if after is not None else None,
            error_message=error_message,
        )
        return _application_record(row)


def apply_approved_feedback(
    feedback: ApprovedDbFeedback,
    *,
    user_repository: UserTagRepository,
    reader: Any | None = None,
    dry_run: bool = False,
) -> LocalFeedbackApplyResult:
    return LocalFeedbackApplyService(user_repository, reader=reader).apply(feedback, dry_run=dry_run)


def list_local_feedback_applications(
    *,
    user_repository: UserTagRepository,
) -> list[LocalFeedbackApplicationRecord]:
    return LocalFeedbackApplyService(user_repository).list_applications()


def proposal_hash_for(proposal: DbFeedbackProposal) -> str:
    return hashlib.sha256(_json_dumps(proposal.model_dump(mode="json")).encode("utf-8")).hexdigest()


def _application_record(row: LocalFeedbackApplication) -> LocalFeedbackApplicationRecord:
    return LocalFeedbackApplicationRecord(
        application_id=row.application_id,
        proposal_hash=row.proposal_hash,
        proposal_kind=row.proposal_kind,
        target_kind=row.target_kind,
        target_scope=row.target_scope,
        target_tag_id=row.target_tag_id,
        format_name=row.format_name,
        field=row.field,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        applied_at=row.applied_at,
        status=row.status,
        dry_run=row.dry_run,
        proposal_json=row.proposal_json,
        before_json=row.before_json,
        after_json=row.after_json,
        error_message=row.error_message,
    )


def _require_target_tag(target: ProposalTarget) -> ProposalTarget:
    if target.target_tag_id is None:
        raise ValueError(f"{target.kind} proposal requires target_tag_id")
    return target


def _require_format_name(target: ProposalTarget) -> str:
    if target.format_name is None:
        raise ValueError("format-dependent local apply requires format_name")
    return target.format_name


def _require_proposed(proposal: DbFeedbackProposal) -> Mapping[str, ProposalValue]:
    if proposal.proposed is None:
        raise ValueError(f"{proposal.kind} requires proposed values")
    return proposal.proposed


def _target_field(proposal: DbFeedbackProposal) -> str | None:
    if proposal.target.language is not None:
        return f"translation.{proposal.target.language}"
    return _optional_mapping_string(proposal.current, "field") or _optional_mapping_string(proposal.proposed, "field")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _string_value(
    data: Mapping[str, ProposalValue],
    key: str,
    *,
    fallback: str | None = None,
) -> str:
    value = data.get(key)
    if isinstance(value, str) and value:
        return value
    if fallback:
        return fallback
    raise ValueError(f"{key} is required")


def _optional_string_value(data: Mapping[str, ProposalValue], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def _optional_mapping_string(data: Mapping[str, ProposalValue] | None, key: str) -> str | None:
    if data is None:
        return None
    return _optional_string_value(data, key)


def _int_value(data: Mapping[str, ProposalValue], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if isinstance(value, int):
        return value
    raise ValueError(f"{key} is required")


def _non_negative_int_value(data: Mapping[str, ProposalValue], key: str) -> int:
    value = _int_value(data, key)
    if value < 0:
        raise ValueError(f"{key} must be greater than or equal to 0")
    return value


def _optional_int_value(data: Mapping[str, ProposalValue], key: str) -> int | None:
    value = data.get(key)
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _bool_value(data: Mapping[str, ProposalValue], key: str) -> bool:
    value = data.get(key)
    if isinstance(value, bool):
        return value
    raise ValueError(f"{key} is required")


def _optional_bool_value(data: Mapping[str, ProposalValue], key: str) -> bool | None:
    value = data.get(key)
    return value if isinstance(value, bool) else None


def _optional_type_name(data: Mapping[str, ProposalValue]) -> str | None:
    return _optional_string_value(data, "type_name")


def _required_type_name_or_id(data: Mapping[str, ProposalValue]) -> str | None:
    type_name = _optional_string_value(data, "type_name")
    type_id = _optional_int_value(data, "type_id")
    if type_name is not None:
        return type_name
    if type_id is not None:
        return None
    raise ValueError("type_name or type_id is required")
