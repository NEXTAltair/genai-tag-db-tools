# tests/test_tag_register.py

import pytest
import polars as pl
from unittest.mock import MagicMock

from genai_tag_db_tools.services.tag_register import TagRegister

@pytest.fixture
def mock_repo():
    """
    TagRepository をモック化したフィクスチャ。
    すべてのテストケースで共有。
    """
    mock = MagicMock()
    # デフォルトの戻り値等を設定しておく場合はここで
    mock.create_tag.return_value = MagicMock(name='created_tag_id')  # 固定の戻り値を設定
    return mock

@pytest.fixture
def tag_register(mock_repo):
    """
    TagRegister のインスタンスを返すフィクスチャ。
    モック化した repository を注入する。
    """
    return TagRegister(repository=mock_repo)


def test_normalize_tags_no_source_tag(tag_register):
    """
    source_tag が空文字の場合、tag をコピーして source_tag に反映されるかテスト
    """
    df = pl.DataFrame({
        "source_tag": ["", "src2"],
        "tag": ["tag1", "tag2"]
    })
    result = tag_register.normalize_tags(df)

    # 最初の行のsource_tagが空なので、tag1がコピーされる
    assert result["source_tag"][0] == "tag1"
    # 2行目はそのまま
    assert result["source_tag"][1] == "src2"

def test_normalize_tags_no_tag(tag_register):
    """
    tag が空文字の場合、source_tag をクリーニングしてコピーされるかテスト
    """
    df = pl.DataFrame({
        "source_tag": [" src_tag ", "another"],
        "tag": ["", "tag2"]
    })
    # TagCleaner.clean_format で空白除去などを行う想定
    # -> " src_tag " → "src tag"
    result = tag_register.normalize_tags(df)

    assert result["tag"][0] == "src tag"
    assert result["tag"][1] == "tag2"

def test_normalize_tags_missing_columns(tag_register):
    """
    source_tag / tag どちらかが無い場合、処理をスキップする
    """
    df = pl.DataFrame({"tag": ["tag1", "tag2"]})
    # source_tagカラムが無いので変化なし
    result = tag_register.normalize_tags(df)
    assert "source_tag" not in result.columns

def test_insert_tags_and_attach_id_empty(tag_register, mock_repo):
    """
    'tag' カラムが無い場合はdfをそのまま返す
    """
    df = pl.DataFrame({"foo": ["bar"]})
    result = tag_register.insert_tags_and_attach_id(df)
    # 何もしない → dfがそのまま
    assert result.columns == ["foo"]
    mock_repo.bulk_insert_tags.assert_not_called()

def test_insert_tags_and_attach_id_normal(tag_register, mock_repo):
    """
    tagカラムがあれば bulk_insert_tags と _fetch_existing_tags_as_map を呼び出し、
    tag_idカラムが付与される
    """
    # モックの戻り値を用意
    mock_repo._fetch_existing_tags_as_map.return_value = {
        "tagA": 101,
        "tagB": 102,
    }

    df = pl.DataFrame({
        "source_tag": ["srcA", "srcB"],
        "tag": ["tagA", "tagB"]
    })
    result = tag_register.insert_tags_and_attach_id(df)

    # bulk_insert_tags が呼ばれたか
    mock_repo.bulk_insert_tags.assert_called_once()
    # _fetch_existing_tags_as_map が呼ばれたか
    mock_repo._fetch_existing_tags_as_map.assert_called_once()

    # 変換されたtag_idカラムをチェック
    assert "tag_id" in result.columns
    assert result["tag_id"][0] == 101
    assert result["tag_id"][1] == 102

def test_update_usage_counts_no_columns(tag_register, mock_repo):
    """
    tag_id or count カラムが無ければ何もしない
    """
    df = pl.DataFrame({"foo": [1], "bar": [2]})
    tag_register.update_usage_counts(df, format_id=1)
    mock_repo.update_usage_count.assert_not_called()

def test_update_usage_counts_normal(tag_register, mock_repo):
    """
    tag_id, count カラムがある場合、
    各行に対して update_usage_count が呼ばれる
    """
    df = pl.DataFrame({
        "tag_id": [100, 101, None],
        "count": [10, 20, 30],
    })
    tag_register.update_usage_counts(df, format_id=1)

    # 呼ばれた回数 (Noneは無視)
    calls = mock_repo.update_usage_count.call_args_list
    assert len(calls) == 2

    # 1回目: tag_id=100, format_id=1, count=10
    assert calls[0].kwargs == {"tag_id": 100, "format_id": 1, "count": 10}
    # 2回目: tag_id=101, format_id=1, count=20
    assert calls[1].kwargs == {"tag_id": 101, "format_id": 1, "count": 20}

def test_update_translations_no_columns(tag_register, mock_repo):
    """
    tag_id or translationカラムが無い場合は何もしない
    """
    df = pl.DataFrame({"foo": [1], "bar": ["something"]})
    tag_register.update_translations(df, language="en")
    mock_repo.add_or_update_translation.assert_not_called()

def test_update_translations_normal(tag_register, mock_repo):
    """
    tag_id, translationがあれば add_or_update_translationを行う
    """
    df = pl.DataFrame({
        "tag_id": [200, None, 202],
        "translation": ["hello", "ignored", "world"]
    })
    tag_register.update_translations(df, language="en")

    calls = mock_repo.add_or_update_translation.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs == {"tag_id": 200, "language": "en", "translation": "hello"}
    assert calls[1].kwargs == {"tag_id": 202, "language": "en", "translation": "world"}

def test_update_deprecated_tags_no_columns(tag_register, mock_repo):
    """
    tag_id or deprecated_tagsカラムが無い場合は何もしない
    """
    df = pl.DataFrame({"tag_id": [300], "foo": ["bar"]})
    tag_register.update_deprecated_tags(df, format_id=2)
    mock_repo.create_tag.assert_not_called()
    mock_repo.update_tag_status.assert_not_called()

def test_update_deprecated_tags_normal(tag_register, mock_repo):
    """
    deprecated_tags があればカンマ区切りでエイリアス登録
    """
    # 各create_tagの呼び出しに対する戻り値を設定
    mock_tag_ids = [MagicMock(name=f'created_tag_id_{i}') for i in range(3)]
    mock_repo.create_tag.side_effect = mock_tag_ids

    df = pl.DataFrame({
        "tag_id": [300],
        "deprecated_tags": ["abc, def ,  ghi"],
    })
    tag_register.update_deprecated_tags(df, format_id=2)

    # 3つのタグ 'abc', 'def', 'ghi' を create_tag → update_tag_status
    calls_create = mock_repo.create_tag.call_args_list
    calls_status = mock_repo.update_tag_status.call_args_list

    assert len(calls_create) == 3
    assert len(calls_status) == 3

    # 各タグの処理を確認
    expected_tags = ["abc", "def", "ghi"]
    for i, tag in enumerate(expected_tags):
        # create_tagの引数を確認
        assert calls_create[i].args == (tag, tag)
        # update_tag_statusの引数を確認
        assert calls_status[i].kwargs == {
            "tag_id": mock_tag_ids[i],
            "format_id": 2,
            "alias": True,
            "preferred_tag_id": 300
        }
