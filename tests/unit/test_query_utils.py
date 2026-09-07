from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db import query_utils
from genai_tag_db_tools.db.query_utils import (
    TagSearchPreloader,
    TagSearchQueryBuilder,
    TagSearchResultBuilder,
    sqlite_ascii_lower,
)
from genai_tag_db_tools.db.schema import (
    Base,
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
)

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


def _seed_minimal_schema(session: Session, total_tags: int) -> None:
    session.add(TagFormat(format_id=1, format_name="test"))
    session.add(TagTypeName(type_name_id=1, type_name="general"))
    session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
    for tag_id in range(1, total_tags + 1):
        tag_name = f"sample_{tag_id}"
        session.add(Tag(tag_id=tag_id, source_tag=tag_name, tag=tag_name))
        session.add(
            TagStatus(
                tag_id=tag_id,
                format_id=1,
                type_id=0,
                alias=False,
                preferred_tag_id=tag_id,
                deprecated=False,
            )
        )
    session.commit()


def test_initial_tag_ids_respects_limit_and_offset(session_factory: Callable[[], Session]) -> None:
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=20)
        builder = TagSearchQueryBuilder(session)
        ids = builder.initial_tag_ids("%sample_%", use_like=True, limit=5, offset=3)
        assert len(ids) == 5


def test_initial_tag_ids_exact_match_is_case_insensitive(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="blue_hair", tag="blue hair"))
        session.commit()
        builder = TagSearchQueryBuilder(session)
        ids = builder.initial_tag_ids("Blue Hair", use_like=False)

    assert ids == {1}


def test_initial_tag_ids_for_keywords_is_case_insensitive(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="blue_hair", tag="blue hair"))
        session.commit()
        builder = TagSearchQueryBuilder(session)
        result = builder.initial_tag_ids_for_keywords(["Blue Hair"])

    assert result == {"Blue Hair": {1}}


def test_exact_match_does_not_fold_stored_tag_values(
    session_factory: Callable[[], Session],
) -> None:
    """小文字キーは大文字混じりの格納値に一致しない (Issue #142)。

    `:d` (tag_id 25296) と `:D` (1087135) のように、大小のみが異なる格納値が
    別タグを指す (base DB 実測で 34 組)。格納値を畳んで照合すると別タグを拾う。
    """
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="Blue_Hair", tag="Blue Hair"))
        session.add(Tag(tag_id=2, source_tag="blue_hair", tag="blue hair"))
        session.commit()
        builder = TagSearchQueryBuilder(session)

        # 格納値が小文字の行は、キーを畳んで index で引ける (従来どおり)
        assert builder.initial_tag_ids_for_keywords(["blue hair"]) == {"blue hair": {2}}
        assert builder.initial_tag_ids("blue hair", use_like=False) == {2}

        # 表記どおりに打てば大文字混じりの行も引ける
        assert builder.initial_tag_ids("Blue Hair", use_like=False) == {1, 2}


def test_exact_match_case_variant_tags_do_not_collide(
    session_factory: Callable[[], Session],
) -> None:
    """大小のみ異なる格納タグが別 tag_id の場合、取り違えない (Issue #142)。"""
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag=":D", tag=":D"))
        session.add(Tag(tag_id=2, source_tag=":d", tag=":d"))
        session.commit()
        builder = TagSearchQueryBuilder(session)

        # 小文字キーは小文字の行だけを引く
        assert builder.initial_tag_ids(":d", use_like=False) == {2}
        # 大文字キーは自身 + 畳んだキーの行を引く (canonical が小文字である前提を保つ)
        assert builder.initial_tag_ids(":D", use_like=False) == {1, 2}


