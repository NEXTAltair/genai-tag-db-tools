"""公開 base DB の検索分類 (TAG_CATEGORIES / TAG_CATEGORY_MEMBERSHIPS) への対応 (Issue #153)。

分類テーブルは dataset builder (core/enrichment.py) が作る。fixture でも ORM ではなく
builder と同じ DDL で作り、ツール側の定義とのずれを検出できるようにする。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from genai_tag_db_tools import (
    TagCategory,
    TagCategoryDatabaseInfo,
    TagCategoryReaderProtocol,
    database_runtime_scope,
    get_tag_categories_batch,
    get_tag_category_database_info,
    get_tag_reader,
    initialize_databases,
    list_tag_categories,
    list_tag_category_namespaces,
    search_tags,
)
from genai_tag_db_tools.cli import main
from genai_tag_db_tools.db import runtime
from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
from genai_tag_db_tools.db.query_utils import TAG_ID_IN_CHUNK
from genai_tag_db_tools.db.repository import MergedTagReader, TagReader
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    DatabaseMetadata,
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
    UserOverlayBase,
    UserTag,
    UserTagTranslationPatch,
)
from genai_tag_db_tools.models import DbSourceRef, TagSearchRequest

pytestmark = pytest.mark.unit

# dataset builder 7e48d47 core/enrichment.py の SCHEMA と同じ DDL
_BUILDER_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS TAG_CATEGORIES (
        category_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, parent_id TEXT,
        label TEXT NOT NULL, depth INTEGER NOT NULL CHECK(depth >= 1), path TEXT NOT NULL,
        UNIQUE(namespace, path), FOREIGN KEY(parent_id) REFERENCES TAG_CATEGORIES(category_id))""",
    """CREATE TABLE IF NOT EXISTS TAG_CATEGORY_MEMBERSHIPS (
        tag_id INTEGER NOT NULL, category_id TEXT NOT NULL,
        PRIMARY KEY(tag_id, category_id), FOREIGN KEY(tag_id) REFERENCES TAGS(tag_id),
        FOREIGN KEY(category_id) REFERENCES TAG_CATEGORIES(category_id))""",
    """CREATE TABLE IF NOT EXISTS TAG_SOURCE_REFERENCES (
        bundle_id TEXT NOT NULL, tag_id INTEGER NOT NULL, source_path TEXT NOT NULL,
        source_row INTEGER NOT NULL CHECK(source_row >= 1),
        PRIMARY KEY(bundle_id, tag_id, source_path, source_row), FOREIGN KEY(tag_id) REFERENCES TAGS(tag_id))""",
    """CREATE TABLE IF NOT EXISTS TAG_CATEGORY_SOURCES (
        bundle_id TEXT NOT NULL, tag_id INTEGER NOT NULL, category_id TEXT NOT NULL,
        source_path TEXT NOT NULL, source_row INTEGER NOT NULL CHECK(source_row >= 1),
        PRIMARY KEY(bundle_id, tag_id, category_id, source_path, source_row),
        FOREIGN KEY(tag_id, category_id) REFERENCES TAG_CATEGORY_MEMBERSHIPS(tag_id, category_id))""",
    "CREATE INDEX IF NOT EXISTS idx_category_parent ON TAG_CATEGORIES(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_category_members ON TAG_CATEGORY_MEMBERSHIPS(category_id, tag_id)",
)

PG = "prompt-generator"
PM = "prompt-manager-203"
# (category_id, namespace, parent_id, path)
_CATEGORIES = [
    ("pg-hair", PG, None, ["髪"]),
    ("pg-hair-color", PG, "pg-hair", ["髪", "髪色"]),
    ("pg-hair-style", PG, "pg-hair", ["髪", "髪型"]),
    ("pg-hair-style-long", PG, "pg-hair-style", ["髪", "髪型", "長髪"]),
    ("pm-face", PM, None, ["表情"]),
    ("pm-character", PM, None, ["キャラ"]),
]
_MEMBERSHIPS = [
    (1, "pg-hair-color"),
    (1, "pg-hair-style"),
    (2, "pg-hair-color"),
    (3, "pg-hair-style-long"),
    (4, "pm-face"),
    (5, "pg-hair-style"),
    (6, "pg-hair-color"),
    (7, "pg-hair-color"),
    (8, "pm-character"),
]
# pg-hair の子孫に所属するタグ。format 未指定の merged 検索は deprecated を行の値 (format 非依存では
# False) で判定する既存仕様 (ADR 0006 Amendment) のため、deprecated の 7 も含む。
_HAIR_ACTIVE = [1, 2, 3, 5, 6, 7]
_USER_ID = USER_TAG_ID_OFFSET


