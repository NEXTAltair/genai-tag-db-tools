import pytest
import polars as pl
from sqlalchemy import MetaData, Table, Column, Integer, String, create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from pathlib import Path
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Signal

from genai_tag_db_tools.services.import_data import TagDataImporter, ImportConfig
from genai_tag_db_tools.cleanup_str import TagCleaner
from genai_tag_db_tools.config import AVAILABLE_COLUMNS
from genai_tag_db_tools.data.database_schema import TagDatabase

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
        # AVAILABLE_COLUMNS に定義したインポートする情報
        "auto_select_columns": ["source_tag", "type_id", "count"],
        # 自動で選択されなかったカラムは手入力で選択する
        # ["言語", 'tag', 'language', 'translation', 'deprecated_tags', 'created_at', 'updated_at', "フォーマット"]
        "mapping_input": ["", "", "", "", "", "", "", ""],
        "language_input": "",
        "format_id_input": "danbooru",
        # assertのフォーマットID
        "format_id": 1,
        "expected_columns": ["source_tag", "type_id", "count"],
    },
    # ケース 2: 非推奨のバリアントを含むCSV
    {
        "name": "deprecated_tags",
        "data": {
            "tag": ["tag1", "tag2"],
            "deprecated_tags": [["tag_4", "tag_5"], ["tag_6", "tag_7"]],
        },
        "auto_select_columns": ["tag", "deprecated_tags"],
        "mapping_input": ["", "", "", "", "", "", "", "", ""],
        "language_input": "",
        "format_id_input": "danbooru",
        "format_id": 1,
        "expected_columns": ["tag", "deprecated_tags"],
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
        "auto_select_columns": ["source_tag", "type_id", "count", "deprecated_tags"],
        "mapping_input": [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        "language_input": "",
        "format_id_input": "danbooru",
        "format_id": 1,
        "expected_columns": ["source_tag", "type_id", "count", "deprecated_tags"],
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
        "auto_select_columns": [
            "source_tag",
            "count",
            "type_id",
            "created_at",
            "updated_at",
        ],
        "mapping_input": ["", "", "", "", "", ""],
        "language_input": "",
        "format_id_input": "e621",
        "format_id": 2,
        "expected_columns": [
            "source_tag",
            "count",
            "type_id",
            "created_at",
            "updated_at",
        ],
    },
    # ケース 5: 日本語訳CSV
    {
        "name": "japanese_translations",
        "data": {
            "source_tag": ["tag1", "tag2"],
            "Japanese": ["タグ1, タグ2", "タグ3"],
        },
        "auto_select_columns": [
            "source_tag",
        ],
        "mapping_input": [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],  # 欠落しているカラム数に合わせて入力を調整
        "language_input": "Japanese",
        "format_id_input": "",
        "format_id": 0,
        "expected_columns": ["source_tag", "language", "translation"],
    },
    # ケース 6: 中国語訳CSV
    {
        "name": "chinese_translations",
        "data": {
            "source_tag": ["tag1", "tag2"],
            "type_id": [0, 0],
            "zh-Hant": ["標籤1", "標籤2"],
        },
        "auto_select_columns": ["source_tag", "type_id"],
        "mapping_input": ["", "", "", "", "", "", "", "", ""],
        "language_input": "zh-Hant",
        "format_id_input": "",
        "format_id": 0,
        "expected_columns": ["source_tag", "type_id", "language", "translation"],
    },
    # ケース 7: 実際のCSVを抜粋使用したテスト01 `danbooru_241016.csv`
    {
        "name": "danbooru_241016",
        "data": TagDataImporter.read_csv(Path("tests/resource/case_03.csv")),
        "mapping_input": [
            "column_1",
            "",
            "",
            "",
            "column_2",
            "column_3",
            "",
            "",
            "column_4",
            "",
            "",
        ],  # mapping_input の要素数を9個に調整
        "language_input": "",
        "format_id_input": "danbooru",
        "format_id": 1,
        "expected_columns": ["source_tag", "type_id", "count", "deprecated_tags"],
    },
    # ケース 8: 実際のCSVを抜粋使用したテスト02 `e621_tags_jsonl.csv`
    {
        "name": "e621_tags_jsonl",
        "data": TagDataImporter.read_csv(Path("tests/resource/case_04.csv")),
        "mapping_input": [
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        "language_input": "",
        "format_id_input": "e621",
        "format_id": 2,
        "expected_columns": [
            "source_tag",
            "count",
            "type_id",
            "created_at",
            "updated_at",
        ],
    },
    # ケース 9: 実際のhf_datasetを使用したテスト
    # {
    #     "name": "hf_dataset",
    #     "data": TagDataImporter.load_hf_dataset(
    #         "hf://datasets/p1atdev/danbooru-ja-tag-pair-20241015/data/train-00000-of-00001.parquet"
    #     ),
    #     "mapping_input": [
    #         "other_names",
    #         "title",
    #         "",
    #         "",
    #         "",
    #         "",
    #         "",
    #         "",
    #         "",
    #     ],
    #     "language_input": "japanese",
    #     "format_id_input": "danbooru",
    #     "format_id": 1,
    #     "expected_columns": [
    #         "source_tag",
    #         "type",
    #         "language",
    #         "translation",
    #     ],
    # },
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
    # "CASE_09_hf_dataset",
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
        "auto_select_columns": ["", "", "", "", "", "format_id"],
        "mapping_input": ["source_tag", "type_id", "count", "deprecated_tags", ""],
    }
]


