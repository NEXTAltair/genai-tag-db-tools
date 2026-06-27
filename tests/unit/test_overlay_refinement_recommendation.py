from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.core_api import recommend_manual_refinement
from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    UserOverlayBase,
    UserTag,
    UserTagStatusPatch,
)

_FORMAT_ID = 1000
_OTHER_FORMAT_ID = 2000
_BLUE_EYES_ID = 10
_BLU_EYES_ID = 11
_WEDDING_DRESS_ID = 20
_WEDDING_CRESS_ID = 21
_GREEN_HAIR_ID = 30
_PIXIV_ID_ID = 40
_OLD_TAG_ID = 50
_USER_ALIAS_ID = USER_TAG_ID_OFFSET + 1
_USER_PREFERRED_ID = USER_TAG_ID_OFFSET + 2
_USER_OTHER_ONLY_ID = USER_TAG_ID_OFFSET + 3


@pytest.fixture
def base_engine(tmp_path: Path):
    db_path = tmp_path / "base.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def user_engine(tmp_path: Path):
    db_path = tmp_path / "user.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    UserOverlayBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def base_session_factory(base_engine):
    return sessionmaker(bind=base_engine, autoflush=False, autocommit=False)


@pytest.fixture
def user_session_factory(user_engine):
    return sessionmaker(bind=user_engine, autoflush=False, autocommit=False)


def _add_format(session, format_id: int, name: str) -> None:
    session.add(TagFormat(format_id=format_id, format_name=name))
    session.add(TagTypeName(type_name_id=format_id, type_name=f"general_{format_id}"))
    session.add(
        TagTypeFormatMapping(format_id=format_id, type_id=0, type_name_id=format_id)
    )


def _add_base_status(
    session,
    tag_id: int,
    *,
    format_id: int = _FORMAT_ID,
    alias: bool = False,
    preferred_tag_id: int | None = None,
    deprecated: bool = False,
) -> None:
    session.add(
        TagStatus(
            tag_id=tag_id,
            format_id=format_id,
            type_id=0,
            alias=alias,
            preferred_tag_id=preferred_tag_id if preferred_tag_id is not None else tag_id,
            deprecated=deprecated,
        )
    )


@pytest.fixture
def populated_base(base_session_factory):
    with base_session_factory() as session:
        _add_format(session, _FORMAT_ID, "test_format")
        _add_format(session, _OTHER_FORMAT_ID, "other_format")
        session.add_all(
            [
                Tag(tag_id=_BLUE_EYES_ID, source_tag="blue_eyes", tag="blue eyes"),
                Tag(tag_id=_BLU_EYES_ID, source_tag="blu_eyes", tag="blu eyes"),
                Tag(
                    tag_id=_WEDDING_DRESS_ID,
                    source_tag="wedding_dress",
                    tag="wedding dress",
                ),
                Tag(
                    tag_id=_WEDDING_CRESS_ID,
                    source_tag="wedding_cress",
                    tag="wedding cress",
                ),
                Tag(tag_id=_GREEN_HAIR_ID, source_tag="green_hair", tag="green hair"),
                Tag(tag_id=_PIXIV_ID_ID, source_tag="pixiv_id", tag="pixiv id"),
                Tag(tag_id=_OLD_TAG_ID, source_tag="old_tag", tag="old tag"),
            ]
        )
        session.flush()
        _add_base_status(session, _BLUE_EYES_ID)
        _add_base_status(session, _BLU_EYES_ID, format_id=_OTHER_FORMAT_ID)
        _add_base_status(session, _BLU_EYES_ID, alias=True, preferred_tag_id=_BLUE_EYES_ID)
        _add_base_status(session, _WEDDING_DRESS_ID)
        _add_base_status(session, _WEDDING_CRESS_ID)
        _add_base_status(session, _GREEN_HAIR_ID, format_id=_OTHER_FORMAT_ID)
        _add_base_status(session, _PIXIV_ID_ID)
        _add_base_status(session, _OLD_TAG_ID, deprecated=True)
        session.add(TagTranslation(tag_id=_BLUE_EYES_ID, language="ja", translation="青い目"))
        session.commit()


@pytest.fixture
def populated_user(user_session_factory):
    with user_session_factory() as session:
        session.add_all(
            [
                UserTag(tag_id=_USER_ALIAS_ID, source_tag="user_blu", tag="user blu"),
                UserTag(
                    tag_id=_USER_PREFERRED_ID,
                    source_tag="user preferred",
                    tag="user preferred",
                ),
                UserTag(
                    tag_id=_USER_OTHER_ONLY_ID,
                    source_tag="user other",
                    tag="user other",
                ),
            ]
        )
        session.flush()
        session.add(
            UserTagStatusPatch(
                target_scope="user",
                target_tag_id=_USER_ALIAS_ID,
                format_id=_FORMAT_ID,
                type_id=0,
                alias=True,
                preferred_scope="base",
                preferred_tag_id=_BLUE_EYES_ID,
                deprecated=False,
            )
        )
        session.add(
            UserTagStatusPatch(
                target_scope="user",
                target_tag_id=_USER_PREFERRED_ID,
                format_id=_FORMAT_ID,
                type_id=0,
                alias=False,
                preferred_scope="user",
                preferred_tag_id=_USER_PREFERRED_ID,
                deprecated=False,
            )
        )
        session.add(
            UserTagStatusPatch(
                target_scope="user",
                target_tag_id=_USER_OTHER_ONLY_ID,
                format_id=_OTHER_FORMAT_ID,
                type_id=0,
                alias=False,
                preferred_scope="user",
                preferred_tag_id=_USER_OTHER_ONLY_ID,
                deprecated=False,
            )
        )
        session.commit()