def _create_category_db(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                TagFormat(format_id=0, format_name="unknown"),
                TagFormat(format_id=1, format_name="danbooru"),
                TagTypeName(type_name_id=0, type_name="unknown"),
                TagTypeName(type_name_id=1, type_name="general"),
                TagTypeName(type_name_id=2, type_name="character"),
                DatabaseMetadata(key="version", value="v-test-cat"),
            ]
        )
        session.flush()
        session.add_all(
            [
                TagTypeFormatMapping(format_id=0, type_id=0, type_name_id=0),
                TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1),
                TagTypeFormatMapping(format_id=1, type_id=4, type_name_id=2),
            ]
        )
        tags = {
            1: "red_hair",
            2: "blue_hair",
            3: "long_hair",
            4: "smile",
            5: "twin_drills",
            6: "red_hairs",
            7: "crimson_hair",
            8: "hatsune_miku",
            9: "blonde_hair",
        }
        session.add_all(Tag(tag_id=i, tag=t, source_tag=t) for i, t in tags.items())
        session.flush()
        for tag_id in (1, 2, 3, 4, 7, 9):
            session.add(
                TagStatus(
                    tag_id=tag_id,
                    format_id=1,
                    type_id=0,
                    alias=False,
                    preferred_tag_id=tag_id,
                    deprecated=tag_id == 7,
                )
            )
        session.add(TagStatus(tag_id=8, format_id=1, type_id=4, alias=False, preferred_tag_id=8))
        session.add(TagStatus(tag_id=6, format_id=1, type_id=0, alias=True, preferred_tag_id=1))
        # 旧タグ表から追加された unknown-format タグ (format_id=0 / type_id=0)
        session.add(TagStatus(tag_id=5, format_id=0, type_id=0, alias=False, preferred_tag_id=5))
        for tag_id, count in {1: 100, 2: 50, 3: 10, 4: 500, 7: 5, 8: 1000, 9: 70}.items():
            session.add(TagUsageCounts(tag_id=tag_id, format_id=1, count=count))
        session.add(TagTranslation(tag_id=5, language="ja", translation="ドリル"))
        session.commit()
    with engine.begin() as connection:
        raw = connection.connection.driver_connection
        assert isinstance(raw, sqlite3.Connection)
        for statement in _BUILDER_SCHEMA:
            raw.execute(statement)
        raw.executemany(
            "INSERT INTO TAG_CATEGORIES VALUES (?, ?, ?, ?, ?, ?)",
            [
                (cid, ns, parent, path[-1], len(path), json.dumps(path, ensure_ascii=False))
                for cid, ns, parent, path in _CATEGORIES
            ],
        )
        raw.executemany("INSERT INTO TAG_CATEGORY_MEMBERSHIPS VALUES (?, ?)", _MEMBERSHIPS)
    engine.dispose()


def _create_old_db(path: Path) -> None:
    """分類テーブルを持たない旧 DB。tag_id 4 は分類 DB の smile と無関係な cat。"""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                TagFormat(format_id=1, format_name="danbooru"),
                TagTypeName(type_name_id=1, type_name="general"),
                DatabaseMetadata(key="version", value="v-old"),
            ]
        )
        session.flush()
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add_all(
            [Tag(tag_id=4, tag="cat", source_tag="cat"), Tag(tag_id=100, tag="dog", source_tag="dog")]
        )
        session.flush()
        for tag_id in (4, 100):
            session.add(
                TagStatus(tag_id=tag_id, format_id=1, type_id=0, alias=False, preferred_tag_id=tag_id)
            )
        session.add(TagTranslation(tag_id=100, language="ja", translation="犬"))
        session.commit()
    engine.dispose()


