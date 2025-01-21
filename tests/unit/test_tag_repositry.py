import pytest
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from genai_tag_db_tools.data.database_schema import Base
from genai_tag_db_tools.data.database_schema import(
        Tag,
        TagStatus,
        TagTranslation,
        TagFormat, TagTypeName,
        TagTypeFormatMapping,
        TagUsageCounts
    )
from genai_tag_db_tools.data.tag_repository import TagRepository

# =============================================================================
# 1) テスト用インメモリDBのフィクスチャ
# =============================================================================
@pytest.fixture(scope="function")
def tag_repository(db_session: Session):
    """
    TagRepository を返すフィクスチャ。
    - テーブル定義をCREATEし
    - TagRepository の session_factory を db_session に差し替える
    """
    # テスト用にテーブルを作成
    Base.metadata.create_all(bind=db_session.bind)

    # リポジトリを生成
    repository = TagRepository()

    # session_factory をオーバーライド
    from sqlalchemy.orm import sessionmaker
    session_factory_override = sessionmaker(bind=db_session.bind)
    repository.session_factory = session_factory_override

    yield repository

    # teardown（必要なら書く）
    # 今回は functionスコープで db_session が切れるときにロールバックされるため特になし
    Base.metadata.drop_all(bind=db_session.bind)

# =============================================================================
# 2) 正常系テスト
#=============================================================================

def test_create_tag(tag_repository):
    """
    create_tag の基本動作テスト。
    """
    tag_id = tag_repository.create_tag(source_tag="source_1", tag="mytag")
    assert tag_id == 1  # 初回INSERTなので、tag_id=1 になるはず

    # 再度同じタグを登録 → 既存を返す
    same_id = tag_repository.create_tag("source_2", "mytag")
    assert same_id == 1  # 既存IDが返る

def test_get_tag_id_by_name(tag_repository):
    """
    get_tag_id_by_name のテスト。
    """
    # 事前にタグ登録
    t1 = tag_repository.create_tag("source_a", "apple")
    t2 = tag_repository.create_tag("source_b", "banana")

    # 完全一致検索
    found = tag_repository.get_tag_id_by_name("banana", partial=False)
    assert found == t2

    # 見つからなければ None
    notfound = tag_repository.get_tag_id_by_name("unknown_tag", partial=False)
    assert notfound is None

    # 部分一致テスト (例: "*an*" → "%an%")
    found_partial = tag_repository.get_tag_id_by_name("ban*", partial=True)
    assert found_partial == t2

def test_update_tag(tag_repository):
    """
    update_tag のテスト。
    """
    tag_id = tag_repository.create_tag("src_before", "before")

    # 更新
    tag_repository.update_tag(tag_id, source_tag="src_after", tag="after")

    updated = tag_repository.get_tag_by_id(tag_id)
    assert updated.source_tag == "src_after"
    assert updated.tag == "after"

def test_delete_tag(tag_repository):
    """
    delete_tag のテスト。
    """
    tag_id = tag_repository.create_tag("delete_src", "delete_me")
    tag_repository.delete_tag(tag_id)
    # 削除されたので None になるはず
    deleted = tag_repository.get_tag_by_id(tag_id)
    assert deleted is None

def test_bulk_insert_tags(tag_repository):
    """
    bulk_insert_tags のテスト。
    Polarsがインストールされていない場合は適宜Mockやテストスキップ推奨。
    """
    try:
        import polars as pl
    except ImportError:
        pytest.skip("polarsがインストールされていないためスキップ")

    df = pl.DataFrame(
        {
            "source_tag": ["src1", "src2", "src3"],
            "tag": ["foo", "bar", "baz"]
        }
    )
    tag_repository.bulk_insert_tags(df)

    # 登録確認
    t_foo = tag_repository.get_tag_id_by_name("foo")
    t_bar = tag_repository.get_tag_id_by_name("bar")
    t_baz = tag_repository.get_tag_id_by_name("baz")

    assert t_foo is not None
    assert t_bar is not None
    assert t_baz is not None

