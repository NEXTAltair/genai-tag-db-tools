import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from genai_tag_db_tools.data.database_schema import Base
from genai_tag_db_tools.data.database_schema import Tag, TagStatus, TagTranslation, TagFormat, TagTypeName, TagTypeFormatMapping, TagUsageCounts
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
    def session_factory_override():
        return db_session
    repository.session_factory = session_factory_override

    yield repository

    # teardown（必要なら書く）
    # 今回は functionスコープで db_session が切れるときにロールバックされるため特になし
    Base.metadata.drop_all(bind=db_session.bind)

# =============================================================================
# 2) テスト本体
# =============================================================================

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
    """
    # 事前にTagFormatをinsert
    with tag_repository.session_factory() as session:
        session.add(TagFormat(format_id=10, format_name="danbooru"))
        session.commit()

    fid = tag_repository.get_format_id("danbooru")
    assert fid == 10

    none_fid = tag_repository.get_format_id("nonsense")
    assert none_fid is None

def test_update_tag_status(tag_repository):
    """
    update_tag_status のテスト (既存があればエラーを投げる仕様)。
    """
    # 事前に Tag, Format をinsert
    with tag_repository.session_factory() as session:
        t = Tag(tag_id=5, tag="test_tag", source_tag="test_source")
        f = TagFormat(format_id=20, format_name="test_format")
        session.add_all([t, f])
        session.commit()

    # 新規
    tag_repository.update_tag_status(tag_id=5, format_id=20, type_id=100, alias=False, preferred_tag_id=5)

    # もう一度同じ tag_id, format_id で呼ぶ → ValueError
    with pytest.raises(ValueError):
        tag_repository.update_tag_status(tag_id=5, format_id=20, type_id=100, alias=False, preferred_tag_id=5)

def test_get_usage_count_and_update_usage_count(tag_repository):
    """
    usage_count の取得・更新テスト。
    """
    # 事前に Tag, Format
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
    同じ (tag_id, language, translation) が既にあればスキップ。
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

def test_search_tags(tag_repository):
    """
    search_tags のテスト。
    """
    # 1) 準備: Tag, Translation, Status, Format, etc.
    with tag_repository.session_factory() as session:
        # Tag
        t1 = Tag(tag_id=101, tag="cat", source_tag="cat_src")
        t2 = Tag(tag_id=102, tag="dog", source_tag="dog_src")
        session.add_all([t1, t2])

        # Translation
        tr1 = TagTranslation(tag_id=101, language="en", translation="cat")
        tr2 = TagTranslation(tag_id=102, language="en", translation="dog")
        session.add_all([tr1, tr2])

        # Format
        f = TagFormat(format_id=40, format_name="danbooru")
        session.add(f)

        # Status
        s1 = TagStatus(tag_id=101, format_id=40, type_id=999, alias=False, preferred_tag_id=101)
        s2 = TagStatus(tag_id=102, format_id=40, type_id=999, alias=True, preferred_tag_id=101)
        session.add_all([s1, s2])

        # UsageCounts
        uc1 = TagUsageCounts(tag_id=101, format_id=40, count=5)
        uc2 = TagUsageCounts(tag_id=102, format_id=40, count=2)
        session.add_all([uc1, uc2])

        # TagTypeFormatMapping + TagTypeName
        ttn = TagTypeName(type_name_id=999, type_name="Animal")
        ttfm = TagTypeFormatMapping(format_id=40, type_id=999, type_name_id=999)
        session.add_all([ttn, ttfm])

        session.commit()

    # 2) search_tags
    results_all = tag_repository.search_tags(keyword="a", partial=True, format_name="All")
    # "cat" "dog" の両方に "a" は含まれないが "Translation" に含まれれば該当するかチェック
    # cat -> c'a't, dog -> no 'a',  あるいは "cat"翻訳に "a" が含まれるか
    # いずれにせよ partialマッチの挙動を確認
    # テストなので、動作確認したいパターンに応じてassertを書く

    # 3) format_name を "danbooru" に絞り込む
    results = tag_repository.search_tags(keyword="cat", partial=True, format_name="danbooru")
    assert len(results) == 1
    assert results[0]["tag"] == "cat"
    assert results[0]["usage_count"] == 5
    assert results[0]["alias"] == False
    assert results[0]["type_name"] == "Animal"

def test_find_preferred_tag(tag_repository):
    """
    find_preferred_tag のテスト。
    """
    with tag_repository.session_factory() as session:
        t_cat = Tag(tag_id=201, tag="cat", source_tag="cat_src")
        f_db = TagFormat(format_id=60, format_name="db")
        status_cat = TagStatus(tag_id=201, format_id=60, type_id=1, alias=True, preferred_tag_id=999)
        session.add_all([t_cat, f_db, status_cat])
        session.commit()

    preferred_id = tag_repository.find_preferred_tag(tag_id=201, format_id=60)
    assert preferred_id == 999

    # 存在しなければNone
    none_pref = tag_repository.find_preferred_tag(tag_id=999, format_id=60)
    assert none_pref is None