def _create_user_db(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    UserOverlayBase.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(UserTag(tag_id=_USER_ID, tag="my_hair", source_tag="my_hair"))
        session.add(
            UserTagTranslationPatch(
                target_scope="base", target_tag_id=3, language="ja", translation="長い髪"
            )
        )
        session.commit()
    engine.dispose()


@pytest.fixture
def db_files(tmp_path: Path) -> dict[str, Path]:
    files = {
        "cat": tmp_path / "category.sqlite",
        "old": tmp_path / "old.sqlite",
        "user": tmp_path / "user.sqlite",
    }
    _create_category_db(files["cat"])
    _create_old_db(files["old"])
    _create_user_db(files["user"])
    return files


class _Env:
    def __init__(self) -> None:
        self.engines: dict[str, Engine] = {}
        self.statements: dict[str, list[str]] = {}

    def factory(self, name: str, path: Path) -> Callable[[], Session]:
        engine = create_engine(f"sqlite:///{path}")
        self.engines[name] = engine
        captured: list[str] = []
        self.statements[name] = captured
        event.listen(engine, "before_cursor_execute", lambda *args: captured.append(args[2]))
        return sessionmaker(bind=engine, autoflush=False)

    def clear(self) -> None:
        for captured in self.statements.values():
            captured.clear()


@pytest.fixture
def env(db_files: dict[str, Path]) -> Iterator[tuple[_Env, MergedTagReader]]:
    state = _Env()
    reader = MergedTagReader(
        # old を最優先にし、tag_id 4 の所有者を旧 DB の cat にする (ID 衝突)
        base_repo=[
            TagReader(state.factory("old", db_files["old"])),
            TagReader(state.factory("cat", db_files["cat"])),
        ],
        user_repo=OverlayTagReader(state.factory("user", db_files["user"])),
    )
    yield state, reader
    for engine in state.engines.values():
        engine.dispose()


@pytest.fixture
def cat_env(db_files: dict[str, Path]) -> Iterator[MergedTagReader]:
    """ID 衝突の無い構成 (分類 DB + user overlay)。"""
    state = _Env()
    yield MergedTagReader(
        base_repo=TagReader(state.factory("cat", db_files["cat"])),
        user_repo=OverlayTagReader(state.factory("user", db_files["user"])),
    )
    for engine in state.engines.values():
        engine.dispose()


def _ids(reader: MergedTagReader, **kwargs: object) -> list[int]:
    request = TagSearchRequest(**{"query": "", "resolve_preferred": False, **kwargs})
    return [item.tag_id for item in search_tags(reader, request).items]


def _category_ids(categories: list[TagCategory]) -> list[str]:
    return [category.category_id for category in categories]


# --- 項目 1: version と分類テーブルの有無 -------------------------------------


def test_database_info_reports_version_and_table_presence_per_base_db(env) -> None:
    _, reader = env
    assert get_tag_category_database_info(reader) == [
        TagCategoryDatabaseInfo(
            version="v-old", has_categories=False, category_count=0, membership_count=0
        ),
        TagCategoryDatabaseInfo(
            version="v-test-cat", has_categories=True, category_count=6, membership_count=9
        ),
    ]


# --- 項目 2: namespace / ノード / 親子 / path ---------------------------------


def test_list_categories_returns_typed_hierarchy_sorted_by_namespace_and_path(env) -> None:
    _, reader = env
    categories = list_tag_categories(reader)
    assert _category_ids(categories) == [
        "pg-hair",
        "pg-hair-style",
        "pg-hair-style-long",
        "pg-hair-color",
        "pm-character",
        "pm-face",
    ]
    long_hair = categories[2]
    assert long_hair == TagCategory(
        category_id="pg-hair-style-long",
        namespace=PG,
        parent_id="pg-hair-style",
        label="長髪",
        depth=3,
        path=["髪", "髪型", "長髪"],
    )
    assert categories[0].parent_id is None
    assert _category_ids(list_tag_categories(reader, namespace=PM)) == ["pm-character", "pm-face"]
    assert list_tag_categories(reader, namespace="missing") == []
    assert list_tag_category_namespaces(reader) == [PG, PM]


# --- 項目 3: タグの所属を一括取得 ---------------------------------------------


def test_batch_categories_resolve_per_db_and_skip_colliding_tag_ids(env) -> None:
    _, reader = env
    result = get_tag_categories_batch(reader, [1, 2, 4, 5, 9, 100, _USER_ID, 1])
    assert {tag_id: _category_ids(categories) for tag_id, categories in result.items()} == {
        1: ["pg-hair-style", "pg-hair-color"],  # 複数所属
        2: ["pg-hair-color"],
        5: ["pg-hair-style"],  # unknown-format の追加タグ
        # 4: 最優先 DB の tag_id 4 は cat。分類 DB の smile の分類を付けない
    }
    assert all(
        isinstance(category, TagCategory) for categories in result.values() for category in categories
    )
    assert get_tag_categories_batch(reader, []) == {}


def _limit_variables(engine: Engine, limit: int = 999) -> None:
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        assert isinstance(raw, sqlite3.Connection)
        raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, limit)