def test_get_format_id(tag_repository):
    """
    get_format_id のテスト。
    存在しないformat_nameの場合は0を返すことを確認。
    """
    with tag_repository.session_factory() as session:
        session.add(TagFormat(format_id=10, format_name="test_format"))
        session.commit()

    # 正常系: 存在するformat_nameの場合はIDを返す
    fid = tag_repository.get_format_id("test_format")
    assert fid == 10

    # 異常系: 存在しないformat_nameの場合は 0 を返す
    fid_none = tag_repository.get_format_id("unknown")
    assert fid_none == 0

def test_get_tag_formats(tag_repository):
    """
    get_tag_formats のテスト。

    以下を確認:
    1. フォーマット名が正しく取得できる
    2. 重複が排除される（DISTINCTの動作確認）
    """
    with tag_repository.session_factory() as session:
        # テストデータ作成（重複を含まない）
        formats = [
            TagFormat(format_id=101, format_name="test_format1"),
            TagFormat(format_id=102, format_name="test_format2"),
            TagFormat(format_id=103, format_name="test_format3"),
        ]
        session.add_all(formats)
        session.commit()

    # フォーマット一覧を取得
    format_list = tag_repository.get_tag_formats()

    # 検証
    # マスターデータ（unknown, danbooru, e621, derpibooru）と
    # テストで追加した3つ（test_format1, test_format2, test_format3）の合計7つ
    assert len(format_list) == 7
    # テストで追加したフォーマットが含まれていることを確認
    assert "test_format1" in format_list
    assert "test_format2" in format_list
    assert "test_format3" in format_list

def test_update_tag_status(tag_repository):
    """
    update_tag_status のテスト。
    既存レコードとの重複などによって DB 側で制約違反が起きた場合、
    リポジトリがキャッチして ValueError を投げ直すことを確認する。
    """
    # 1) 事前に Tag / Format を用意
    with tag_repository.session_factory() as session:
        t = Tag(tag_id=5, tag="test_tag", source_tag="test_source")
        f = TagFormat(format_id=20, format_name="test_format")
        session.add_all([t, f])
        session.commit()

    # 2) 新規登録 → OK (DB制約違反は発生しない)
    tag_repository.update_tag_status(tag_id=5, format_id=20, type_id=None, alias=False, preferred_tag_id=5)

    # 3) もう一度同じ (tag_id=5, format_id=20) で登録
    #    → DBのPK/UNIQUE制約が発動して IntegrityError → リポジトリで ValueError に変換
    with pytest.raises(ValueError) as exc_info:
        tag_repository.update_tag_status(tag_id=5, format_id=20, type_id=None, alias=False, preferred_tag_id=5)

    # 必要ならメッセージ内容をチェック
    assert "データベース操作に失敗しました:" in str(exc_info.value)

def test_get_usage_count_and_update_usage_count(tag_repository):
    """
    usage_count の取得・更新テスト。
    """
    with tag_repository.session_factory() as session:
        t = Tag(tag_id=10, tag="test_tag2", source_tag="test_src2")
        f = TagFormat(format_id=30, format_name="test_format2")
        session.add_all([t, f])
        session.commit()

    # 初期は存在しない→None
    assert tag_repository.get_usage_count(10, 30) is None

    # update_usage_count → 新規作成
    tag_repository.update_usage_count(10, 30, 7)
    assert tag_repository.get_usage_count(10, 30) == 7

    # update_usage_count → 上書き
    tag_repository.update_usage_count(10, 30, 15)
    assert tag_repository.get_usage_count(10, 30) == 15

def test_add_or_update_translation(tag_repository):
    """
    翻訳テーブルへの追加テスト。
    """
    with tag_repository.session_factory() as session:
        t = Tag(tag_id=50, tag="trans_test", source_tag="trans_src")
        session.add(t)
        session.commit()

    # 1) 新規作成
    tag_repository.add_or_update_translation(50, "en", "TestTag")
    translations = tag_repository.get_translations(50)
    assert len(translations) == 1
    assert translations[0].translation == "TestTag"

    # 2) 重複挿入 → スキップ
    tag_repository.add_or_update_translation(50, "en", "TestTag")
    translations = tag_repository.get_translations(50)
    assert len(translations) == 1  # 変わらない

