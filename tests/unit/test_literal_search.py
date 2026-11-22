"""`*` / `%` を文字として扱う完全一致検索 (LoRAIro #1620)。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.core_api import search_tags
from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagFormat,
    UserOverlayBase,
    UserTag,
    UserTagTranslationPatch,
)
from genai_tag_db_tools.db.user_tag_repository import UserTagRepository
from genai_tag_db_tools.models import TagRegisterRequest, TagSearchRequest
from genai_tag_db_tools.services.tag_register import TagRegisterService

pytestmark = pytest.mark.unit

_USER_ID = USER_TAG_ID_OFFSET


@pytest.fixture
def db(tmp_path) -> Iterator[tuple]:
    engines = [create_engine(f"sqlite:///{tmp_path / name}.db") for name in ("base", "user")]
    for engine in engines:
        Base.metadata.create_all(engine)
    UserOverlayBase.metadata.create_all(engines[1])
    base, user = (sessionmaker(bind=engine) for engine in engines)
    with base() as session:
        session.add(TagFormat(format_id=1, format_name="danbooru"))
        tags = ["1950s", "alphabet", "100% orange juice", "100%", "a*b", "translated"]
        session.add_all(Tag(tag_id=i, tag=t, source_tag=t) for i, t in enumerate(tags, start=1))
        session.commit()
    with user() as session:
        session.add(UserTag(tag_id=_USER_ID, tag="my*tag", source_tag="my*tag"))
        session.add(UserTag(tag_id=_USER_ID + 1, tag="my long tag", source_tag="my long tag"))
        session.add(
            UserTagTranslationPatch(
                target_scope="base", target_tag_id=6, language="ja", translation="訳*語"
            )
        )
        session.commit()
    statements: list[str] = []
    for engine in engines:
        event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    reader = MergedTagReader(base_repo=TagReader(base), user_repo=OverlayTagReader(user))
    yield reader, user, statements
    for engine in engines:
        engine.dispose()


def _likes(statements: list[str]) -> list[str]:
    return [sql for sql in statements if " LIKE " in sql.upper()]


_EXACT_CASES = [
    ("100%", [4]),
    ("a*b", [5]),
    ("my*tag", [_USER_ID]),
    ("訳*語", [6]),
    ("50%", []),
    ("al*bet", []),
    ("my*", []),
]


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("query,ids", _EXACT_CASES)
def test_literal_request_is_exact_match(db, query, ids, partial):
    reader, _, statements = db
    result = search_tags(reader, TagSearchRequest(query=query, partial=partial, literal=True))
    assert [item.tag_id for item in result.items] == ids
    assert _likes(statements) == []


@pytest.mark.parametrize("format_name", [None, "danbooru"])
@pytest.mark.parametrize("lightweight", [False, True])
@pytest.mark.parametrize("query", ["50%", "al*bet", "my*"])
def test_bulk_miss_does_not_fall_back_to_wildcard(db, query, lightweight, format_name):
    reader, _, statements = db
    found = reader.search_tags_bulk(
        [query], format_name=format_name, resolve_preferred=True, lightweight=lightweight
    )
    assert found == {}
    assert _likes(statements) == []


@pytest.mark.parametrize("lightweight", [False, True])
@pytest.mark.parametrize("query,tag_id", [("100%", 4), ("a*b", 5), ("my*tag", _USER_ID)])
def test_bulk_finds_symbol_tag(db, query, tag_id, lightweight):
    reader, _, statements = db
    found = reader.search_tags_bulk([query], resolve_preferred=True, lightweight=lightweight)
    assert found[query]["tag_id"] == tag_id
    assert _likes(statements) == []


@pytest.mark.parametrize("query,ids", _EXACT_CASES[:3] + _EXACT_CASES[4:])
def test_bulk_all_is_exact_match(db, query, ids):
    reader, _, statements = db
    found = reader.search_tags_bulk_all([query])
    assert [row["tag_id"] for row in found.get(query, [])] == ids
    assert _likes(statements) == []


@pytest.mark.parametrize("query,ids", _EXACT_CASES)
def test_name_lookup_without_partial_is_exact(db, query, ids):
    reader, _, statements = db
    expected = [] if query == "訳*語" else ids  # タグ名だけを引き、翻訳は見ない
    found = reader.get_tag_id_by_name(query)
    assert found == (expected[0] if expected else None)
    assert _likes(statements) == []


@pytest.mark.parametrize("scope", ["base", "user"])
@pytest.mark.parametrize("tag", ["50%", "al*bet", "my*"])
def test_register_does_not_reuse_wildcard_match(db, tag, scope):
    reader, user, statements = db
    service = TagRegisterService(
        repository=TagRepository(session_factory=user, reader=reader),
        reader=reader,
        user_tag_repo=UserTagRepository(user),
    )
    result = service.register_tag(
        TagRegisterRequest(tag=tag, format_name="Lorairo", type_name="unknown", scope=scope)
    )
    assert result.created is True
    with user() as session:
        assert session.get(Tag if scope == "base" else UserTag, result.tag_id).tag == tag
    assert _likes(statements) == []


@pytest.mark.parametrize(
    "query,partial,ids",
    [
        ("50%", False, [1]),
        ("alph*", False, [2]),
        ("100%", False, [3, 4]),
        ("alph*", True, [2]),
        ("my*", False, [_USER_ID, _USER_ID + 1]),
    ],
)
def test_default_search_keeps_wildcard(db, query, partial, ids):
    reader, _, statements = db
    result = search_tags(reader, TagSearchRequest(query=query, partial=partial))
    assert [item.tag_id for item in result.items] == ids
    assert _likes(statements)


def test_partial_name_lookup_keeps_wildcard(db):
    reader, _, _ = db
    assert reader.get_tag_id_by_name("alph*", partial=True) == 2
