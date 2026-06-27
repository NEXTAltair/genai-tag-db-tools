from __future__ import annotations

from types import SimpleNamespace

from genai_tag_db_tools.core_api import recommend_tag_record_refinement


class _RepoWithMeta:
    def get_format_id(self, format_name: str) -> int:
        return {"danbooru": 1, "e621": 2}[format_name]

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        return {
            (1, "meta"): 5,
            (2, "meta"): 7,
        }.get((format_id, type_name))

    def get_type_name_by_format_type_id(self, format_id: int, type_id: int) -> str | None:
        return {
            (1, 0): "general",
            (1, 1): "general",
            (1, 5): "meta",
            (2, 0): "general",
            (2, 7): "meta",
        }.get((format_id, type_id))

    def get_tag_status(self, tag_id: int, format_id: int):
        return None


class _RepoWithDeprecatedOverlay(_RepoWithMeta):
    def get_tag_status(self, tag_id: int, format_id: int):
        return SimpleNamespace(
            tag_id=tag_id,
            format_id=format_id,
            type_id=5,
            alias=False,
            preferred_tag_id=tag_id,
            deprecated=True,
        )


def _reason_codes(row: dict, **kwargs) -> list[str]:
    return [reason.code for reason in recommend_tag_record_refinement(row, **kwargs).reasons]


def test_deprecated_tag_is_reported_without_status_proposal():
    row = {
        "tag_id": 10,
        "tag": "old tag",
        "deprecated": True,
        "type_id": 1,
        "type_name": "general",
        "format_statuses": {},
    }

    recommendation = recommend_tag_record_refinement(row, format_name="danbooru")

    assert recommendation.needs_refinement is True
    assert _reason_codes(row, format_name="danbooru") == ["deprecated_tag"]
    assert recommendation.proposals == []


def test_unknown_type_is_review_only_and_preserves_unknown_format_name():
    row = {
        "tag_id": 1_000_000_010,
        "tag": "custom token",
        "deprecated": False,
        "type_id": 0,
        "type_name": "unknown",
        "format_statuses": {},
    }

    recommendation = recommend_tag_record_refinement(row)

    assert _reason_codes(row) == ["unknown_type"]
    assert recommendation.proposals == []
    assert recommendation.suggestions[0].kind == "review_only"


def test_training_unsuitable_external_id_uses_status_correction_proposal():
    row = {
        "tag_id": 12,
        "tag": "pixiv_id",
        "deprecated": False,
        "type_id": 1,
        "type_name": "general",
        "format_statuses": {},
    }

    recommendation = recommend_tag_record_refinement(row, format_name="unknown")

    assert [reason.code for reason in recommendation.reasons] == [
        "site_info_token",
        "external_id_tag",
        "training_unsuitable",
        "status_type_conflict",
    ]
    assert len(recommendation.proposals) == 1
    proposal = recommendation.proposals[0]
    assert proposal.kind == "status_correction"
    assert proposal.target.kind == "tag_status"
    assert proposal.target.target_scope == "base"
    assert proposal.target.target_tag_id == 12
    assert proposal.target.format_name == "unknown"
    assert proposal.current == {"deprecated": False}
    assert proposal.proposed == {"deprecated": True}
    assert proposal.reason_codes == ["training_unsuitable"]


def test_type_correction_candidate_is_only_emitted_when_format_has_meta_type():
    row = {
        "tag_id": 13,
        "tag": "__source_request",
        "deprecated": False,
        "type_id": 1,
        "type_name": "general",
        "format_statuses": {},
    }

    without_repo = recommend_tag_record_refinement(row, format_name="danbooru")
    with_repo = recommend_tag_record_refinement(row, format_name="danbooru", repo=_RepoWithMeta())

    assert "type_correction_candidate" not in [reason.code for reason in without_repo.reasons]
    assert "type_correction_candidate" in [reason.code for reason in with_repo.reasons]
    type_proposal = next(p for p in with_repo.proposals if p.kind == "type_correction")
    assert type_proposal.target.format_name == "danbooru"
    assert type_proposal.current == {"type_id": 1, "type_name": "general"}
    assert type_proposal.proposed == {"type_id": 5, "type_name": "meta"}


