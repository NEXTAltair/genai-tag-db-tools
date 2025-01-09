import pytest
import polars as pl
from unittest.mock import MagicMock

from genai_tag_db_tools.services.tag_register import TagRegister
from genai_tag_db_tools.data.tag_repository import TagRepository


@pytest.fixture
def register():
    """
    TagRegisterのインスタンスを返すフィクスチャ。
    TagRepository 部分をモック化して呼び出しを検証する。
    """
    mock_repo = MagicMock(spec=TagRepository)
    register = TagRegister(repository=mock_repo)
    return register


def test_insert_tags_and_attach_id_basic(register: TagRegister):
    """
    insert_tags_and_attach_id が新規タグをまとめて DB に挿入し、
    カラム tag_id を付与するフローをテスト。
    """
    # 仮の DataFrame
    df = pl.DataFrame(
        {
            "source_tag": ["tag_One", "tag_Two"],
            "tag": ["tag One", "tag Two"],
        }
    )

    # _fetch_existing_tags_as_map で {tagName: tag_id} を返す
    register._repo._fetch_existing_tags_as_map.return_value = {
        "tag One": 101,
        "tag Two": 102,
    }

    # 実行
    result_df = register.insert_tags_and_attach_id(df)

    # bulk_insert_tags が呼ばれたか
    register._repo.bulk_insert_tags.assert_called_once()
    # 正しい引数で呼ばれたか確認
    call_df = register._repo.bulk_insert_tags.call_args[0][0]
    assert isinstance(call_df, pl.DataFrame)
    assert set(call_df.columns) == {"source_tag", "tag"}

    # _fetch_existing_tags_as_map が呼ばれたか
    register._repo._fetch_existing_tags_as_map.assert_called_once()
    call_args = register._repo._fetch_existing_tags_as_map.call_args[0][0]
    assert set(call_args) == {"tag One", "tag Two"}

    # 結果の DataFrame に tag_id カラムが存在し、想定の値が入っているか
    assert "tag_id" in result_df.columns
    assert result_df["tag_id"].to_list() == [101, 102]


def test_insert_tags_and_attach_id_missing_column(register: TagRegister):
    """
    'tag' カラムが存在しない場合は何もしない(例外を投げずスキップ)ことを確認。
    """
    df = pl.DataFrame({"source_tag": ["foo", "bar"]})
    result_df = register.insert_tags_and_attach_id(df)
    # 何も起きず、tag_idも付与されない
    assert "tag_id" not in result_df.columns
    # bulk_insert_tagsも呼ばれない
    register._repo.bulk_insert_tags.assert_not_called()


def test_insert_tags_and_attach_id_duplicate(register: TagRegister):
    """
    重複するタグがある場合、同じ tag_id が付与されることを確認。
    """
    df = pl.DataFrame(
        {
            "source_tag": ["tag_A", "tag_A", "tag_B"],
            "tag": ["tag A", "tag A", "tag B"],
        }
    )

    register._repo._fetch_existing_tags_as_map.return_value = {
        "tag A": 100,
        "tag B": 200,
    }

    result_df = register.insert_tags_and_attach_id(df)
    assert "tag_id" in result_df.columns
    # "tag A" は同じID
    assert result_df["tag_id"].to_list() == [100, 100, 200]


def test_insert_tags_and_attach_id_exception(register: TagRegister):
    """
    bulk_insert_tags や _fetch_existing_tags_as_map がエラーを投げた場合、
    例外をそのまま上位に伝播するかを確認。
    """
    df = pl.DataFrame({"source_tag": ["foo"], "tag": ["bar"]})
    register._repo.bulk_insert_tags.side_effect = RuntimeError("DB error")

    with pytest.raises(RuntimeError) as exc_info:
        register.insert_tags_and_attach_id(df)
    assert "DB error" in str(exc_info.value)


def test_normalize_tags(register: TagRegister):
    """
    normalize_tags メソッドのテスト:
    - source_tag/tagの相互補完
    - タグのクリーニング
    """
    df = pl.DataFrame(
        {
            "source_tag": ["Tag_One", ""],
            "tag": ["", "Tag Two"],
        }
    )

    result_df = register.normalize_tags(df)

    # source_tagが空ならtagをコピー、tagが空ならsource_tagをクリーニングしてコピー
    assert result_df["source_tag"].to_list() == ["Tag_One", "Tag Two"]
    assert result_df["tag"].to_list() == ["Tag One", "Tag Two"]


def test_update_usage_counts(register: TagRegister):
    """
    update_usage_counts メソッドのテスト
    """
    df = pl.DataFrame({
        "tag_id": [1, 2],
        "count": [10, 20]
    })
    format_id = 1

    register.update_usage_counts(df, format_id)

    # 各タグについてupdate_usage_countが呼ばれることを確認
    assert register._repo.update_usage_count.call_count == 2
    register._repo.update_usage_count.assert_any_call(tag_id=1, format_id=1, count=10)
    register._repo.update_usage_count.assert_any_call(tag_id=2, format_id=1, count=20)


def test_update_translations(register: TagRegister):
    """
    update_translations メソッドのテスト
    """
    df = pl.DataFrame({
        "tag_id": [1, 2],
        "translation": ["翻訳1", "翻訳2"]
    })
    language = "ja"

    register.update_translations(df, language)

    # 各タグについてadd_or_update_translationが呼ばれることを確認
    assert register._repo.add_or_update_translation.call_count == 2
    register._repo.add_or_update_translation.assert_any_call(1, "ja", "翻訳1")
    register._repo.add_or_update_translation.assert_any_call(2, "ja", "翻訳2")


def test_update_deprecated_tags(register: TagRegister):
    """
    update_deprecated_tags メソッドのテスト
    """
    df = pl.DataFrame({
        "tag_id": [1],
        "deprecated_tags": ["old_tag1,old_tag2"]  # カンマの後にスペースを入れない
    })
    format_id = 1

    # create_tagの戻り値を設定
    register._repo.create_tag.side_effect = [101, 102]

    register.update_deprecated_tags(df, format_id)

    # 各エイリアスについてcreate_tagとupdate_tag_statusが呼ばれることを確認
    assert register._repo.create_tag.call_count == 2
    register._repo.create_tag.assert_any_call("old tag1", "old tag1")
    register._repo.create_tag.assert_any_call("old tag2", "old tag2")

    assert register._repo.update_tag_status.call_count == 2
    register._repo.update_tag_status.assert_any_call(
        tag_id=101, format_id=1, alias=True, preferred_tag_id=1
    )
    register._repo.update_tag_status.assert_any_call(
        tag_id=102, format_id=1, alias=True, preferred_tag_id=1
    )
