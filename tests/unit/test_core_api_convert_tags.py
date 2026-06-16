from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools import core_api
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
from genai_tag_db_tools.db.schema import Base, TagFormat, TagTypeFormatMapping, TagTypeName


class FakeRepo:
    def __init__(self, mapping: dict[str, str], types: dict[str, str] | None = None) -> None:
        self._mapping = mapping
        self._types = types or {}

    def get_format_id(self, format_name: str) -> int | None:
        return 1 if format_name == "danbooru" else None

    def search_tags_bulk(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, dict[str, str]]:
        return {
            key: {"tag": self._mapping[key], "type_name": self._types.get(key, "general")}
            for key in keywords
            if key in self._mapping
        }


@pytest.fixture()
def danbooru_reader() -> MergedTagReader:
    """grey hair(general) と highres(meta) を持つ danbooru 用の MergedTagReader を構築する。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: Callable[[], Session] = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    reader = TagReader(factory)
    merged = MergedTagReader(base_repo=reader)
    repo = TagRepository(factory, reader=merged)

    with factory() as session:
        session.add(TagFormat(format_id=1, format_name="danbooru"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeName(type_name_id=2, type_name="meta"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add(TagTypeFormatMapping(format_id=1, type_id=1, type_name_id=2))
        session.commit()

    general_id = repo.create_tag("grey_hair", "grey hair")
    repo.update_tag_status(general_id, format_id=1, alias=False, preferred_tag_id=general_id, type_id=0)
    meta_id = repo.create_tag("highres", "highres")
    repo.update_tag_status(meta_id, format_id=1, alias=False, preferred_tag_id=meta_id, type_id=1)

    return merged


def test_convert_tags_case_insensitive_lookup(danbooru_reader: MergedTagReader) -> None:
    result = core_api.convert_tags(danbooru_reader, "Grey Hair", "danbooru")

    assert result == "grey hair"


def test_convert_tags_excludes_meta_types(danbooru_reader: MergedTagReader) -> None:
    result = core_api.convert_tags(
        danbooru_reader, "grey hair, highres", "danbooru", exclude_types=["meta"]
    )

    assert result == "grey hair"


def test_convert_tags_keeps_meta_without_exclude(danbooru_reader: MergedTagReader) -> None:
    result = core_api.convert_tags(danbooru_reader, "grey hair, highres", "danbooru")

    assert result == "grey hair, highres"


def test_convert_tags_normalizes_and_falls_back_to_words():
    repo = FakeRepo(
        {
            "blue hair": "blue hair",
            "red eyes": "red eyes",
            "object": "object",
        }
    )

    result = core_api.convert_tags(repo, "blue_hair\nmysterious object, red eyes", "danbooru")

    assert result == "blue hair, mysterious, object, red eyes"


def test_convert_tags_unknown_format_returns_original():
    repo = FakeRepo({"blue hair": "blue hair"})

    result = core_api.convert_tags(repo, "blue hair", "unknown")

    assert result == "blue hair"


def test_convert_tags_exclude_types_drops_meta_tag():
    repo = FakeRepo(
        {"blue hair": "blue hair", "highres": "highres"},
        types={"blue hair": "general", "highres": "meta"},
    )

    result = core_api.convert_tags(repo, "blue hair, highres", "danbooru", exclude_types=["meta"])

    assert result == "blue hair"