def test_format_statuses_override_row_level_status_and_preserve_user_scope():
    row = {
        "tag_id": 1_000_000_042,
        "tag": "rating:safe",
        "deprecated": False,
        "type_id": 1,
        "type_name": "general",
        "format_statuses": {
            "danbooru": {
                "deprecated": True,
                "type_id": 5,
                "type_name": "meta",
            }
        },
    }

    recommendation = recommend_tag_record_refinement(row, format_name="danbooru")

    assert [reason.code for reason in recommendation.reasons] == [
        "deprecated_tag",
        "site_info_token",
        "training_unsuitable",
    ]
    assert recommendation.proposals == []


def test_missing_requested_format_status_does_not_use_other_format_row_level_status():
    row = {
        "tag_id": 1_000_000_046,
        "tag": "other only",
        "deprecated": True,
        "type_id": 5,
        "type_name": "meta",
        "format_statuses": {
            "other_format": {
                "deprecated": True,
                "type_id": 5,
                "type_name": "meta",
            }
        },
    }

    recommendation = recommend_tag_record_refinement(row, format_name="danbooru")

    assert [reason.code for reason in recommendation.reasons] == ["missing_format_status"]
    assert recommendation.suggestions[0].kind == "review_only"
    assert recommendation.proposals == []


def test_numeric_format_status_key_is_used_when_repo_resolves_format_id():
    row = {
        "tag_id": 1_000_000_044,
        "tag": "rating:safe",
        "deprecated": False,
        "type_id": 1,
        "type_name": "general",
        "format_statuses": {
            "1": {
                "deprecated": True,
                "type_id": 5,
                "type_name": "meta",
            }
        },
    }

    recommendation = recommend_tag_record_refinement(
        row,
        format_name="danbooru",
        repo=_RepoWithMeta(),
    )

    assert [reason.code for reason in recommendation.reasons] == [
        "deprecated_tag",
        "site_info_token",
        "training_unsuitable",
    ]
    assert recommendation.proposals == []


def test_numeric_format_status_type_name_is_resolved_from_repo():
    row = {
        "tag_id": 1_000_000_045,
        "tag": "custom token",
        "deprecated": False,
        "type_id": None,
        "type_name": "",
        "format_statuses": {
            "1": {
                "deprecated": False,
                "type_id": 0,
            }
        },
    }

    recommendation = recommend_tag_record_refinement(
        row,
        format_name="danbooru",
        repo=_RepoWithMeta(),
    )

    assert recommendation.needs_refinement is False
    assert recommendation.reasons == []


def test_repo_overlay_status_overrides_base_row_status():
    row = {
        "tag_id": 46,
        "tag": "old tag",
        "deprecated": False,
        "type_id": 1,
        "type_name": "general",
        "format_statuses": {},
    }

    recommendation = recommend_tag_record_refinement(
        row,
        format_name="danbooru",
        repo=_RepoWithDeprecatedOverlay(),
    )

    assert [reason.code for reason in recommendation.reasons] == ["deprecated_tag"]
    assert recommendation.proposals == []


def test_status_correction_preserves_user_target_scope_and_tag_id():
    row = {
        "tag_id": 1_000_000_043,
        "tag": "source:https://example.test/image.png",
        "deprecated": False,
        "type_id": 1,
        "type_name": "general",
        "format_statuses": {},
    }

    recommendation = recommend_tag_record_refinement(row, format_name="unknown")

    proposal = recommendation.proposals[0]
    assert proposal.kind == "status_correction"
    assert proposal.target.target_scope == "user"
    assert proposal.target.target_tag_id == 1_000_000_043
    assert proposal.target.format_name == "unknown"
