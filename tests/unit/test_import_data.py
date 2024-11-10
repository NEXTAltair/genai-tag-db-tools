import pytest
import polars as pl
from pathlib import Path
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QObject
from genai_tag_db_tools.core.import_data import TagDataImporter, ImportConfig

# テスト用のサンプルデータを定義
sample_data_cases = [
    # ケース 1: タイプと数を含む基本的なCSV
    {
        "name": "basic_tag_data",
        "data": {
            "source_tag": ["tag_1", "tag_2"],
            "type_id": [0, 0],  # 一般的なタイプ
            "count": [5000, 3000],
        },
    },
    # ケース 2: 非推奨のバリアントを含むCSV
    {
        "name": "deprecated_tags",
        "data": {
            "tag": ["tag1", "tag2"],
            "deprecated_tags": [["tag_4", "tag_5"], ["tag_6", "tag_7"]],
        },
    },
    # ケース 3: 非推奨 + タイプ + カウント
    {
        "name": "deprecated_tags_and_type",
        "data": {
            "source_tag": ["tag_1", "tag_2"],
            "type_id": [0, 0],
            "count": [5000, 3000],
            "deprecated_tags": [["tag_4", "tag_5"], ["tag_6", "tag_7"]],
        },
    },
    # ケース 4: いろいろな情報が含まれるCSV
    {
        "name": "many_columns",
        "data": {
            "id": [1, 2],
            "source_tag": ["tag1", "tag2"],
            "count": [100, 200],
            "related_tags": [[], []],
            "related_tags_updated_at": [
                "2023-09-17T16:19:15.596-04:00",
                "2023-09-17T13:40:46.599-04:00",
            ],
            "type_id": [0, 0],
            "is_locked": [False, True],
            "created_at": [
                "2023-09-17T16:19:15.596-04:00",
                "2023-09-17T13:40:46.599-04:00",
            ],
            "updated_at": [
                "2023-09-17T16:19:15.596-04:00",
                "2023-09-17T13:40:46.599-04:00",
            ],
        },
    },
    # ケース 5: 日本語訳CSV
    {
        "name": "japanese_translations",
        "data": {
            "source_tag": ["tag1", "tag2"],
            "japanese": ["タグ1, タグ2", "タグ3"],
        },
    },
    # ケース 6: 中国語訳CSV
    {
        "name": "chinese_translations",
        "data": {
            "source_tag": ["tag1", "tag2"],
            "type_id": [0, 0],
            "zh-Hant": ["標籤1", "標籤2"],
        },
    },
    # ケース 8: 実際のCSVを抜粋使用したテスト01 `danbooru_241016.csv`
    {
        "name": "danbooru_241016",
        "data": pl.read_csv("tests/resource/case_03.csv"),
    },
    # ケース 9: 実際のCSVを抜粋使用したテスト02 `e621_tags_jsonl.csv`
    {
        "name": "danbooru_241016",
        "data": pl.read_csv("tests/resource/case_04.csv"),
    },
]
sample_data_ids = [
    "CASE_01_基本タグデータ",
    "CASE_02_非推奨タグ",
    "CASE_03_非推奨_タイプ_カウント",
    "CASE_04_多列",
    "CASE_05_日本語訳",
    "CASE_06_中国語訳",
    "CASE_07_ダンボール241016",
    "CASE_08_e621タグ",
]

sample_csv_cases = [
    # ケース 1: 英語のタイポを含むCSV ヘッダなし
    {
        "name": "typo",
        "data": {
            "tag_1": ["tag_2", "tag_3"],
            0: [0, 0],
            10: [200, 2],
            "tag_4, tag_5": [["tag_6", "tag_7"], ["tag_8", "tag_9"]],
            "format_id": 1,
        },
    }
]