def test_translation_match_is_case_sensitive(
    session_factory: Callable[[], Session],
) -> None:
    """翻訳は大文字小文字を区別して照合する (Issue #139)。

    `Aiki` と `aiki` のように大小のみが異なる翻訳が別タグを指すため、
    小文字化した照合は誤った tag_id を返しうる。
    """
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="cat", tag="cat"))
        session.add(TagTranslation(translation_id=1, tag_id=1, language="en", translation="Cat Ears"))
        session.add(TagTranslation(translation_id=2, tag_id=1, language="ja", translation="猫耳"))
        session.commit()
        builder = TagSearchQueryBuilder(session)

        # 表記どおりなら一致する (非 ASCII はそもそも大小の概念がないので常に一致)
        assert builder.initial_tag_ids_for_keywords(["Cat Ears", "猫耳"]) == {
            "Cat Ears": {1},
            "猫耳": {1},
        }
        assert builder.initial_tag_ids("Cat Ears", use_like=False) == {1}

        # 小文字化した入力は大文字混じり翻訳に一致しない
        assert builder.initial_tag_ids_for_keywords(["cat ears"]) == {}
        assert builder.initial_tag_ids("cat ears", use_like=False) == set()


def test_translation_case_variants_resolve_to_distinct_tags(
    session_factory: Callable[[], Session],
) -> None:
    """大小のみ異なる翻訳が別タグを指す場合、取り違えない (Issue #139)。"""
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="aiki_upper", tag="aiki upper"))
        session.add(Tag(tag_id=2, source_tag="aiki_lower", tag="aiki lower"))
        session.add(TagTranslation(translation_id=1, tag_id=1, language="en", translation="Aiki"))
        session.add(TagTranslation(translation_id=2, tag_id=2, language="en", translation="aiki"))
        session.commit()
        builder = TagSearchQueryBuilder(session)

        assert builder.initial_tag_ids_for_keywords(["Aiki"]) == {"Aiki": {1}}
        assert builder.initial_tag_ids_for_keywords(["aiki"]) == {"aiki": {2}}
        assert builder.initial_tag_ids("Aiki", use_like=False) == {1}
        assert builder.initial_tag_ids("aiki", use_like=False) == {2}


def test_sqlite_ascii_lower_folds_ascii_only() -> None:
    """SQLite lower()/NOCASE と同じく ASCII のみ折り畳み、非 ASCII は保持する。"""
    assert sqlite_ascii_lower("Blue Hair") == "blue hair"
    assert sqlite_ascii_lower("CAFÉ") == "cafÉ"
    assert sqlite_ascii_lower("猫耳") == "猫耳"


def test_filtered_tag_ids_applies_filters_before_limit(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=6)
        session.add(TagTypeName(type_name_id=2, type_name="character"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=1, type_name_id=2))
        for tag_id in range(1, 4):
            status = session.get(TagStatus, (tag_id, 1))
            assert status is not None
            status.type_id = 1
            session.add(TagUsageCounts(tag_id=tag_id, format_id=1, count=1))
        for tag_id in range(4, 7):
            session.add(TagUsageCounts(tag_id=tag_id, format_id=1, count=100))
        session.commit()

        builder = TagSearchQueryBuilder(session)
        ids, format_id = builder.filtered_tag_ids(
            "%sample_%",
            use_like=True,
            format_names=["test"],
            type_names=["general"],
            min_usage=10,
            limit=2,
        )

    assert sorted(ids) == [4, 5]
    assert format_id == 1


def test_filtered_tag_ids_filters_alias_and_deprecated_before_limit(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=5)
        first = session.get(TagStatus, (1, 1))
        second = session.get(TagStatus, (2, 1))
        assert first is not None
        assert second is not None
        first.alias = True
        first.preferred_tag_id = 2
        second.deprecated = True
        session.commit()

        builder = TagSearchQueryBuilder(session)
        ids, _ = builder.filtered_tag_ids(
            "%sample_%",
            use_like=True,
            format_names=["test"],
            alias=False,
            deprecated=False,
            limit=2,
        )

    assert sorted(ids) == [3, 4]


def test_filtered_tag_ids_treats_all_as_unfiltered(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=4)
        builder = TagSearchQueryBuilder(session)
        ids, format_id = builder.filtered_tag_ids(
            "%sample_%",
            use_like=True,
            format_names=["all"],
            type_names=["all"],
            limit=2,
        )

    assert sorted(ids) == [1, 2]
    # "all"/no concrete format is signalled by None so the sentinel "unknown"
    # format (format_id == 0) is not mistaken for "no active format".
    assert format_id is None