def test_find_preferred_tag(tag_repository):
    """
    find_preferred_tag のテスト。
    """
    with tag_repository.session_factory() as session:
        # catタグ (tag_id=201) を作成
        t_cat = Tag(tag_id=201, tag="cat", source_tag="cat_src")

        # 999番のタグ (推奨タグとして存在する) を作成
        t_preferred = Tag(tag_id=999, tag="preferred_cat", source_tag="cat_src")

        # フォーマット 60
        f_db = TagFormat(format_id=60, format_name="db")

        session.add_all([t_cat, t_preferred, f_db])
        session.commit()  # コミットし、IDを確定させる

    # ここでTagStatusをINSERT
    with tag_repository.session_factory() as session:
        status_cat = TagStatus(
            tag_id=201,
            format_id=60,
            alias=True,
            preferred_tag_id=999
        )
        session.add(status_cat)
        session.commit()

        preferred_id = tag_repository.find_preferred_tag(tag_id=201, format_id=60)
        assert preferred_id == 999

        # 存在しなければNone
        none_pref = tag_repository.find_preferred_tag(tag_id=999, format_id=60)
        assert none_pref is None

def test_search_tag_ids_with_translation(tag_repository):
    """
    search_tag_ids のテスト。
    Tag.tag, Tag.source_tag, および TagTranslation.translation カラムを検索し、
    部分一致/完全一致/ワイルドカードで該当する tag_id を取得できるか検証する。
    """
    with tag_repository.session_factory() as session:
        # ---------------------------
        # 1) TagをINSERT → IDを取得
        # ---------------------------
        t1 = Tag(tag="cat", source_tag="cat_src")
        t2 = Tag(tag="dog", source_tag="dog_src")
        session.add_all([t1, t2])
        session.commit()
        # コミット or flush により t1.tag_id, t2.tag_id が確定

        # IDを変数に保持しておく (テスト後で使う)
        tid_cat = t1.tag_id
        tid_dog = t2.tag_id

        # ---------------------------
        # 2) TagTranslationをINSERT
        # ---------------------------
        tr1 = TagTranslation(tag_id=tid_cat, language="en", translation="feline")
        tr2 = TagTranslation(tag_id=tid_dog, language="en", translation="doggy")
        tr3 = TagTranslation(tag_id=tid_cat, language="jp", translation="猫")
        session.add_all([tr1, tr2, tr3])
        session.commit()
        # コミット後にDBに反映された状態

        # ---------------------------
        # 3) テスト対象メソッドの呼び出し & アサーション
        # ---------------------------

        # 完全一致 (partial=False)
        result = tag_repository.search_tag_ids("feline", partial=False)
        assert len(result) == 1
        assert tid_cat in result  # t1.tag_id ではなく変数tid_catを比較

        # 部分一致 (partial=True) → "fel*" → "fel%"
        result_partial = tag_repository.search_tag_ids("fel*", partial=True)
        assert len(result_partial) == 1
        assert tid_cat in result_partial

        # ワイルドカード "*猫*" → "%猫%"
        result_jp = tag_repository.search_tag_ids("*猫*", partial=True)
        assert len(result_jp) == 1
        assert tid_cat in result_jp

        # 存在しない翻訳
        none_result = tag_repository.search_tag_ids("unknown", partial=False)
        assert len(none_result) == 0

        # タグ名での検索も可能
        result_tag = tag_repository.search_tag_ids("cat", partial=False)
        assert len(result_tag) == 1
        assert tid_cat in result_tag

        # source_tagでの検索も可能
        result_source = tag_repository.search_tag_ids("cat_src", partial=False)
        assert len(result_source) == 1
        assert tid_cat in result_source