def test_batch_categories_sql_count_does_not_grow_with_tag_count(env) -> None:
    state, reader = env
    for engine in state.engines.values():
        _limit_variables(engine)

    def count(tag_ids: list[int]) -> int:
        state.clear()
        get_tag_categories_batch(reader, tag_ids)
        return sum(len(captured) for captured in state.statements.values())

    small = count([1])
    large_ids = list(range(1, 3 * TAG_ID_IN_CHUNK))
    assert count(large_ids) == small
    assert set(get_tag_categories_batch(reader, large_ids)) == {1, 2, 3, 5, 6, 7, 8}


# --- 項目 4 / 5: 分類条件・子孫・ページング・重複排除 ---------------------------


def test_category_filter_includes_descendants_by_default(env) -> None:
    _, reader = env
    assert _ids(reader, category_ids=["pg-hair"]) == _HAIR_ACTIVE
    assert _ids(reader, category_ids=["pg-hair"], include_descendant_categories=False) == []
    assert _ids(reader, category_ids=["pg-hair-style"]) == [1, 3, 5]
    assert _ids(reader, category_ids=["pg-hair-style"], include_descendant_categories=False) == [1, 5]
    # 複数指定は OR
    assert _ids(reader, category_ids=["pg-hair-style-long", "pm-face"]) == [3, 4]
    assert _ids(reader, category_ids=["missing"]) == []
    # 空リストは format_names 等と同じく条件なし
    assert _ids(reader, query="hair", category_ids=[]) == _ids(reader, query="hair")


def test_category_search_returns_categorized_row_not_colliding_tag(env) -> None:
    _, reader = env
    items = search_tags(reader, TagSearchRequest(query="", category_ids=["pm-face"])).items
    assert [(item.tag_id, item.tag) for item in items] == [(4, "smile")]


def test_category_filter_is_applied_before_paging_without_duplicates(env) -> None:
    _, reader = env
    pages = []
    for offset in (0, 2, 4, 6):
        result = search_tags(
            reader,
            TagSearchRequest(
                query="", category_ids=["pg-hair"], resolve_preferred=False, limit=2, offset=offset
            ),
        )
        assert result.total is None  # bounded 検索の契約
        pages.append([item.tag_id for item in result.items])
    assert pages == [[1, 2], [3, 5], [6, 7], []]
    unbounded = search_tags(
        reader, TagSearchRequest(query="", category_ids=["pg-hair"], resolve_preferred=False)
    )
    assert unbounded.total == len(_HAIR_ACTIVE)


