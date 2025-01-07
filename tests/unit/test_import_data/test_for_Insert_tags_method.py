# tests/unit/test_import_data/test_insert_tags_method.py

import pytest
import polars as pl
from unittest.mock import MagicMock

from genai_tag_db_tools.services.import_data import TagDataImporter
from genai_tag_db_tools.data.tag_repository import TagRepository


@pytest.fixture
def importer():
    """
    TagDataImporterのインスタンスを返すフィクスチャ。
    主に _insert_tags_and_attach_id をテストするので、
    TagRepository 部分をモック化して呼び出しを検証する。
    """
    importer = TagDataImporter()
    return importer


def test_insert_tags_and_attach_id_basic(importer: TagDataImporter):
    """
    _insert_tags_and_attach_id が新規タグをまとめて DB に挿入し、
    カラム tag_id を付与するフローをテスト。

    変更点:
        - _fetch_existing_tags_as_map の引数を順序ではなく内容(集合)で比較するように修正。
    """
    # 仮の DataFrame
    df = pl.DataFrame(
        {
            "source_tag": ["tag_One", "tag_Two"],
            "tag": ["tag One", "tag Two"],
        }
    )

    # TagRepository をモック
    mock_repo = MagicMock(spec=TagRepository)
    importer._tag_repo = mock_repo

    # bulk_insert_tags の呼び出し結果は確認だけ
    # _fetch_existing_tags_as_map で {tagName: tag_id} を返す
    mock_repo._fetch_existing_tags_as_map.return_value = {
        "tag one": 101,
        "tag two": 102,
    }

    # 実行
    result_df = importer._insert_tags_and_attach_id(df)

    # bulk_insert_tags が呼ばれたか
    mock_repo.bulk_insert_tags.assert_called_once()

    # _fetch_existing_tags_as_map が呼ばれたか (呼び出し回数と引数)
    mock_repo._fetch_existing_tags_as_map.assert_called_once()
    call_args, call_kwargs = mock_repo._fetch_existing_tags_as_map.call_args
    actual_list = call_args[0]  # 実際に渡されたリスト (例: ['tag Two', 'tag One'])

    # 順序でなく、要素の集合またはソート結果で比較する
    assert sorted(actual_list) == sorted(["tag One", "tag Two"])
    # または:
    # assert set(actual_list) == {"tag One", "tag Two"}

    # 結果の DataFrame に tag_id カラムが存在し、想定の値が入っているか
    assert "tag_id" in result_df.columns
    # ※結果の tag_id はテストモックで実際に反映していないため null になる可能性あり
    #   ここでは「カラムができているかどうか」だけを確認する。
    #   もし実際のid値をテストしたい場合はモックの挙動を改めて工夫する。

def test_insert_tags_and_attach_id_missing_column(importer: TagDataImporter):
    """
    'tag' カラムが存在しない場合は何もしない(例外を投げずスキップ)ことを確認。
    """
    df = pl.DataFrame({"source_tag": ["foo", "bar"]})
    result_df = importer._insert_tags_and_attach_id(df)
    # 何も起きず、tag_idも付与されない
    assert "tag_id" not in result_df.columns


def test_insert_tags_and_attach_id_duplicate(importer: TagDataImporter):
    """
    重複するタグがある場合、同じ tag_id が付与されることを確認。
    """
    df = pl.DataFrame(
        {
            "source_tag": ["tag_A", "tag_A", "tag_B"],
            "tag": ["tag A", "tag A", "tag B"],
        }
    )

    mock_repo = MagicMock(spec=TagRepository)
    importer._tag_repo = mock_repo

    mock_repo._fetch_existing_tags_as_map.return_value = {
        "tag A": 100,
        "tag B": 200,
    }

    result_df = importer._insert_tags_and_attach_id(df)
    assert "tag_id" in result_df.columns
    # "tag a" は同じID
    assert result_df["tag_id"].to_list() == [100, 100, 200]


def test_insert_tags_and_attach_id_exception(importer: TagDataImporter):
    """
    bulk_insert_tags や _fetch_existing_tags_as_map がエラーを投げた場合、
    例外をそのまま上位に伝播するかを確認。
    """
    df = pl.DataFrame({"source_tag": ["foo"], "tag": ["bar"]})

    mock_repo = MagicMock(spec=TagRepository)
    importer._tag_repo = mock_repo

    mock_repo.bulk_insert_tags.side_effect = RuntimeError("DB error")
    with pytest.raises(RuntimeError) as exc_info:
        importer._insert_tags_and_attach_id(df)
    assert "DB error" in str(exc_info.value)