def test_filtered_tag_ids_unknown_format_returns_id_zero_not_none(
    session_factory: Callable[[], Session],
) -> None:
    """Requesting the sentinel "unknown" format must yield format_id == 0.

    Regression for issue #63: format_id 0 (the real "unknown" format) used to be
    indistinguishable from the "no active format" sentinel, which blanked the
    top-level type fields in search output.
    """
    with session_factory() as session:
        session.add(TagFormat(format_id=0, format_name="unknown"))
        session.add(TagTypeName(type_name_id=0, type_name="unknown"))
        session.add(TagTypeFormatMapping(format_id=0, type_id=0, type_name_id=0))
        session.add(Tag(tag_id=1, source_tag="bad_id", tag="bad id"))
        session.add(
            TagStatus(
                tag_id=1,
                format_id=0,
                type_id=0,
                alias=False,
                preferred_tag_id=1,
                deprecated=False,
            )
        )
        session.commit()

        builder = TagSearchQueryBuilder(session)
        ids, format_id = builder.filtered_tag_ids(
            "%bad%",
            use_like=True,
            format_names=["unknown"],
        )

        assert sorted(ids) == [1]
        assert format_id == 0

        preloaded = TagSearchPreloader(session).load(ids)
        result_builder = TagSearchResultBuilder(format_id=format_id, resolve_preferred=False)
        row = result_builder.build_row(1, preloaded)

    assert row is not None
    # Top-level fields must reflect the unknown-format status, matching
    # format_statuses["unknown"], rather than being blanked out.
    assert row["type_name"] == "unknown"
    assert row["type_id"] == 0
    assert row["format_statuses"]["unknown"]["type_name"] == "unknown"


def test_filtered_tag_ids_negative_status_filters_keep_statusless_tags(
    session_factory: Callable[[], Session],
) -> None:
    with session_factory() as session:
        session.add(Tag(tag_id=1, source_tag="sample_statusless", tag="sample_statusless"))
        session.add(TagFormat(format_id=1, format_name="test"))
        session.add(TagTypeName(type_name_id=1, type_name="general"))
        session.add(TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1))
        session.add(Tag(tag_id=2, source_tag="sample_active", tag="sample_active"))
        session.add(
            TagStatus(
                tag_id=2,
                format_id=1,
                type_id=0,
                alias=False,
                preferred_tag_id=2,
                deprecated=False,
            )
        )
        session.add(Tag(tag_id=3, source_tag="sample_deprecated", tag="sample_deprecated"))
        session.add(
            TagStatus(
                tag_id=3,
                format_id=1,
                type_id=0,
                alias=False,
                preferred_tag_id=3,
                deprecated=True,
            )
        )
        session.commit()

        builder = TagSearchQueryBuilder(session)
        ids, _ = builder.filtered_tag_ids(
            "%sample_%",
            use_like=True,
            alias=False,
            deprecated=False,
        )

    assert sorted(ids) == [1, 2]


