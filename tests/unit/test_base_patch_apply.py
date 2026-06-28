"""Tests for applying base correction patches to a base DB build source (#60)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
from genai_tag_db_tools.db.schema import (
    Base,
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
)
from genai_tag_db_tools.services.base_patch.apply import (
    BasePatchApplyService,
    apply_base_patch_file,
)
from genai_tag_db_tools.services.base_patch.models import BaseCorrectionPatch

pytestmark = pytest.mark.db_tools


@pytest.fixture()
def session_factory() -> Callable[[], Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as session:
        session.add(TagFormat(format_id=1, format_name="danbooru"))
        session.add(TagFormat(format_id=999, format_name="unknown"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeName(type_name_id=2, type_name="character"))
        session.add(TagTypeName(type_name_id=3, type_name="unknown"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add(TagTypeFormatMapping(format_id=1, type_id=4, type_name_id=2))
        session.add(TagTypeFormatMapping(format_id=999, type_id=0, type_name_id=3))
        # base tags
        session.add(Tag(tag_id=1, source_tag="black hair", tag="black hair"))
        session.add(Tag(tag_id=3, source_tag="blue eyes", tag="blue eyes"))
        session.add(Tag(tag_id=7, source_tag="pixiv id", tag="pixiv id"))
        session.add(Tag(tag_id=5, source_tag="example character", tag="example character"))
        session.add(
            TagStatus(tag_id=5, format_id=1, type_id=0, alias=False, preferred_tag_id=5, deprecated=False)
        )
        session.add(
            TagStatus(tag_id=7, format_id=999, type_id=0, alias=False, preferred_tag_id=7, deprecated=False)
        )
        session.commit()
    return factory


@pytest.fixture()
def service(session_factory: Callable[[], Session]) -> BasePatchApplyService:
    reader = MergedTagReader(base_repo=TagReader(session_factory))
    repo = TagRepository(session_factory, reader=reader)
    return BasePatchApplyService(repo, reader)


def _patch(patch_type: str, target: dict, proposed: dict, **extra) -> BaseCorrectionPatch:
    data = {
        "schema_version": 1,
        "scope": "base",
        "patch_type": patch_type,
        "target": target,
        "proposed": proposed,
        "approved": True,
        "validated": True,
    }
    data.update(extra)
    return BaseCorrectionPatch.model_validate(data)


def test_apply_alias_addition(service: BasePatchApplyService, session_factory) -> None:
    patch = _patch(
        "alias_addition",
        {"target_type": "alias", "tag": "blakc hair", "format_name": "danbooru"},
        {"alias": True, "preferred_tag": "black hair"},
    )
    row = service.apply_patch(patch)
    assert row.status == "applied"
    with session_factory() as session:
        alias_tag = session.query(Tag).filter(Tag.tag == "blakc hair").one()
        status = (
            session.query(TagStatus)
            .filter(TagStatus.tag_id == alias_tag.tag_id, TagStatus.format_id == 1)
            .one()
        )
        assert status.alias is True
        assert status.preferred_tag_id == 1


def test_apply_translation(service: BasePatchApplyService, session_factory) -> None:
    patch = _patch(
        "translation_correction",
        {"target_type": "translation", "tag": "blue eyes", "field": "translation.ja"},
        {"translation": "青い目", "language": "ja"},
    )
    row = service.apply_patch(patch)
    assert row.status == "applied"
    with session_factory() as session:
        trans = session.query(TagTranslation).filter(TagTranslation.tag_id == 3).one()
        assert trans.language == "ja"
        assert trans.translation == "青い目"
    # second apply is idempotent
    assert service.apply_patch(patch).status == "already_applied"


def test_apply_type_correction(service: BasePatchApplyService, session_factory) -> None:
    patch = _patch(
        "type_correction",
        {"target_type": "tag_type", "tag": "example character", "format_name": "danbooru"},
        {"type_name": "character"},
    )
    row = service.apply_patch(patch)
    assert row.status == "applied"
    with session_factory() as session:
        status = session.query(TagStatus).filter(TagStatus.tag_id == 5, TagStatus.format_id == 1).one()
        assert status.type_id == 4


def test_apply_status_deprecated(service: BasePatchApplyService, session_factory) -> None:
    patch = _patch(
        "status_correction",
        {
            "target_type": "tag_status",
            "tag": "pixiv id",
            "format_name": "unknown",
            "field": "TAG_STATUS.deprecated",
        },
        {"deprecated": True},
    )
    row = service.apply_patch(patch)
    assert row.status == "applied"
    with session_factory() as session:
        status = session.query(TagStatus).filter(TagStatus.tag_id == 7, TagStatus.format_id == 999).one()
        assert status.deprecated is True
    assert service.apply_patch(patch).status == "already_applied"


def test_apply_preferred_tag_correction(service: BasePatchApplyService, session_factory) -> None:
    # first create an alias blakc hair -> black hair
    service.apply_patch(
        _patch(
            "alias_addition",
            {"target_type": "alias", "tag": "blakc hair", "format_name": "danbooru"},
            {"alias": True, "preferred_tag": "black hair"},
        )
    )
    # now repoint it to blue eyes
    row = service.apply_patch(
        _patch(
            "preferred_tag_correction",
            {"target_type": "alias", "tag": "blakc hair", "format_name": "danbooru"},
            {"preferred_tag": "blue eyes"},
        )
    )
    assert row.status == "applied"
    with session_factory() as session:
        alias_tag = session.query(Tag).filter(Tag.tag == "blakc hair").one()
        status = session.query(TagStatus).filter(TagStatus.tag_id == alias_tag.tag_id).one()
        assert status.preferred_tag_id == 3


def test_apply_tag_name_correction_creates_tag(service: BasePatchApplyService, session_factory) -> None:
    patch = _patch(
        "tag_name_correction",
        {"target_type": "tag_name", "source_tag": "blue__eyes"},
        {"tag": "blue green eyes"},
    )
    row = service.apply_patch(patch)
    assert row.status == "applied"
    with session_factory() as session:
        assert session.query(Tag).filter(Tag.tag == "blue green eyes").one_or_none() is not None


def test_unsupported_patch_type_rejected(service: BasePatchApplyService) -> None:
    patch = _patch(
        "format_relation_review",
        {"target_type": "format_relation", "tag": "wolf"},
        {},
    )
    row = service.apply_patch(patch)
    assert row.status == "rejected"


def test_explicitly_unvalidated_rejected(service: BasePatchApplyService) -> None:
    patch = _patch(
        "status_correction",
        {
            "target_type": "tag_status",
            "tag": "pixiv id",
            "format_name": "unknown",
            "field": "TAG_STATUS.deprecated",
        },
        {"deprecated": True},
        validated=False,
    )
    assert service.apply_patch(patch).status == "rejected"


def test_wrong_scope_rejected(service: BasePatchApplyService) -> None:
    patch = _patch(
        "status_correction",
        {
            "target_type": "tag_status",
            "tag": "pixiv id",
            "format_name": "unknown",
            "field": "TAG_STATUS.deprecated",
        },
        {"deprecated": True},
        scope="user",
    )
    assert service.apply_patch(patch).status == "rejected"


def test_dry_run_does_not_write(session_factory) -> None:
    reader = MergedTagReader(base_repo=TagReader(session_factory))
    repo = TagRepository(session_factory, reader=reader)
    dry = BasePatchApplyService(repo, reader, dry_run=True)
    patch = _patch(
        "status_correction",
        {
            "target_type": "tag_status",
            "tag": "pixiv id",
            "format_name": "unknown",
            "field": "TAG_STATUS.deprecated",
        },
        {"deprecated": True},
    )
    row = dry.apply_patch(patch)
    assert row.status == "applied"
    with session_factory() as session:
        status = session.query(TagStatus).filter(TagStatus.tag_id == 7, TagStatus.format_id == 999).one()
        assert status.deprecated is False


def test_apply_file_with_report_and_jsonl_load(session_factory, tmp_path: Path) -> None:
    reader = MergedTagReader(base_repo=TagReader(session_factory))
    repo = TagRepository(session_factory, reader=reader)
    patches = [
        _patch(
            "translation_correction",
            {"target_type": "translation", "tag": "blue eyes", "field": "translation.ja"},
            {"translation": "青い目", "language": "ja"},
        ),
        _patch(
            "status_correction",
            {
                "target_type": "tag_status",
                "tag": "pixiv id",
                "format_name": "unknown",
                "field": "TAG_STATUS.deprecated",
            },
            {"deprecated": True},
        ),
    ]
    patch_file = tmp_path / "patches.jsonl"
    patch_file.write_text(
        "\n".join(json.dumps(p.model_dump(mode="json", exclude_none=True)) for p in patches),
        encoding="utf-8",
    )
    report = tmp_path / "apply.tsv"

    result = apply_base_patch_file(patch_file, repository=repo, reader=reader, report=report)
    assert result.ok
    assert result.applied_count == 2

    lines = report.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t")[0] == "patch_id"
    assert "db_changes" in lines[0]


def test_invalid_patch_does_not_break_db(service: BasePatchApplyService, session_factory) -> None:
    patch = _patch(
        "status_correction",
        {
            "target_type": "tag_status",
            "tag": "pixiv id",
            "format_name": "unknown",
            "field": "TAG_STATUS.alias",
        },
        {"deprecated": True},
    )
    row = service.apply_patch(patch)
    assert row.status == "rejected"
    with session_factory() as session:
        status = session.query(TagStatus).filter(TagStatus.tag_id == 7, TagStatus.format_id == 999).one()
        assert status.deprecated is False