# TagDataImporterのインスタンスを作成するためのフィクスチャ
@pytest.fixture(name="importer")
def importer():
    """TagDataImporterのモックを提供するフィクスチャ"""
    with patch("sqlite3.connect"):
        mock_tag_data_importer = TagDataImporter()
        mock_tag_data_importer.conn = MagicMock()
        mock_tag_data_importer.conn.cursor = MagicMock()
        yield mock_tag_data_importer

@pytest.fixture
def importer_db(db_session):
    # 実データベースセッションを使用するインスタンス
    importer = TagDataImporter()
    importer.session = db_session
    return importer

@pytest.fixture(name="sample_df")
def sample_df():
    """サンプルデータフレームを提供するフィクスチャ"""
    return pl.DataFrame(
        {
            "source_tag": ["tag1", "tag2"],
            "type_id": [0, 0],
            "count": [100, 200],
            "deprecated_tags": [["tag_4", "tag_5"], ["tag_6", "tag_7"]],
        }
    )


# ImportConfigのサンプルを提供するフィクスチャ
@pytest.fixture(name="sample_config")
def sample_config():
    """ImportConfigのサンプルを提供するフィクスチャ"""
    return ImportConfig(
        format_id=1,
        language=None,
        column_names=["source_tag", "type_id", "count", "deprecated_tags"],
    )


@pytest.fixture(name="mock_get_format_id")
def mock_get_format_id():
    def side_effect(*args, **kwargs):
        if args[0] == "unknown":
            return 0
        elif args[0] == "danbooru":
            return 1
        elif args[0] == "e621":
            return 2
        elif args[0] == "dripbooru":
            return 3

    with patch(
        "genai_tag_db_tools.services.tag_search.TagSearcher.get_format_id",
        side_effect=side_effect,
    ) as mock_method:
        yield mock_method