def test_preloader_load_handles_large_id_sets_with_chunking(
    session_factory: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLITE_IN_LIMIT を小さい値に上書きして、チャンク分割が正しく動作することを確認する。"""
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=1200)
        preloader = TagSearchPreloader(session)
        monkeypatch.setattr(preloader, "SQLITE_IN_LIMIT", 200)

        preloaded = preloader.load(set(range(1, 1201)))

        assert len(preloaded.tags_by_id) == 1200
        assert len(preloaded.statuses_by_tag_id) == 1200


def test_preloader_load_returns_empty_for_empty_input(session_factory: Callable[[], Session]) -> None:
    with session_factory() as session:
        preloader = TagSearchPreloader(session)
        preloaded = preloader.load(set())

    assert preloaded.tags_by_id == {}
    assert preloaded.statuses_by_tag_id == {}


def _seed_second_format(session: Session, tag_ids: range, format_id: int) -> None:
    """既存タグに別 format の TAG_STATUS 行を追加する (format 絞り込み検証用)。"""
    session.add(TagFormat(format_id=format_id, format_name=f"format_{format_id}"))
    session.add(TagTypeFormatMapping(format_id=format_id, type_id=0, type_name_id=1))
    for tag_id in tag_ids:
        session.add(
            TagStatus(
                tag_id=tag_id,
                format_id=format_id,
                type_id=0,
                alias=False,
                preferred_tag_id=tag_id,
                deprecated=False,
            )
        )
    session.commit()


def test_apply_format_filter_returns_only_requested_tag_ids_present_in_format(
    session_factory: Callable[[], Session],
) -> None:
    """format に属する tag_id だけが残り、format 外の tag_id は落ちる。"""
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=50)
        # 1..50 は format 1。31..50 のみ format 2 にも属する。
        _seed_second_format(session, range(31, 51), format_id=2)
        builder = TagSearchQueryBuilder(session)

        ids, format_id = builder.apply_format_filter({10, 35, 40}, "format_2")

    assert ids == {35, 40}
    assert format_id == 2


def test_apply_format_filter_does_not_scan_rows_outside_requested_tag_ids(
    session_factory: Callable[[], Session],
) -> None:
    """絞り込みは SQL 側で行い、format 全行を materialize しない (Issue #146)。

    現行実装は `WHERE format_id = ?` だけで該当 format の TAG_STATUS 全行を読むため、
    入力 tag_ids の件数に依らず一定のスキャンコストが乗る。tag_id 述語が SQL に
    渡っていることを、発行された文と bind パラメータで検証する。
    """
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=500)
        engine = session.get_bind()
        statements: list[tuple[str, object]] = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append((statement, parameters))

        event.listen(engine, "before_cursor_execute", capture)
        try:
            builder = TagSearchQueryBuilder(session)
            ids, _ = builder.apply_format_filter({1, 2, 3}, "test")
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert ids == {1, 2, 3}

    status_statements = [
        (sql, params) for sql, params in statements if "TAG_STATUS" in sql and "SELECT" in sql.upper()
    ]
    assert status_statements, "TAG_STATUS への SELECT が発行されていない"
    for sql, params in status_statements:
        assert "tag_id IN" in sql, f"tag_id 述語が SQL に渡っていない (全行スキャン): {sql}"
        # bind パラメータに要求した tag_id が含まれ、全 500 件を読んでいないこと
        assert params, f"bind パラメータが空: {sql}"


def test_apply_format_filter_handles_id_sets_over_sqlite_variable_limit(
    session_factory: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite の IN 句変数上限を超える tag_ids でもチャンク分割して正しく返す。"""
    monkeypatch.setattr(query_utils, "TAG_ID_IN_CHUNK", 200)
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=1200)
        builder = TagSearchQueryBuilder(session)

        engine = session.get_bind()
        status_selects = 0

        def capture(conn, cursor, statement, parameters, context, executemany):
            nonlocal status_selects
            if "TAG_STATUS" in statement and statement.upper().startswith("SELECT"):
                status_selects += 1

        event.listen(engine, "before_cursor_execute", capture)
        try:
            # format に存在しない ID (2001..2100) を混ぜ、絞り込みが効くことも確認する
            requested = set(range(1, 1201)) | set(range(2001, 2101))
            ids, format_id = builder.apply_format_filter(requested, "test")
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert ids == set(range(1, 1201))
    assert format_id == 1
    # 1300 件 / チャンク 200 → 7 文に分割される (1 文にまとめず bind 上限を守る)
    assert status_selects == 7


def test_apply_format_filter_returns_input_untouched_for_all_or_missing_format(
    session_factory: Callable[[], Session],
) -> None:
    """format 未指定/"all" は素通し、未知 format は空集合 (現行挙動の維持)。"""
    with session_factory() as session:
        _seed_minimal_schema(session, total_tags=10)
        builder = TagSearchQueryBuilder(session)

        assert builder.apply_format_filter({1, 2}, None) == ({1, 2}, None)
        assert builder.apply_format_filter({1, 2}, "all") == ({1, 2}, None)
        assert builder.apply_format_filter({1, 2}, "no_such_format") == (set(), None)
        assert builder.apply_format_filter(set(), "test") == (set(), 1)