# TagDataImporterのインスタンスを作成するためのフィクスチャ
@pytest.fixture
def importer():
    """TagDataImporterのモックを提供するフィクスチャ"""
    with patch("sqlite3.connect"):
        mock_tag_data_importer = TagDataImporter(Path("test.db"))
        mock_tag_data_importer.conn = MagicMock()
        mock_tag_data_importer.conn.cursor = MagicMock()
        yield mock_tag_data_importer


# ImportConfigのサンプルを提供するフィクスチャ
@pytest.fixture
def sample_config():
    """ImportConfigのサンプルを提供するフィクスチャ"""
    return ImportConfig(
        format_id=1,
        language=None,
        column_names=["source_tag", "type_id", "count", "aliases"],
    )


def test_auto_select_columns(importer: TagDataImporter):
    """自動選択のテスト"""
    # テスト用のデータフレームを作成
    df = pl.DataFrame(
        {
            "source_tag": ["tag1", "tag2"],
            "type_id": [0, 0],
            "count": [5000, 3000],
            "other": ["other1", "other2"],
        }
    )

    # 入力をモック化（必要に応じて変更）
    with patch("builtins.input", side_effect=["danbooru", ""]):
        header_list = importer.auto_select_columns(df)

        # 不要な情報は拾わないことを確認
        assert "other" not in header_list

        # 必要な情報はリスト化されていることを確認
        assert (
            "source_tag" in header_list
            and "type_id" in header_list
            and "count" in header_list
        )


def test_map_missing_columns(importer: TagDataImporter):
    """欠落しているカラムヘッダをマッピングするテスト"""
    # テスト用のデータフレームを作成
    df = pl.DataFrame(
        {
            "source_tag": ["tag1", "tag2"],
            "type_id": [0, 0],
            "count": [5000, 3000],
            "other": ["other1", "other2"],
        }
    )

    # 入力をモック化（必要に応じて変更）
    with patch("builtins.input", side_effect=["danbooru", ""]):
        header_list = importer.auto_select_columns(df)

        # 不要な情報は拾わないことを確認
        assert "other" not in header_list

        # 必要な情報はリスト化されていることを確認
        assert (
            "source_tag" in header_list
            and "type_id" in header_list
            and "count" in header_list
        )


def test_human_input(importer: TagDataImporter):
    """人が入力するテスト"""
    df = pl.DataFrame(
        {
            "source_tag": ["tag1", "tag2"],
            "type_id": [0, 0],
            "count": [5000, 3000],
            "other": ["other1", "other2"],
        }
    )

    with patch("builtins.input", side_effect=["danbooru", "custom_input"]):
        header_list = importer.auto_select_columns(df)
        assert "other" not in header_list
        assert "source_tag" in header_list
        assert "type_id" in header_list
        assert "count" in header_list


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_configure_import(importer: TagDataImporter, sample_case):
    """インポート設定メソッドをテスト"""
    # サンプルデータフレームを作成
    df = pl.DataFrame(sample_case["data"])

    # 入力をモック化（必要に応じて変更）
    with patch("builtins.input", side_effect=["danbooru", ""]):
        config = importer.configure_import(df)

    # 設定が正しく行われていることをアサート
    assert config.format_id == 1  # danbooruのフォーマットIDは1

    # カラム名のテスト（サンプルによって異なるため、適宜調整）
    for col in config.column_names:
        assert col in df.columns