def test_search_tag_ids_by_usage_count_range(tag_repository):
    """
    search_tag_ids_by_usage_count_range のテスト。
    min_count, max_count, format_id によるフィルタが正しく機能するか確認する。
    """
    with tag_repository.session_factory() as session:
        # 1) Tag + Formatを作る
        tag_a = Tag(tag="alpha", source_tag="A_src")
        tag_b = Tag(tag="beta", source_tag="B_src")
        fmt_1 = TagFormat(format_id=101, format_name="fmt101")
        fmt_2 = TagFormat(format_id=102, format_name="fmt102")
        session.add_all([tag_a, tag_b, fmt_1, fmt_2])
        session.commit()

        # コミット後: tag_a.tag_id, tag_b.tag_id が確定
        tid_a = tag_a.tag_id
        tid_b = tag_b.tag_id
        # フォーマットIDはDB上で指定済み(101, 102)なのでそのまま利用可

        # 2) UsageCountsを作成
        uc_a1 = TagUsageCounts(tag_id=tid_a, format_id=101, count=10)
        uc_a2 = TagUsageCounts(tag_id=tid_a, format_id=102, count=50)
        uc_b1 = TagUsageCounts(tag_id=tid_b, format_id=101, count=100)
        session.add_all([uc_a1, uc_a2, uc_b1])
        session.commit()

        # --- ここからテスト本体 ---
        # min_count=0, max_count=60 → tag_a(10,50), tag_b(100)のうち
        #  count <=60 に該当するのは10と50のみ → tag_a のみ
        res_1 = tag_repository.search_tag_ids_by_usage_count_range(min_count=0, max_count=60)
        assert len(res_1) == 1
        assert tid_a in res_1

        # format_id=101 だけに絞り込む
        #  - tag_a(10), tag_b(100)
        #  - min_count=50 → 10はNG, 100はOK → tag_b
        res_2 = tag_repository.search_tag_ids_by_usage_count_range(min_count=50, format_id=101)
        assert len(res_2) == 1
        assert tid_b in res_2

        # max_count=10, format_id=101
        #  - tag_a(10), tag_b(100)
        #  - count<=10 → tag_aのみ
        res_3 = tag_repository.search_tag_ids_by_usage_count_range(max_count=10, format_id=101)
        assert len(res_3) == 1
        assert tid_a in res_3

        # 該当なしのパターン
        res_4 = tag_repository.search_tag_ids_by_usage_count_range(min_count=999)
        assert len(res_4) == 0


import pytest
from unittest.mock import PropertyMock

def test_search_tag_ids_by_alias(tag_repository):
    with tag_repository.session_factory() as session:
        # 1) Tag, Format
        tag_x = Tag(tag="X", source_tag="X_src")
        tag_y = Tag(tag="Y", source_tag="Y_src")
        fmt_10 = TagFormat(format_id=10, format_name="fmt10")
        session.add_all([tag_x, tag_y, fmt_10])
        session.commit()

        tid_x = tag_x.tag_id
        tid_y = tag_y.tag_id

        # 2) TagStatus:
        # alias=True の場合は別のタグを参照
        # alias=False の場合は自分自身を参照
        ts_x = TagStatus(tag_id=tid_x, format_id=10, alias=True, preferred_tag_id=tid_y)
        ts_y = TagStatus(tag_id=tid_y, format_id=10, alias=False, preferred_tag_id=tid_y)
        session.add_all([ts_x, ts_y])
        session.commit()

    # --- テスト本体: 検索結果を確認 ---
    res_true = tag_repository.search_tag_ids_by_alias(alias=True, format_id=10)
    assert len(res_true) == 1
    assert tid_x in res_true

    res_false = tag_repository.search_tag_ids_by_alias(alias=False, format_id=10)
    assert len(res_false) == 1
    assert tid_y in res_false

    # format_id を指定しない → 全タグが対象
    res_all_true = tag_repository.search_tag_ids_by_alias(alias=True)
    assert len(res_all_true) == 1
    assert tid_x in res_all_true

    res_all_false = tag_repository.search_tag_ids_by_alias(alias=False)
    assert len(res_all_false) == 1
    assert tid_y in res_all_false


