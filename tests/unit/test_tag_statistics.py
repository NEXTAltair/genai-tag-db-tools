from __future__ import annotations

from collections.abc import Callable

import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.db.schema import (
    Base,
    TagFormat,
    TagTypeFormatMapping,
    TagTypeName,
)
from genai_tag_db_tools.services.tag_statistics import TagStatistics


pytestmark = pytest.mark.db_tools


@pytest.fixture()
def session_factory() -> Callable[[], Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_format_and_type(session: Session, *, format_id: int = 1, type_id: int = 0) -> None:
    session.add(TagFormat(format_id=format_id, format_name="test"))
    session.add(TagTypeName(type_name_id=type_id, type_name="general"))
    session.add(
        TagTypeFormatMapping(format_id=format_id, type_id=type_id, type_name_id=type_id)
    )
    session.commit()


def _seed_sample_data(
    repo: TagRepository, session_factory: Callable[[], Session]
) -> dict[str, int]:
    tag_a = repo.create_tag("alpha", "alpha")
    tag_b = repo.create_tag("beta", "beta")
    tag_c = repo.create_tag("gamma", "gamma")

    with session_factory() as session:
        _seed_format_and_type(session)

    repo.update_tag_status(tag_a, format_id=1, alias=False, preferred_tag_id=tag_a, type_id=0)
    repo.update_tag_status(tag_b, format_id=1, alias=True, preferred_tag_id=tag_a, type_id=0)
    repo.update_tag_status(
        tag_c,
        format_id=1,
        alias=False,
        preferred_tag_id=tag_c,
        type_id=0,
        deprecated=True,
    )
    repo.update_usage_count(tag_a, format_id=1, count=10)
    repo.update_usage_count(tag_c, format_id=1, count=3)
    repo.add_or_update_translation(tag_a, language="ja", translation="alpha_ja")
    repo.add_or_update_translation(tag_b, language="en", translation="beta_en")
    repo.add_or_update_translation(tag_c, language="ja", translation="gamma_ja")
    return {"tag_a": tag_a, "tag_b": tag_b, "tag_c": tag_c}


def test_general_stats_counts_aliases(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    _seed_sample_data(repo, session_factory)

    stats = TagStatistics(session_factory())
    general = stats.get_general_stats()

    assert general["total_tags"] == 3
    assert general["alias_tags"] == 1
    assert general["non_alias_tags"] == 2


def test_usage_stats_returns_rows(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    ids = _seed_sample_data(repo, session_factory)

    stats = TagStatistics(session_factory())
    usage_df = stats.get_usage_stats()

    assert isinstance(usage_df, pl.DataFrame)
    assert usage_df.height == 1
    assert usage_df["format_name"][0] == "test"
    assert usage_df["usage_count"][0] == 10
    assert usage_df["tag_id"][0] == ids["tag_a"]


def test_type_distribution_counts_tags(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    _seed_sample_data(repo, session_factory)

    stats = TagStatistics(session_factory())
    type_df = stats.get_type_distribution()

    assert isinstance(type_df, pl.DataFrame)
    assert type_df.height == 1
    assert type_df["format_name"][0] == "test"
    assert type_df["type_name"][0] == "general"
    assert type_df["tag_count"][0] == 1


def test_translation_stats_lists_languages(session_factory: Callable[[], Session]) -> None:
    repo = TagRepository(session_factory)
    _seed_sample_data(repo, session_factory)

    stats = TagStatistics(session_factory())
    trans_df = stats.get_translation_stats()

    assert isinstance(trans_df, pl.DataFrame)
    assert trans_df.height == 3
    lang_map = {row["tag_id"]: row["languages"] for row in trans_df.to_dicts()}
    assert any("ja" in langs for langs in lang_map.values())
    assert any("en" in langs for langs in lang_map.values())
