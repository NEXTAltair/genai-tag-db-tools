"""Tests for base correction patch models and stable patch_id (#58/#60/#61)."""

from __future__ import annotations

from genai_tag_db_tools.services.base_patch.models import (
    SCHEMA_VERSION,
    BaseCorrectionPatch,
    compute_patch_id,
)


def _patch(**overrides) -> BaseCorrectionPatch:
    data = {
        "schema_version": SCHEMA_VERSION,
        "patch_type": "translation_correction",
        "target": {"target_type": "translation", "tag": "blue eyes", "field": "translation.ja"},
        "proposed": {"translation": "青い目", "language": "ja"},
        "scope": "base",
    }
    data.update(overrides)
    return BaseCorrectionPatch.model_validate(data)


def test_patch_id_is_stable_for_same_content() -> None:
    a = _patch(approved_by="alice", evidence={"detected_language": "zh"})
    b = _patch(approved_by="bob", evidence={"detected_language": "en"})
    assert compute_patch_id(a) == compute_patch_id(b)
    assert compute_patch_id(a).startswith("sha256:")


def test_patch_id_changes_when_proposed_changes() -> None:
    a = _patch()
    b = _patch(proposed={"translation": "蒼い目", "language": "ja"})
    assert compute_patch_id(a) != compute_patch_id(b)


def test_patch_id_changes_when_scope_changes() -> None:
    a = _patch(scope="base")
    b = _patch(scope=None)
    assert compute_patch_id(a) != compute_patch_id(b)


def test_optional_keys_default_to_none_or_empty() -> None:
    patch = BaseCorrectionPatch.model_validate(
        {
            "schema_version": 1,
            "patch_type": "status_correction",
            "target": {
                "target_type": "tag_status",
                "tag": "pixiv id",
                "format_name": "unknown",
                "field": "TAG_STATUS.deprecated",
            },
            "proposed": {"deprecated": True},
        }
    )
    assert patch.patch_id is None
    assert patch.scope is None
    assert patch.reason_codes == []
    assert patch.target_type == "tag_status"
    assert patch.target_tag == "pixiv id"
    assert patch.format_name == "unknown"
    assert patch.field == "TAG_STATUS.deprecated"


def test_extra_keys_are_allowed() -> None:
    patch = BaseCorrectionPatch.model_validate(
        {
            "schema_version": 1,
            "patch_type": "translation_correction",
            "target": {"target_type": "translation", "tag": "x", "field": "translation.ja"},
            "proposed": {"translation": "y"},
            "future_key": {"nested": 1},
        }
    )
    assert patch.model_dump()["future_key"] == {"nested": 1}