def test_search_tag_ids_by_type_name(tag_repository):
    """
    search_tag_ids_by_type_name のテスト。
    type_name から type_id を取得し、TagStatus.type_id と一致するタグを検索する。
    format_id で追加絞り込みも可能かどうか確認。

    注: preferred_tag_id の NOT NULL 制約を使っている場合は None ではNGかもしれない。
    """
    with tag_repository.session_factory() as session:
        # 1) Tag, Format, TypeName
        tag_m = Tag(tag="M", source_tag="M_src")
        tag_n = Tag(tag="N", source_tag="N_src")
        fmt_2 = TagFormat(format_id=301, format_name="fmt2")
        ttype_char = TagTypeName(type_name_id=100, type_name="Character")
        ttype_obj = TagTypeName(type_name_id=101, type_name="Object")
        session.add_all([tag_m, tag_n, fmt_2, ttype_char, ttype_obj])
        session.commit()

        # 2) TagTypeFormatMapping
        mapping_char = TagTypeFormatMapping(format_id=301, type_id=100, type_name_id=100)
        mapping_obj = TagTypeFormatMapping(format_id=301, type_id=101, type_name_id=101)
        session.add_all([mapping_char, mapping_obj])
        session.commit()

        tid_m = tag_m.tag_id
        tid_n = tag_n.tag_id

        # 3) TagStatus
        status_m = TagStatus(
            tag_id=tid_m, format_id=301, type_id=100,
            alias=False, preferred_tag_id=tid_m
        )
        status_n = TagStatus(
            tag_id=tid_n, format_id=301, type_id=101,
            alias=False, preferred_tag_id=tid_n
        )
        session.add_all([status_m, status_n])
        session.commit()

    # --- テスト本体 ---
    # type_name="Character" → type_name_id=100 → tag_m
    res_char = tag_repository.search_tag_ids_by_type_name("Character", format_id=301)
    assert len(res_char) == 1
    assert tid_m in res_char

    # type_name="Object" → type_name_id=101 → tag_n
    res_obj = tag_repository.search_tag_ids_by_type_name("Object", format_id=301)
    assert len(res_obj) == 1
    assert tid_n in res_obj

    # 存在しない type_name → 空
    res_none = tag_repository.search_tag_ids_by_type_name("NonExistent")
    assert len(res_none) == 0


def test_search_tag_ids_by_format_name(tag_repository):
    """
    search_tag_ids_by_format_name のテスト。
    事前に format_name と format_id を紐付けて TagStatus を作成しておき、
    該当する tag_id を取得できるか確認する。

    注: preferred_tag_id の NOT NULL を許容しない場合は None がNGかもしれない。
    """
    with tag_repository.session_factory() as session:
        # 1) Tag
        tag_r = Tag(tag="R", source_tag="R_src")
        tag_s = Tag(tag="S", source_tag="S_src")
        session.add_all([tag_r, tag_s])
        session.commit()

        tid_r = tag_r.tag_id
        tid_s = tag_s.tag_id

        # 2) TagFormat
        fmt_aaa = TagFormat(format_id=200, format_name="aaa")
        fmt_bbb = TagFormat(format_id=300, format_name="bbb")
        session.add_all([fmt_aaa, fmt_bbb])
        session.commit()
        # 200, 300 はそのまま使える

        # 3) TagStatus (tag_r→200, tag_s→300)
        ts_r = TagStatus(tag_id=tid_r, format_id=200, alias=False, preferred_tag_id=tid_r)
        ts_s = TagStatus(tag_id=tid_s, format_id=300, alias=False, preferred_tag_id=tid_s)
        session.add_all([ts_r, ts_s])
        session.commit()

    # --- テスト本体 ---
    # format_name="aaa" → format_id=200 → tag_r
    res_aaa = tag_repository.search_tag_ids_by_format_name("aaa")
    assert len(res_aaa) == 1
    assert tid_r in res_aaa

    # format_name="bbb" → format_id=300 → tag_s
    res_bbb = tag_repository.search_tag_ids_by_format_name("bbb")
    assert len(res_bbb) == 1
    assert tid_s in res_bbb

    # 存在しないフォーマット名
    res_none = tag_repository.search_tag_ids_by_format_name("zzz")
    assert len(res_none) == 0


