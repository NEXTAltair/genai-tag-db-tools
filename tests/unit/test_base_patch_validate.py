"""Tests for base DB correction patch validation (#58)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from genai_tag_db_tools.services.base_patch.models import BaseCorrectionPatch
from genai_tag_db_tools.services.base_patch.validate import (
    validate_base_patch,
    validate_base_patch_file,
)


class FakeReader:
    """Minimal read-only reader for validation tests."""

    def __init__(self) -> None:
        self._tags = {"black hair": 1, "blakc hair": 2, "blue eyes": 3, "loop a": 10, "loop b": 11}
        self._formats = {"danbooru": 1, "unknown": 999}
        self._types = {("danbooru", "character"): 4, ("danbooru", "general"): 1}
        # alias cycle fixture: loop a -> loop b -> loop a
        self._status = {
            (10, 1): SimpleNamespace(alias=True, preferred_tag_id=11, type_id=1, deprecated=False),
            (11, 1): SimpleNamespace(alias=True, preferred_tag_id=10, type_id=1, deprecated=False),
        }

    def get_format_id(self, format_name: str) -> int:
        if format_name in self._formats:
            return self._formats[format_name]
        raise ValueError(format_name)

    def get_tag_id_by_name(self, name: str, partial: bool = False) -> int | None:
        return self._tags.get(name)

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        name = {v: k for k, v in self._formats.items()}.get(format_id)
        return self._types.get((name, type_name)) if name else None

    def get_tag_status(self, tag_id: int, format_id: int):
        return self._status.get((tag_id, format_id))

    def get_tag_by_id(self, tag_id: int):
        name = {v: k for k, v in self._tags.items()}.get(tag_id)
        return SimpleNamespace(tag=name) if name else None


def _patch(patch_type: str, target: dict, proposed: dict, **extra) -> BaseCorrectionPatch:
    data = {"schema_version": 1, "patch_type": patch_type, "target": target, "proposed": proposed}
    data.update(extra)
    return BaseCorrectionPatch.model_validate(data)


def _codes(result) -> set[str]:
    return {issue.code for issue in result.errors}


def test_valid_translation_patch_passes_without_db_change() -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "blue eyes", "field": "translation.ja"},
        {"translation": "青い目", "language": "ja"},
        patch_id="sha256:x",
    )
    result = validate_base_patch(patch)
    assert result.status == "valid"
    assert result.errors == []


def test_missing_required_field_rejected_in_file() -> None:
    # proposed が無いので構築に失敗 -> missing_required_field
    line = json.dumps({"schema_version": 1, "patch_type": "translation_correction", "target": {}})
    result_items = _validate_lines([line])
    assert result_items[0].status == "invalid"
    assert "missing_required_field" in {e.code for e in result_items[0].errors}


def test_unsupported_schema_version_rejected() -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "x", "field": "translation.ja"},
        {"translation": "y"},
        schema_version=2,
    )
    result = validate_base_patch(patch)
    assert "unsupported_schema_version" in _codes(result)


@pytest.mark.parametrize("scope", ["user", "local"])
def test_user_local_scope_rejected(scope: str) -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "x", "field": "translation.ja"},
        {"translation": "y"},
        scope=scope,
    )
    assert "invalid_scope" in _codes(validate_base_patch(patch))


def test_explicit_unapproved_and_unvalidated_rejected() -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "x", "field": "translation.ja"},
        {"translation": "y"},
        approved=False,
        validated=False,
    )
    codes = _codes(validate_base_patch(patch))
    assert "explicitly_unapproved" in codes
    assert "explicitly_unvalidated" in codes


def test_missing_optional_metadata_is_not_failure() -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "x", "field": "translation.ja"},
        {"translation": "y"},
    )
    result = validate_base_patch(patch)
    assert result.ok
    # patch_id 欠落は warning に留まる
    assert "missing_patch_id" in {w.code for w in result.warnings}


def test_approved_without_metadata_is_warning_only() -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "x", "field": "translation.ja"},
        {"translation": "y"},
        approved=True,
        patch_id="sha256:x",
    )
    result = validate_base_patch(patch)
    assert result.ok
    assert "missing_approval_metadata" in {w.code for w in result.warnings}


@pytest.mark.parametrize(
    "patch_type", ["metadata_correction", "training_policy_correction", "format_relation_review", "made_up"]
)
def test_unsupported_patch_types_rejected(patch_type: str) -> None:
    patch = _patch(patch_type, {"target_type": "translation", "tag": "x"}, {})
    assert "unsupported_patch_type" in _codes(validate_base_patch(patch))


def test_invalid_target_type_rejected() -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "tag_status", "tag": "x", "field": "translation.ja"},
        {"translation": "y"},
    )
    assert "invalid_target_type" in _codes(validate_base_patch(patch))


def test_alias_self_reference_rejected() -> None:
    patch = _patch(
        "alias_addition",
        {"target_type": "alias", "tag": "black hair", "format_name": "unknown"},
        {"alias": True, "preferred_tag": "black hair"},
    )
    assert "self_alias" in _codes(validate_base_patch(patch))


def test_alias_missing_preferred_detected() -> None:
    patch = _patch(
        "alias_addition",
        {"target_type": "alias", "tag": "blakc hair", "format_name": "unknown"},
        {"alias": True},
    )
    assert "missing_preferred_tag" in _codes(validate_base_patch(patch))


def test_alias_cycle_detected_with_reader() -> None:
    patch = _patch(
        "preferred_tag_correction",
        {"target_type": "alias", "tag": "loop b", "format_name": "danbooru"},
        {"preferred_tag": "loop a"},
    )
    assert "alias_cycle" in _codes(validate_base_patch(patch, repo=FakeReader()))


def test_missing_format_name_for_format_dependent_patch() -> None:
    patch = _patch(
        "status_correction",
        {"target_type": "tag_status", "tag": "x", "field": "TAG_STATUS.deprecated"},
        {"deprecated": True},
    )
    assert "missing_format_name" in _codes(validate_base_patch(patch))


def test_invalid_format_name_with_reader() -> None:
    patch = _patch(
        "status_correction",
        {"target_type": "tag_status", "tag": "x", "format_name": "nope", "field": "TAG_STATUS.deprecated"},
        {"deprecated": True},
    )
    assert "invalid_format_name" in _codes(validate_base_patch(patch, repo=FakeReader()))


def test_empty_translation_rejected() -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "x", "field": "translation.ja"},
        {"translation": "   "},
    )
    assert "empty_translation" in _codes(validate_base_patch(patch))


def test_translation_language_mismatch_detected() -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "x", "field": "translation.ja"},
        {"translation": "青い目", "language": "zh"},
    )
    assert "translation_language_mismatch" in _codes(validate_base_patch(patch))


def test_status_correction_only_allows_deprecated_field() -> None:
    patch = _patch(
        "status_correction",
        {"target_type": "tag_status", "tag": "x", "format_name": "unknown", "field": "TAG_STATUS.alias"},
        {"deprecated": True},
    )
    assert "status_field_not_allowed" in _codes(validate_base_patch(patch))


def test_status_correction_invalid_deprecated_value() -> None:
    patch = _patch(
        "status_correction",
        {
            "target_type": "tag_status",
            "tag": "x",
            "format_name": "unknown",
            "field": "TAG_STATUS.deprecated",
        },
        {"deprecated": "yes"},
    )
    assert "invalid_deprecated_value" in _codes(validate_base_patch(patch))


def test_invalid_type_name_missing() -> None:
    patch = _patch(
        "type_correction",
        {"target_type": "tag_type", "tag": "x", "format_name": "danbooru"},
        {},
    )
    assert "invalid_type_name" in _codes(validate_base_patch(patch))


def test_type_mapping_will_be_created_warning() -> None:
    patch = _patch(
        "type_correction",
        {"target_type": "tag_type", "tag": "x", "format_name": "danbooru"},
        {"type_name": "brand_new_type"},
        patch_id="sha256:x",
    )
    result = validate_base_patch(patch, repo=FakeReader())
    assert result.ok
    assert "type_mapping_will_be_created" in {w.code for w in result.warnings}


def test_format_name_none_is_not_all_formats() -> None:
    patch = _patch(
        "type_correction",
        {"target_type": "tag_type", "tag": "x", "format_name": None},
        {"type_name": "character"},
    )
    assert "missing_format_name" in _codes(validate_base_patch(patch))


def test_validate_file_and_report_output(tmp_path: Path) -> None:
    patches = [
        {
            "schema_version": 1,
            "patch_id": "sha256:a",
            "patch_type": "translation_correction",
            "target": {"target_type": "translation", "tag": "blue eyes", "field": "translation.ja"},
            "proposed": {"translation": "青い目", "language": "ja"},
        },
        {
            "schema_version": 1,
            "patch_type": "status_correction",
            "target": {"target_type": "tag_status", "tag": "x", "field": "TAG_STATUS.alias"},
            "proposed": {"deprecated": True},
        },
    ]
    patch_file = tmp_path / "patches.jsonl"
    patch_file.write_text("\n".join(json.dumps(p) for p in patches), encoding="utf-8")
    report = tmp_path / "report.tsv"

    result = validate_base_patch_file(patch_file, report=report)
    assert result.valid_count == 1
    assert result.invalid_count == 1
    assert not result.ok

    lines = report.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t") == [
        "line_number",
        "patch_id",
        "patch_type",
        "target_type",
        "target_tag",
        "format_name",
        "status",
        "error_code",
        "message",
    ]
    assert any("status_field_not_allowed" in line for line in lines[1:])


def _validate_lines(lines: list[str]):
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as fh:
        fh.write("\n".join(lines))
        path = Path(fh.name)
    try:
        return validate_base_patch_file(path).items
    finally:
        path.unlink(missing_ok=True)