def list_required_inputs(source_df: pl.DataFrame) -> list[str]:
    """
    必要な入力をリストアップする

    Args:
        source_df (pl.DataFrame): カラム名を確認するデータフレーム

    Returns:
        list[str]: 必要な入力のリスト
    """
    missing_columns = [col for col in AVAILABLE_COLUMNS if col not in source_df.columns]
    return missing_columns


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_configure_import(importer: TagDataImporter, sample_case, mock_get_format_id):
    """インポート設定メソッドをテスト"""
    # サンプルデータフレームを作成
    df = pl.DataFrame(sample_case["data"])

    # 必要な入力をリストアップして出力
    required_inputs = list_required_inputs(df)
    print(f"必要な入力: {required_inputs}")

    # `self.tag_search.get_format_id` を `mock_get_format_id` でモック
    user_inputs = (
        [sample_case.get("language_input", "")]
        + sample_case["mapping_input"]
        + [sample_case.get("format_id_input", "")]
    )

    with patch.object(importer.tag_search, "get_format_id", mock_get_format_id):
        # 入力をモック化(必要に応じて変更)
        with patch("builtins.input", side_effect=user_inputs):
            add_db_df, config = importer.configure_import(
                df
            )  # 新しいデータフレームを取得

    # 設定が正しく行われていることをアサート
    assert config.format_id == sample_case["format_id"]

    # 追加で、add_db_df が期待通りのカラムを持つことを確認
    print(f"期待されるカラム: {sample_case['expected_columns']}")
    print(f"実際のカラム: {add_db_df.columns}")
    assert set(config.column_names) == set(sample_case["expected_columns"])


def test_get_format_id(importer: TagDataImporter, mock_get_format_id):
    with patch("builtins.input", side_effect=["unknown"]):
        assert importer.get_format_id() == 0
    with patch("builtins.input", side_effect=["danbooru"]):
        assert importer.get_format_id() == 1
    with patch("builtins.input", side_effect=["e621"]):
        assert importer.get_format_id() == 2
    with patch("builtins.input", side_effect=["dripbooru"]):
        assert importer.get_format_id() == 3


def test_normalize_typing(importer: TagDataImporter):
    """タイプの正規化をテスト"""
    # テスト用のデータフレームを作成
    df = pl.DataFrame(
        {
            "deprecated_tags": ["str, で", "格納, されてる"],
            "translation": [["リスト", "で"], ["格納", "されている"]],
        }
    )

    # メソッドを実行
    df_normalized = importer._normalize_typing(df)

    type_dict = df_normalized.schema
    assert type_dict["deprecated_tags"] == pl.List(pl.Utf8)
    assert type_dict["translation"] == pl.List(pl.Utf8)

    # 列をフラット化して比較
    assert df_normalized.select(
        pl.col("deprecated_tags").explode()
    ).to_series().to_list() == [
        "str",
        "で",
        "格納",
        "されてる",
    ]
    assert df_normalized.select(
        pl.col("translation").explode()
    ).to_series().to_list() == [
        "リスト",
        "で",
        "格納",
        "されている",
    ]


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_normalize_typing_param(importer: TagDataImporter, sample_case):
    """タイプの正規化をテスト"""
    df = pl.DataFrame(sample_case["data"])

    # メソッドを実行
    df_normalized = importer._normalize_typing(df)

    # データ型が正しく変換されていることを確認
    for col, expected_type in AVAILABLE_COLUMNS.items():
        if col in df_normalized.columns:
            if expected_type is None:
                raise ValueError(f"無効なデータ型: {expected_type}")
            assert df_normalized.schema[col] == expected_type


def test_normalize_tags_append(importer: TagDataImporter):
    """
    正常系テスト:既に'tag'カラムが存在しない場合、追加されることを確認
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
    異常系テスト:'source_tag'が空の場合、エラーで戻ることを確認
    """
    # sample_caseの'data'をDataFrameに変換
    df = pl.DataFrame(sample_case["data"])

    # 'source_tag'カラムをNoneに設定して空にする
    source_null = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("source_tag"))

    if sample_case["name"] == "deprecated_tags":
        # ケース2ではエラーが発生しないことを確認
        result = importer._normalize_tags(source_null)
    else:
        # その他のケースでは ValueError が発生することを確認
        with pytest.raises(ValueError):
            importer._normalize_tags(source_null)