def test_single_reader_applies_category_filter_in_sql_before_limit(db_files) -> None:
    state = _Env()
    reader = TagReader(state.factory("cat", db_files["cat"]))
    _limit_variables(state.engines["cat"])
    rows = reader.search_tags("", partial=True, category_ids=["pg-hair"], limit=2, offset=1)
    assert [row["tag_id"] for row in rows] == [2, 3]
    filtered = [
        sql
        for sql in state.statements["cat"]
        if "TAG_CATEGORY_MEMBERSHIPS" in sql and not sql.startswith("PRAGMA")
    ]
    assert len(filtered) == 1 and "LIMIT" in filtered[0].upper()
    # 入力が変数上限を超えても 1 文で解決する (json_each で 1 変数に束ねる)
    many = ["pg-hair-style-long", *[f"missing-{i}" for i in range(2 * TAG_ID_IN_CHUNK)]]
    assert [row["tag_id"] for row in reader.search_tags("", partial=True, category_ids=many)] == [3]
    state.engines["cat"].dispose()


@pytest.mark.parametrize(
    "filters",
    [
        {"format_names": ["danbooru"]},
        {"type_names": ["character"]},
        {"format_names": ["danbooru"], "type_names": ["general"]},
        {"min_usage": 60},
        {"max_usage": 60},
        {"include_aliases": False},
        {"include_deprecated": True},
        {"query": "hair"},
        {"query": "red_hair", "partial": False},
        {"query": "ドリル", "partial": False},
    ],
)
@pytest.mark.parametrize("categories", [["pg-hair"], ["pm-character", "pm-face"], ["pg-hair-color"]])
def test_category_filter_combines_with_existing_filters(cat_env, filters, categories) -> None:
    reader = cat_env
    expanded = {
        "pg-hair": {1, 2, 3, 5, 6, 7},
        "pg-hair-color": {1, 2, 6, 7},
        "pm-character": {8},
        "pm-face": {4},
    }
    allowed = set().union(*(expanded[c] for c in categories))
    without_category = _ids(reader, **filters)
    expected = [tag_id for tag_id in without_category if tag_id in allowed]
    assert _ids(reader, **filters, category_ids=categories) == expected
    # ページングは条件適用と重複排除の後
    paged = search_tags(
        reader,
        TagSearchRequest(
            **{"query": "", "resolve_preferred": False, **filters},
            category_ids=categories,
            limit=1,
            offset=1,
        ),
    )
    assert [item.tag_id for item in paged.items] == expected[1:2]
    assert paged.total is None


# --- 互換: unknown-format タグ・alias 解決・user overlay -----------------------


def test_unknown_format_tag_is_searchable_by_category(env) -> None:
    _, reader = env
    assert _ids(reader, query="twin_drills", partial=False, category_ids=["pg-hair-style"]) == [5]
    assert _ids(reader, query="ドリル", partial=False, category_ids=["pg-hair"]) == [5]


def test_alias_resolution_is_unchanged_by_category_filter(env) -> None:
    _, reader = env
    common = {"query": "red_hairs", "partial": False, "format_names": ["danbooru"]}
    plain = search_tags(reader, TagSearchRequest(**common))
    filtered = search_tags(reader, TagSearchRequest(**common, category_ids=["pg-hair-color"]))
    assert [item.model_dump() for item in filtered.items] == [item.model_dump() for item in plain.items]
    assert [item.tag for item in plain.items] == ["red_hair"]


def test_user_overlay_rows_follow_category_membership(env) -> None:
    _, reader = env
    # user 翻訳パッチ経由で一致した base タグも、所属で絞る
    assert _ids(reader, query="長い髪", partial=False, category_ids=["pg-hair-style-long"]) == [3]
    assert _ids(reader, query="長い髪", partial=False, category_ids=["pm-face"]) == []
    # user 独自タグは分類を持たない。条件なしの検索結果は変えない
    assert _USER_ID in _ids(reader, query="hair")
    assert _USER_ID not in _ids(reader, query="hair", category_ids=["pg-hair"])


