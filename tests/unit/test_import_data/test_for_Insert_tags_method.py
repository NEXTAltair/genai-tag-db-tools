import pytest
from unittest.mock import MagicMock, patch, Mock, call

import polars as pl
from datetime import datetime
from sqlalchemy import (
    Table, Column, Integer, String, MetaData, DateTime,
    ForeignKey, Boolean, create_engine, select
)
from sqlalchemy.sql import func

from genai_tag_db_tools.core.import_data import TagDataImporter
from genai_tag_db_tools.data.database_schema import Tag

# テストスキーマを定義する
metadata = MetaData()

tags = Table(
    'TAGS',
    metadata,
    Column('tag_id', Integer, primary_key=True),
    Column('source_tag', String),
    Column('tag', String, nullable=False),
    Column('created_at', DateTime, server_default=func.now(), nullable=True), # pylint: disable=not-callable
    Column('updated_at', DateTime, server_default=func.now(), nullable=True), # pylint: disable=not-callable
)

@pytest.fixture(autouse=True)
def setup_database(engine):
    """各テストの前にテスト テーブルを作成"""
    metadata.create_all(engine)
    yield
    metadata.drop_all(engine)

@pytest.fixture
def importer(db_session):
    """テスト セッションで TagDataImporter インスタンスを作成する"""
    importer = TagDataImporter()
    importer.tag_db.session = db_session
    return importer

def test_insert_tags_with_empty_df(importer, caplog):
    """空のDataFrameを処理しようとした場合のエラーログが出力されることをテスト"""
    # ログレベルをDEBUGに設定
    caplog.set_level("DEBUG")

    # 空のデータフレームを用意
    empty_df = pl.DataFrame({
        "source_tag": [],
        "tag": []
    })

    # 処理実行
    try:
        importer.insert_tags(empty_df)
    except Exception:
        pass  # エラーは想定内なので無視

    # ERRORレベルのログが1つ以上出力されていることを確認
    assert any(record.levelname == "ERROR" for record in caplog.records), \
        "エラーログが出力されていない"

def test_insert_tags_with_new_data(importer, caplog):
    """新規タグの挿入テスト"""
    # リポジトリのモックを作成
    mock_repo = Mock()
    # 最初は既存のタグがないことを示す
    mock_repo.get_tag_id_mapping.return_value = {}
    # bulk_insert_tags後の新規タグのIDマッピング
    mock_repo.get_tag_id_mapping.side_effect = [
        {},  # 1回目の呼び出し（既存タグ検索）
        {"new tag 1": 1, "new tag 2": 2}  # 2回目の呼び出し（新規タグ検索）
    ]
    importer.tag_repo = mock_repo

    # テストデータを準備
    test_df = pl.DataFrame({
        "source_tag": ["new_tag_1", "new_tag_2"],
        "tag": ["new tag 1", "new tag 2"]
    })

    # タグを挿入
    result_df = importer.insert_tags(test_df)

    # 結果の検証
    assert "tag_id" in result_df.columns
    assert result_df.shape[0] == 2
    assert all(result_df["tag_id"].is_not_null())

    # モックの呼び出しを検証
    mock_repo.get_tag_id_mapping.assert_called()
    mock_repo.bulk_insert_tags.assert_called_once()

    # 期待されるタグデータが渡されたことを確認
    expected_tag_data = [
        {"source_tag": "new_tag_1", "tag": "new tag 1"},
        {"source_tag": "new_tag_2", "tag": "new tag 2"}
    ]
    actual_tag_data = mock_repo.bulk_insert_tags.call_args[0][0]
    assert actual_tag_data == expected_tag_data

    # ログ出力の検証
    assert "新規タグを登録: 2件" in caplog.text

def test_insert_tags_with_existing_data(importer, caplog):
    """既存タグが存在する場合のテスト"""
    # リポジトリのモックを作成
    mock_repo = Mock()
    # 既存のタグのマッピングを設定
    mock_repo.get_tag_id_mapping.return_value = {"existing tag": 1}
    importer.tag_repo = mock_repo

    # テストデータを準備
    test_df = pl.DataFrame({
        "source_tag": ["existing_tag", "new_tag"],
        "tag": ["existing tag", "new tag"]
    })

    # タグを挿入
    result_df = importer.insert_tags(test_df)

    # 結果の検証
    assert "tag_id" in result_df.columns
    existing_tag_row = result_df.filter(pl.col("tag") == "existing tag")
    assert existing_tag_row["tag_id"].item() == 1

    # モックの呼び出しを検証
    mock_repo.get_tag_id_mapping.assert_called()

    # 既存タグのログを確認
    assert "既存タグを検出: existing tag" in caplog.text

def test_insert_tags_with_invalid_data(importer, caplog):
    """無効なデータ構造の処理テスト"""
    # 必須カラムが欠けているデータを準備
    test_df = pl.DataFrame({
        "source_tag": ["test"]  # tagカラムが欠けている
    })

    # エラーの発生を確認
    with pytest.raises(Exception) as exc_info:
        importer.insert_tags(test_df)

    # ログ出力の検証
    assert "df へ tag id 追加中にエラー" in caplog.text

def test_insert_tags_with_duplicate_values(importer, db_session):
    mock_repo = Mock()
    importer.tag_repo = mock_repo
    importer.session = db_session

    # 1回の呼び出しに対する戻り値を設定
    mock_repo.get_tag_id_mapping.return_value = {"tag 1": 1}

    test_df = pl.DataFrame({
        "source_tag": ["tag_1", "tag_1"],
        "tag": ["tag 1", "tag 1"]
    })

    result_df = importer.insert_tags(test_df)

    # 結果の検証
    assert "tag_id" in result_df.columns
    assert result_df.shape[0] == 2
    tag_ids = result_df["tag_id"].to_list()
    assert len(set(tag_ids)) == 1

    # 実際の呼び出しパターンに合わせて検証
    expected_calls = [
        call(['tag 1']),               # 1回目の呼び出し
    ]
    assert mock_repo.get_tag_id_mapping.call_args_list == expected_calls

    # モックの呼び出しを検証
    mock_repo.get_tag_id_mapping.assert_called_once_with(['tag 1'])

def test_insert_tags_null_values(importer, db_session, caplog):

    mock_repo = Mock()
    importer.tag_repo = mock_repo
    importer.session = db_session

    # テストデータの準備 値が null
    test_df = pl.DataFrame({
        "source_tag": [None, "tag_2"],
        "tag": ["tag 1", None]
    })

    # アサートするとエラーが発生
    try:
        importer.insert_tags(test_df)
    except Exception:
        pass  # エラーは想定内なので無視

    # ERRORレベルのログが1つ以上出力されていることを確認
    assert any(record.levelname == "ERROR" for record in caplog.records), \
        "エラーログが出力されていない"