def test_normalize_tags_append(importer: TagDataImporter):
    """
    正常系テスト：既に'tag'カラムが存在しない場合、追加されることを確認
    ついでに文字列の正則化も確認
    """
    # テスト用のデータフレームを作成
    df = pl.DataFrame(
        {
            "source_tag": ["Tag1", "tag(2)", "TAG_3"],
        }
    )

    # メソッドを実行
    df_normalized = importer._normalize_tags(df)

    # 'tag'カラムが既存のままであることを確認
    assert df_normalized["tag"].to_list() == ["Tag1", "tag\\(2\\)", "TAG 3"]


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_normalize_tags_empty_source(importer: TagDataImporter, sample_case):
    """
    異常系テスト：'source_tag'が空の場合、エラーで戻ることを確認
    """
    # sample_caseの'data'をDataFrameに変換
    df = pl.DataFrame(sample_case["data"])

    # 'source_tag'カラムをNoneに設定して空にする
    source_null = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("source_tag"))

    # メソッドを実行
    with pytest.raises(ValueError) as exc_info:
        importer._normalize_tags(source_null)
    print(exc_info.value)


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_normalize_tags_no_source_tag(importer: TagDataImporter, sample_case):
    """
    異常系テスト：'source_tag'カラムが存在しない場合、例外が発生することを確認
    """
    # sample_caseの'data'をDataFrameに変換
    df = pl.DataFrame(sample_case["data"])

    # 'source_tag'カラムを削除する
    drop_source = df.drop("source_tag")

    # メソッドを実行 tyep_id と count だけのデータフレームを送る
    with pytest.raises(KeyError) as exc_info:
        importer._normalize_tags(drop_source)
    print(exc_info.value)


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_add_tag_id_column_normal(importer, sample_case):
    """正常系テスト：タグIDが正常に追加される場合"""
    # テスト用のデータフレームを作成
    df = pl.DataFrame({"tag": ["tag1", "tag2"]})

    with patch("genai_tag_db_tools.core.import_data.TagSearcher") as MockTagSearcher:
        mock_searcher = MockTagSearcher.return_value
        mock_searcher.find_tag_id.side_effect = [1, 2]

        # メソッドを実行
        df = importer._add_tag_id_column(df)

        # tag_idカラムが追加され、正しい値が設定されていることを確認
        assert "tag_id" in df.columns
        assert df["tag_id"].to_list() == [1, 2]


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_add_tag_id_column_abnormal(importer: TagDataImporter, sample_case):
    """異常系テスト：タグIDが取得できない場合"""
    # テスト用のデータフレームを作成（存在しないタグを含む）
    df = pl.DataFrame({"tag": ["tag1", "unknown_tag"]})

    # TagSearcherをモック化
    with patch("genai_tag_db_tools.core.import_data.TagSearcher") as MockTagSearcher:
        mock_searcher = MockTagSearcher.return_value
        # 一つ目のタグはIDを返し、二つ目はNoneを返す
        mock_searcher.find_tag_id.side_effect = [1, None]

        # メソッドを実行
        df = importer._add_tag_id_column(df)

        # tag_idカラムが追加され、Noneが含まれていることを確認
        assert "tag_id" in df.columns
        assert df["tag_id"].to_list() == [1, None]

        # None値が含まれている場合の処理を追加で確認する場合
        assert df["tag_id"].null_count() == 1


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_normalize_translation_normal(importer, sample_case):
    """翻訳の処理をテスト"""
    # テスト用のデータフレームを作成
    df = pl.DataFrame(
        {
            "source_tag": ["tag1", "tag2"],
            "Japanese": ["trans1", "trans2, trans3"],
        }
    )

    # メソッドを実行
    df = importer._normalize_translations(df)
    # 翻訳が正しく正規化されていることを確認するアサーションを追加してください
    # 例: assert df["translation"].to_list() == ["trans1", "trans2, trans3"]


def test_cancel_import(importer: TagDataImporter):
    """インポートのキャンセルをテスト"""
    importer.cancel()
    assert importer._cancel_flag is True


def test_import_data_signals(
    importer: TagDataImporter, sample_df, sample_config: ImportConfig
):
    """インポートデータのシグナルをテスト"""
    progress_signal = MagicMock()
    start_signal = MagicMock()
    finish_signal = MagicMock()

    importer.progress_updated.connect(progress_signal)
    importer.process_started.connect(start_signal)
    importer.process_finished.connect(finish_signal)

    importer.import_data(sample_df, sample_config)

    start_signal.assert_called_once_with("import")
    assert progress_signal.called
    finish_signal.assert_called_once_with("import")