def test_search_without_category_filter_issues_no_category_sql(env) -> None:
    state, reader = env
    state.clear()
    search_tags(reader, TagSearchRequest(query="hair", limit=5))
    search_tags(reader, TagSearchRequest(query="red_hair", partial=False))
    statements = [sql for captured in state.statements.values() for sql in captured]
    assert statements
    assert not [sql for sql in statements if "TAG_CATEGOR" in sql or "sqlite_master" in sql]


# --- 互換: 分類テーブルの無い旧 DB ---------------------------------------------


def test_old_database_keeps_search_and_translations_and_reports_empty_categories(db_files) -> None:
    state = _Env()
    reader = MergedTagReader(base_repo=TagReader(state.factory("old", db_files["old"])))
    assert [item.tag for item in search_tags(reader, TagSearchRequest(query="dog")).items] == ["dog"]
    assert reader.get_translations(100)[0].translation == "犬"
    assert list_tag_categories(reader) == []
    assert list_tag_category_namespaces(reader) == []
    assert get_tag_categories_batch(reader, [4, 100]) == {}
    assert get_tag_category_database_info(reader) == [
        TagCategoryDatabaseInfo(version="v-old", has_categories=False)
    ]
    assert _ids(reader, category_ids=["pg-hair"]) == []
    state.engines["old"].dispose()


def test_user_only_reader_has_no_categories(db_files) -> None:
    state = _Env()
    reader = MergedTagReader(base_repo=OverlayTagReader(state.factory("user", db_files["user"])))
    assert list_tag_categories(reader) == []
    assert get_tag_categories_batch(reader, [_USER_ID]) == {}
    assert _ids(reader, category_ids=["pg-hair"]) == []
    assert get_tag_category_database_info(reader) == [TagCategoryDatabaseInfo(has_categories=False)]
    state.engines["user"].dispose()


def test_merged_reader_satisfies_category_protocol(env) -> None:
    _, reader = env
    assert isinstance(reader, TagCategoryReaderProtocol)


def test_reader_without_category_support_keeps_default_search_contract() -> None:
    """分類条件なしの検索では、分類引数を知らない reader 実装にも引数を渡さない。"""

    class _FakeReader:
        def search_tags(
            self,
            keyword,
            *,
            partial,
            format_names,
            type_names,
            alias,
            deprecated,
            min_usage,
            max_usage,
            resolve_preferred,
            limit,
            offset,
        ):
            return []

    assert search_tags(_FakeReader(), TagSearchRequest(query="x")).items == []


# --- 互換: read_only 初期化 / runtime scope -----------------------------------