@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_normalize_tags_no_source_tag(importer: TagDataImporter, sample_case):
    """
    異常系テスト:'source_tag'カラムが存在しない場合、例外が発生することを確認
    """
    # sample_caseの'data'をDataFrameに変換
    df = pl.DataFrame(sample_case["data"])

    # 'source_tag'カラムが存在する場合に削除する
    if "source_tag" in df.columns:
        drop_source = df.drop("source_tag")
    else:
        drop_source = df

    if sample_case["name"] == "deprecated_tags":
        # ケース2ではエラーが発生しないことを確認
        result = importer._normalize_tags(drop_source)
    else:
        # メソッドを実行 tyep_id と count だけのデータフレームを送る
        with pytest.raises(KeyError) as exc_info:
            importer._normalize_tags(drop_source)
        print(exc_info.value)


def test_insert_tags(importer_db, db_session):
    # テストデータ
    df = pl.DataFrame({
        "source_tag": ["1_girl", "blue_eyes", "1_girl", "long_hair"],
        "tag": ["1 girl", "blue eyes", "1 girl", "long hair"]
    })

    # importer_db に既存の db_session を割り当て
    importer_db.session = db_session

    # テスト用のTAGSテーブルを作成
    metadata = MetaData()
    tags_table = Table(
        'TAGS',
        metadata,
        Column('id', Integer, primary_key=True),
        Column('source_tag', String),
        Column('tag', String),
    )
    metadata.create_all(db_session.get_bind())  # データベースにテーブルを作成

    # テスト実行
    result = importer_db.insert_tags(df)

    # アサート
    assert "tag_id" in result.columns
    assert len(result) == len(df)

@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_normalize_translation_normal(importer, sample_case, mock_get_format_id):
    """翻訳の処理をテスト"""
    # テスト用のデータフレームを作成
    case_df = pl.DataFrame(sample_case["data"])

    # `self.tag_search.get_format_id` を `mock_get_format_id` でモック
    user_inputs = (
        [sample_case.get("language_input", "")]
        + sample_case["mapping_input"]
        + [sample_case.get("format_id_input", "")]
    )
    with patch.object(importer.tag_search, "get_format_id", mock_get_format_id):
        # 入力をモック化(必要に応じて変更)
        with patch("builtins.input", side_effect=user_inputs):
            add_db_df, _ = importer.configure_import(case_df)

    if "translation" in add_db_df.columns:
        df_normalized = importer._normalize_typing(add_db_df)
        # 暫定的な tag_id を追加
        df_with_tag_id = df_normalized.with_columns(
            pl.arange(1, df_normalized.height + 1).alias("tag_id")
        )
        df_normalize_translation = importer._normalize_translations(df_with_tag_id)

        # translation 中の カンマ が含まれていないことを確認
        for translation in df_normalize_translation["translation"]:
            if "," in translation:
                print(f"カンマが含まれている翻訳: {translation}")
        assert all(
            "," not in translation
            for translation in df_normalize_translation["translation"]
        )
    else:
        # translation がない場合は何もしない
        assert True