# =============================================================================
# 3) 異常系テストの追加
# =============================================================================

def test_create_tag_with_invalid_arguments(tag_repository):
    """
    create_tag の異常系テスト例。
    実際にリポジトリ側でNone禁止チェックやValueErrorが起きる。
    """
    # tag が None
    with pytest.raises(ValueError):
        tag_repository.create_tag("source_1", None)

    # source_tag が None
    with pytest.raises(ValueError):
        tag_repository.create_tag(None, "some_tag")

def test_update_tag_nonexistent_id(tag_repository):
    """
    update_tag の異常系テスト。
    存在しない ID を指定したらエラーが起きる仕様にしている場合の例。
    """
    non_existent_id = 9999
    # リポジトリ側で存在チェック → 見つからなければ例外を投げる想定
    with pytest.raises(ValueError):
        tag_repository.update_tag(non_existent_id, source_tag="does_not_exist", tag="does_not_exist")

def test_delete_tag_nonexistent_id(tag_repository):
    """
    delete_tag の異常系テスト。
    存在しない ID を削除しようとしてエラーが起きる仕様の場合の例。
    """
    non_existent_id = 9999
    with pytest.raises(ValueError):
        tag_repository.delete_tag(non_existent_id)

def test_update_tag_status_inconsistent_preferred_id(tag_repository):
    """
    CHECK制約などで alias=False の場合は (preferred_tag_id=tag_id) でなければNG、
    といったルールがあるなら、それを破ってみるテスト。
    """
    # 事前に Tag, Format 用意 (tag_id=1, format_id=2)
    with tag_repository.session_factory() as session:
        t = Tag(tag_id=1, tag="tag_for_check", source_tag="src_for_check")
        f = TagFormat(format_id=201, format_name="check_format")
        session.add_all([t, f])
        session.commit()

    # alias=False なのに preferred_tag_id が別ID
    # リポジトリの実装がチェックをしていれば ValueError など
    # あるいはDBレイヤーでIntegrityErrorなどが投げられるかもしれない
    with pytest.raises((ValueError, IntegrityError)):
        tag_repository.update_tag_status(
            tag_id=1,
            format_id=201,
            type_id=100,
            alias=False,
            preferred_tag_id=999  # 本来なら1 を指定すべき
        )

def test_update_tag_status_nonexistent_foreign_keys(tag_repository):
    """
    存在しない tag_id, format_id を指定した場合の異常系テスト例。
    FK制約違反で IntegrityError が起きるか、ValueError にするかは実装次第。
    """
    with pytest.raises((IntegrityError, ValueError)):
        # 事前にTagやFormatを入れていないので、DBレイヤーでFK制約エラーになる想定
        tag_repository.update_tag_status(
            tag_id=9999,
            format_id=8888,
            type_id=100,
            alias=False,
            preferred_tag_id=9999
        )

def test_bulk_insert_tags_invalid_data(tag_repository):
    """
    bulk_insert_tags の異常系例。
    PolarsのDataFrameに必須カラムが無いなど。
    """
    try:
        import polars as pl
    except ImportError:
        pytest.skip("polars がインストールされていないためスキップ")

    # 'tag' カラムが無い例
    df_missing_column = pl.DataFrame(
        {
            "source_tag": ["src1", "src2", "src3"],
            # "tag" カラムを敢えて入れない
        }
    )
    with pytest.raises(ValueError):
        tag_repository.bulk_insert_tags(df_missing_column)

def test_add_or_update_translation_nonexistent_tag(tag_repository):
    """
    存在しない tag_id へ翻訳を追加しようとした場合の例外テスト。
    """
    non_existent_id = 9999
    with pytest.raises(ValueError):
        tag_repository.add_or_update_translation(non_existent_id, "en", "GhostTag")