@pytest.fixture
def merged_reader(base_session_factory, user_session_factory, populated_base, populated_user):
    return MergedTagReader(
        base_repo=TagReader(session_factory=base_session_factory),
        user_repo=OverlayTagReader(session_factory=user_session_factory),
    )


def _codes(recommendation) -> list[str]:
    return [reason.code for reason in recommendation.reasons]


def test_exact_normal_tag_suppresses_extra_warning(merged_reader):
    recommendation = recommend_manual_refinement(
        "blue eyes",
        merged_reader,
        format_name="test_format",
    )

    assert recommendation.needs_refinement is False
    assert recommendation.reasons == []
    assert recommendation.suggestions == []


def test_base_alias_recommends_preferred_tag(merged_reader):
    recommendation = recommend_manual_refinement(
        "blu eyes",
        merged_reader,
        format_name="test_format",
    )

    assert _codes(recommendation) == ["alias_tag"]
    assert [(s.kind, s.tag) for s in recommendation.suggestions] == [
        ("correction_candidate", "blue eyes")
    ]


def test_unknown_format_exact_alias_still_recommends_preferred_tag(merged_reader):
    recommendation = recommend_manual_refinement("blu eyes", merged_reader)

    assert _codes(recommendation) == ["alias_tag"]
    assert [(s.kind, s.tag) for s in recommendation.suggestions] == [
        ("correction_candidate", "blue eyes")
    ]


def test_exact_tag_without_requested_format_status_needs_review(merged_reader):
    recommendation = recommend_manual_refinement(
        "user other",
        merged_reader,
        format_name="test_format",
    )

    assert _codes(recommendation) == ["missing_format_status"]
    assert recommendation.suggestions[0].kind == "review_only"


def test_translation_only_match_is_review_only_not_canonical_hit(merged_reader):
    recommendation = recommend_manual_refinement(
        "青い目",
        merged_reader,
        format_name="test_format",
    )

    assert _codes(recommendation) == ["translation_match_tag"]
    assert recommendation.suggestions[0].kind == "review_only"


def test_site_info_source_token_keeps_review_even_when_normalized_tag_exists(merged_reader):
    recommendation = recommend_manual_refinement(
        "pixiv_id",
        merged_reader,
        format_name="test_format",
    )

    assert _codes(recommendation) == ["site_info_token"]
    assert recommendation.suggestions[0].kind == "review_only"


def test_management_token_input_needs_review_without_repo():
    recommendation = recommend_manual_refinement("rating:safe")

    assert _codes(recommendation) == ["site_info_token"]
    assert recommendation.suggestions[0].kind == "review_only"


def test_user_alias_to_base_preferred_recommends_cross_scope_preferred(merged_reader):
    recommendation = recommend_manual_refinement(
        "user blu",
        merged_reader,
        format_name="test_format",
    )

    assert _codes(recommendation) == ["alias_tag"]
    assert recommendation.suggestions[0].tag == "blue eyes"


def test_typo_candidate_is_alias_addition_proposal_with_scopes(merged_reader):
    recommendation = recommend_manual_refinement(
        "weding dress",
        merged_reader,
        format_name="test_format",
    )

    assert _codes(recommendation) == ["typo_alias_candidate"]
    assert recommendation.suggestions[0].tag == "wedding dress"
    assert len(recommendation.proposals) == 1
    proposal = recommendation.proposals[0]
    assert proposal.kind == "alias_addition"
    assert proposal.target.target_scope == "user"
    assert proposal.target.target_tag_id is None
    assert proposal.target.preferred_scope == "base"
    assert proposal.target.preferred_tag_id == _WEDDING_DRESS_ID
    assert proposal.target.format_name == "test_format"
    assert proposal.proposed == {
        "alias": True,
        "alias_tag": "weding dress",
        "preferred_tag": "wedding dress",
        "preferred_scope": "base",
        "preferred_tag_id": _WEDDING_DRESS_ID,
    }


def test_ambiguous_typo_candidates_are_not_decided(merged_reader):
    recommendation = recommend_manual_refinement(
        "wedding xress",
        merged_reader,
        format_name="test_format",
    )

    assert _codes(recommendation) == ["ambiguous_alias_candidates"]
    assert {s.tag for s in recommendation.suggestions} == {"wedding dress", "wedding cress"}
    assert recommendation.proposals == []


def test_format_specific_candidates_are_not_mixed(merged_reader):
    recommendation = recommend_manual_refinement(
        "gren hair",
        merged_reader,
        format_name="test_format",
    )

    assert recommendation.needs_refinement is False
    assert recommendation.reasons == []
    assert recommendation.proposals == []


def test_unknown_format_does_not_crash_and_uses_unknown_in_proposal(merged_reader):
    recommendation = recommend_manual_refinement(
        "weding dress",
        merged_reader,
        format_name="unknown",
    )

    assert _codes(recommendation) == ["typo_alias_candidate"]
    assert recommendation.proposals[0].target.format_name == "unknown"


def test_unknown_format_typo_candidate_does_not_prefer_existing_alias(merged_reader):
    recommendation = recommend_manual_refinement("blu eyez", merged_reader)

    assert _codes(recommendation) == ["typo_alias_candidate"]
    assert recommendation.suggestions[0].tag == "blue eyes"
    assert recommendation.proposals[0].target.preferred_tag_id == _BLUE_EYES_ID


def test_deprecated_tag_is_not_used_as_typo_target(merged_reader):
    recommendation = recommend_manual_refinement(
        "old teg",
        merged_reader,
        format_name="test_format",
    )

    assert recommendation.needs_refinement is False
    assert recommendation.proposals == []