@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_normalize_deprecated_tags(sample_case):
    """
    '_normalize_deprecated_tags' の動作をテストする。

    - 'deprecated_tags' カラムが無いケース → スキップする
    - 'deprecated_tags' が存在するケース → explode で行数が増えることを想定
    - 'tag_id' カラムが存在しない場合、テスト用に仮追加
    - explode 後の 'deprecated_tags' カラムが正しく正規化されているかを検証
    """

    # 今回のケースに 'deprecated_tags' カラムが存在しない場合はテストをスキップ
    if "deprecated_tags" not in sample_case["data"]:
        pytest.skip(f"sample_case '{sample_case['name']}' には 'deprecated_tags' が無いためスキップ")

    # Arrange
    # データフレームを生成
    df_input = pl.DataFrame(sample_case["data"])

    # _normalize_deprecated_tags 内部では "tag_id" も参照して explode するため、
    # もし元データに "tag_id" が無い場合は、暫定的に連番を振って用意しておく
    if "tag_id" not in df_input.columns:
        df_input = df_input.with_columns(
            pl.arange(1, df_input.height + 1).alias("tag_id")
        )

    # テスト対象クラスを初期化（DBセッション不要なら None でOK）
    importer = TagDataImporter(parent=None)

    # Act
    df_output = importer._normalize_deprecated_tags(df_input)

    # Assert
    # 'deprecated_tags' を explode すると、行数が増える可能性があるので、
    # テストでは「元のリストをフラット化した順序」に一致するかを確認
    # まず、期待値のリストをフラット化し、clean_format した結果を作る
    original_nested = sample_case["data"]["deprecated_tags"]  # 例: [["tag_4","tag_5"], ["tag_6","tag_7"]]
    expected_list = []
    for row_list in original_nested:
        expected_list.extend(row_list)  # 2次元配列を1次元に

    # TagCleaner.clean_format() を適用し、実際に _normalize_deprecated_tags と同じ処理に揃える
    expected_list = [TagCleaner.clean_format(t) for t in expected_list]

    # df_output["deprecated_tags"] は explode 後、1行ごとに単一のタグが入る想定
    actual_list = df_output["deprecated_tags"].to_list()

    # 行数が想定どおり（= フラット化した合計数）であること
    assert df_output.height == len(expected_list), (
        f"explode 後の行数が想定外です。"
        f"\n 期待行数: {len(expected_list)}"
        f"\n 実際行数: {df_output.height}"
    )

    # 各行の 'deprecated_tags' が正しく正規化されているか
    assert actual_list == expected_list, (
        f"'deprecated_tags' の正規化結果が期待値と一致しません。"
        f"\n 期待: {expected_list}"
        f"\n 実際: {actual_list}"
    )

@pytest.mark.parametrize("sample_case", sample_data_cases, ids=sample_data_ids)
def test_import_data(
    importer: TagDataImporter, sample_case, sample_config: ImportConfig
):
    """インポートデータのテスト"""
    case_df = pl.DataFrame(sample_case["data"])
    importer.import_data(case_df, sample_config)

    # 途中でキャンセルされていないことを確認
    assert importer._cancel_flag is False


def test_cancel_import(importer: TagDataImporter):
    """インポートのキャンセルをテスト"""
    importer.cancel()
    assert importer._cancel_flag is True


def test_import_data_signals(
    importer: TagDataImporter, sample_df, sample_config: ImportConfig
):
    """インポートデータのシグナルをテスト"""
    importbutton_signal = MagicMock()
    progress_signal = MagicMock()
    start_signal = MagicMock()
    finish_signal = MagicMock()
    error_signal = MagicMock()

    importer.importbutton_clicked.connect(importbutton_signal)
    importer.progress_updated.connect(progress_signal)
    importer.process_started.connect(start_signal)
    importer.process_finished.connect(finish_signal)
    importer.error_occurred.connect(error_signal)

    importer.import_data(sample_df, sample_config)

    start_signal.assert_called_once_with("インポート開始")
    assert progress_signal.called
    finish_signal.assert_called_once_with("インポート終了")

def test_normalize_deprecated_tags_empty(importer: TagDataImporter):
    """
    非推奨タグが空の場合のテスト
    """
    # テスト用のデータフレームを作成
    df = pl.DataFrame(
        {
            "tag_id": [1, 2],
            "deprecated_tags": [None, None],
        }
    )

    # メソッドを実行
    df_normalized = importer._normalize_deprecated_tags(df)

    # 非推奨タグが空の場合は空のままであることを確認
    assert df_normalized["deprecated_tags"].to_list() == [None, None]


def test_normalize_deprecated_tags_no_column(importer: TagDataImporter):
    """
    非推奨タグのカラムが存在しない場合のテスト
    """
    # テスト用のデータフレームを作成
    df = pl.DataFrame(
        {
            "tag_id": [1, 2],
        }
    )

    # メソッドを実行
    with pytest.raises(Exception):
        importer._normalize_deprecated_tags(df)

