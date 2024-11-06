"""何かと狂いがちなDBのデータの整合性をチェックするテストコード"""

import pytest
import sqlite3
from pathlib import Path


@pytest.fixture
def db_connection():
    db_path = Path("tags_v3.db")
    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


def test_database_connection(db_connection):
    assert db_connection is not None


def test_tables_exist(db_connection):
    cursor = db_connection.cursor()
    tables = [
        "TAGS",
        "TAG_TRANSLATIONS",
        "TAG_STATUS",
        "TAG_FORMATS",
        "TAG_USAGE_COUNTS",
        "TAG_TYPE_FORMAT_MAPPING",
        "TAG_TYPE_NAME",
    ]
    for table in tables:
        cursor.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
        )
        assert cursor.fetchone() is not None, f"テーブル {table} が存在しません"


def test_tags_table_columns(db_connection):
    cursor = db_connection.cursor()
    cursor.execute("PRAGMA table_info('TAGS')")
    columns = [info[1] for info in cursor.fetchall()]
    expected_columns = ["tag_id", "tag", "source_tag"]
    for col in expected_columns:
        assert col in columns, f"列 {col} がTAGSテーブルに存在しません"


def test_foreign_key_constraints(db_connection):
    """
    データベースの外部キー制約をテストする関数。
    この関数は、TAG_STATUS テーブルの外部キーが他の関連テーブルに正しく存在するかを確認します。
    以下のチェックを行います：
    1. TAG_STATUS の tag_id が TAGS テーブルに存在するか。
    2. TAG_STATUS の format_id が TAG_FORMATS テーブルに存在するか。
    3. TAG_STATUS の (format_id, type_id) の組み合わせが TAG_TYPE_FORMAT_MAPPING テーブルに存在するか。
    4. TAG_STATUS の preferred_tag_id が TAGS テーブルに存在するか（NULL でない場合）。
    Args:
        db_connection (sqlite3.Connection): データベース接続オブジェクト。
    Raises:
        AssertionError: 外部キーが関連テーブルに存在しない場合に発生します。
    """
    cursor = db_connection.cursor()

    # TAG_STATUS の各外部キーの整合性を確認する
    # TAG_STATUS の tag_id が TAGS に存在するかチェック
    cursor.execute(
        """
        SELECT TS.tag_id, T.source_tag, TF.format_name, TT.translation, TT.language, TS.type_id, TS.alias
        FROM TAG_STATUS AS TS
        LEFT JOIN TAGS AS T ON TS.tag_id = T.tag_id
        LEFT JOIN TAG_FORMATS AS TF ON TS.format_id = TF.format_id
        LEFT JOIN TAG_TRANSLATIONS AS TT ON TS.tag_id = TT.tag_id
        WHERE TS.tag_id NOT IN (SELECT tag_id FROM TAGS)
    """
    )
    missing_tags = cursor.fetchall()
    assert (
        len(missing_tags) == 0
    ), f"TAG_STATUS の tag_id が TAGS に存在しません: {missing_tags}"

    # TAG_STATUS の format_id が TAG_FORMATS に存在するかチェック
    cursor.execute(
        """
        SELECT TS.format_id, TF.format_name, TS.type_id, TS.alias
        FROM TAG_STATUS AS TS
        LEFT JOIN TAG_FORMATS AS TF ON TS.format_id = TF.format_id
        WHERE TS.format_id NOT IN (SELECT format_id FROM TAG_FORMATS)
    """
    )
    missing_formats = cursor.fetchall()
    assert (
        len(missing_formats) == 0
    ), f"TAG_STATUS の format_id が TAG_FORMATS に存在しません: {missing_formats}"

    # TAG_STATUS の (format_id, type_id) が TAG_TYPE_FORMAT_MAPPING に存在するかチェック
    cursor.execute(
        """
        SELECT TS.format_id, TS.type_id, TF.format_name, TTN.type_name, TS.alias
        FROM TAG_STATUS AS TS
        LEFT JOIN TAG_FORMATS AS TF ON TS.format_id = TF.format_id
        LEFT JOIN TAG_TYPE_FORMAT_MAPPING AS TTFM ON TS.format_id = TTFM.format_id AND TS.type_id = TTFM.type_id
        LEFT JOIN TAG_TYPE_NAME AS TTN ON TTFM.type_name_id = TTN.type_name_id
        WHERE (TS.format_id, TS.type_id) NOT IN (
            SELECT format_id, type_id FROM TAG_TYPE_FORMAT_MAPPING
        )
    """
    )
    missing_mappings = cursor.fetchall()
    assert (
        len(missing_mappings) == 0
    ), f"TAG_STATUS の (format_id, type_id) が TAG_TYPE_FORMAT_MAPPING に存在しません: {missing_mappings}"

    # TAG_STATUS の preferred_tag_id が TAGS に存在するかチェック
    cursor.execute(
        """
        SELECT TS.preferred_tag_id, T.source_tag, TF.format_name, TS.type_id, TS.alias
        FROM TAG_STATUS AS TS
        LEFT JOIN TAGS AS T ON TS.preferred_tag_id = T.tag_id
        LEFT JOIN TAG_FORMATS AS TF ON TS.format_id = TF.format_id
        WHERE TS.preferred_tag_id IS NOT NULL AND TS.preferred_tag_id NOT IN (SELECT tag_id FROM TAGS)
    """
    )
    missing_preferred_tags = cursor.fetchall()
    assert (
        len(missing_preferred_tags) == 0
    ), f"TAG_STATUS の preferred_tag_id が TAGS に存在しません: {missing_preferred_tags}"

    def test_models_present(db_connection):
        """モデルがデータベースに正しく挿入されていることを確認するテスト"""
        cursor = db_connection.cursor()
        cursor.execute("SELECT name FROM models")
        models = {row[0] for row in cursor.fetchall()}
        expected_models = {
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-4o-mini",
            "laion",
            "cafe",
            "gemini-1.5-pro-exp-0801",
            "gemini-1.5-pro-preview-0409",
            "gemini-1.0-pro-vision",
            "claude-3-5-sonnet-20240620",
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            "RealESRGAN_x4plus",
        }
        assert expected_models.issubset(models), "期待されるモデルがすべて存在しません"