def _read_only_initialize(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", Mock(return_value=str(path)))
    monkeypatch.setattr(
        "genai_tag_db_tools.core_api.ensure_databases",
        Mock(side_effect=AssertionError("download forbidden")),
    )
    initialize_databases(
        sources=[DbSourceRef(repo_id="test/db", filename=path.name)],
        init_user_db=False,
        read_only=True,
    )


def test_read_only_initialization_reads_categories_without_writes(db_files, monkeypatch) -> None:
    path = db_files["cat"]
    before = path.read_bytes()
    files_before = sorted(p.name for p in path.parent.iterdir())
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        with database_runtime_scope():
            _read_only_initialize(monkeypatch, path)
            reader = get_tag_reader()
            assert len(list_tag_categories(reader)) == 6
            assert set(get_tag_categories_batch(reader, [1, 4])) == {1, 4}
            assert _ids(reader, category_ids=["pg-hair-style"]) == [1, 3, 5]
            assert get_tag_category_database_info(reader)[0].has_categories is True
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    assert not [
        sql
        for sql in statements
        if sql.split()[0].upper() in {"CREATE", "INSERT", "UPDATE", "DELETE", "ALTER"}
    ]
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == files_before


def test_runtime_scope_switch_and_nesting_do_not_leak_categories(db_files, monkeypatch) -> None:
    with database_runtime_scope():
        _read_only_initialize(monkeypatch, db_files["cat"])
        outer_reader = get_tag_reader()
        assert len(list_tag_categories(outer_reader)) == 6
        with database_runtime_scope():
            _read_only_initialize(monkeypatch, db_files["old"])
            inner_reader = get_tag_reader()
            assert list_tag_categories(inner_reader) == []
            assert get_tag_categories_batch(inner_reader, [4]) == {}
            assert _ids(inner_reader, category_ids=["pm-face"]) == []
            assert get_tag_category_database_info(inner_reader)[0].has_categories is False
        assert len(list_tag_categories(get_tag_reader())) == 6
        assert _ids(outer_reader, category_ids=["pm-face"]) == [4]
    with database_runtime_scope():
        _read_only_initialize(monkeypatch, db_files["old"])
        assert list_tag_categories(get_tag_reader()) == []


# --- 項目 6: CLI --------------------------------------------------------------


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> list[dict]:
    with database_runtime_scope():
        try:
            main(argv)
        finally:
            runtime.close_all()
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_cli_categories_lists_hierarchy_and_database_info(db_files, capsys) -> None:
    lines = _run_cli(
        [
            "categories",
            "--namespace",
            PM,
            "--base-db",
            str(db_files["old"]),
            "--base-db",
            str(db_files["cat"]),
        ],
        capsys,
    )
    assert [line["category_id"] for line in lines if line["kind"] == "item"] == ["pm-character", "pm-face"]
    assert lines[0] == {
        "kind": "item",
        "category_id": "pm-character",
        "namespace": PM,
        "parent_id": None,
        "label": "キャラ",
        "depth": 1,
        "path": ["キャラ"],
    }
    result = lines[-1]
    assert result["kind"] == "result" and result["ok"] is True and result["count"] == 2
    assert result["databases"] == [
        {"version": "v-old", "has_categories": False, "category_count": 0, "membership_count": 0},
        {"version": "v-test-cat", "has_categories": True, "category_count": 6, "membership_count": 9},
    ]


def test_cli_search_with_category_filter(db_files, capsys) -> None:
    base = ["--base-db", str(db_files["cat"])]
    lines = _run_cli(["search", "--query", "", "--category-id", "pg-hair-style", *base], capsys)
    assert [line["tag_id"] for line in lines if line["kind"] == "item"] == [1, 3, 5]
    lines = _run_cli(
        ["search", "--query", "", "--category-id", "pg-hair-style", "--no-category-descendants", *base],
        capsys,
    )
    assert [line["tag_id"] for line in lines if line["kind"] == "item"] == [1, 5]
    lines = _run_cli(
        ["search", "--query", "", "--category-id", "pm-face", "--category-id", "pm-character", *base],
        capsys,
    )
    assert [line["tag_id"] for line in lines if line["kind"] == "item"] == [4, 8]
    assert lines[-1] == {
        "kind": "result",
        "ok": True,
        "message": "search completed",
        "query": "",
        "count": 2,
        "total": None,
        "limit": 50,
        "offset": 0,
    }


def test_cli_search_output_keys_are_unchanged(db_files, capsys) -> None:
    lines = _run_cli(
        ["search", "--query", "red_hair", "--exact", "--base-db", str(db_files["cat"])], capsys
    )
    item = next(line for line in lines if line["kind"] == "item")
    assert set(item) == {
        "kind",
        "tag",
        "source_tag",
        "tag_id",
        "format_name",
        "type_id",
        "type_name",
        "alias",
        "deprecated",
        "usage_count",
        "translations",
        "format_statuses",
    }
    assert set(lines[-1]) == {"kind", "ok", "message", "query", "count", "total", "limit", "offset"}


def test_cli_help_documents_category_options(capsys) -> None:
    for argv in (["search", "--help"], ["categories", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--category-id" in out
    assert "--no-category-descendants" in out
    assert "--namespace" in out


def test_cli_describe_categories(capsys) -> None:
    main(["describe", "categories"])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["name"] == "categories"
    assert lines[0]["read_only"] is True
    assert lines[0]["input_model"] == "TagCategoryListRequest"
    assert lines[0]["output_model"] == "TagCategoryListResult"
