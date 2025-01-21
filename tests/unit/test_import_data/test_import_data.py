import pytest
from unittest.mock import ANY, MagicMock
import polars as pl
from pathlib import Path

from genai_tag_db_tools.services.import_data import TagDataImporter, ImportConfig

"""
本ファイルでは TagDataImporter の主要メソッドを一通りテストします。
 - configure_import
 - import_data (実行フローの検証)
 - cancel (キャンセル機能)
 - シグナルの発火確認
など。
"""


@pytest.fixture
def importer():
    """
    TagDataImporter のインスタンスを返すフィクスチャ。
    TagRegister に対しては基本的にモックを使う。
    """
    importer = TagDataImporter()
    return importer


def test_configure_import_basic(importer: TagDataImporter):
    """
    configure_import で DataFrame と ImportConfig が正しく構築されるか確認。
    """
    df = pl.DataFrame({"source_tag": ["foo"], "tag": ["bar"], "count": [123]})
    # 例: format_id=1 (danbooru), language="ja"
    processed_df, config = importer.configure_import(
        source_df=df, format_id=1, language="ja"
    )

    # DataFrame 側の検証
    assert set(processed_df.columns) == {"source_tag", "tag", "count"}
    # Config 側の検証
    assert config.format_id == 1
    assert config.language == "ja"
    assert set(config.column_names) == {"source_tag", "tag", "count"}


def test_import_data_flow(importer: TagDataImporter):
    """
    import_data の実行フローをテスト:
      - シグナル発火
      - TagRegisterの各メソッド呼び出し
      - 正しい引数での呼び出し確認
    """
    # テスト用DataFrame
    df = pl.DataFrame(
        {
            "source_tag": ["Tag_A", ""],
            "tag": ["", "Tag B"],
            "count": [5, 10],
        }
    )
    config = ImportConfig(format_id=1, language=None)

    # TagRegister をモック化
    mock_register = MagicMock()
    # normalize_tagsの戻り値を設定
    mock_register.normalize_tags.return_value = pl.DataFrame({
        "source_tag": ["Tag A", "Tag B"],
        "tag": ["Tag A", "Tag B"],
        "count": [5, 10]
    })
    # insert_tags_and_attach_idの戻り値を設定
    mock_register.insert_tags_and_attach_id.return_value = pl.DataFrame({
        "source_tag": ["Tag A", "Tag B"],
        "tag": ["Tag A", "Tag B"],
        "count": [5, 10],
        "tag_id": [1, 2]
    })
    importer._register_svc = mock_register

    # シグナルをモックに置き換え
    start_signal = MagicMock()
    finish_signal = MagicMock()
    importer.process_started.connect(start_signal)
    importer.process_finished.connect(finish_signal)

    # 実行
    importer.import_data(df, config)

    # シグナル発火の確認
    start_signal.assert_called_once_with("インポート開始")
    finish_signal.assert_called_once_with("インポート完了")

    # TagRegisterの各メソッド呼び出し確認
    mock_register.normalize_tags.assert_called_once()
    mock_register.insert_tags_and_attach_id.assert_called_once()
    mock_register.update_usage_counts.assert_called_once()

    # update_usage_countsが正しい引数で呼ばれることを確認
    enriched_df = mock_register.insert_tags_and_attach_id.return_value
    mock_register.update_usage_counts.assert_called_once_with(enriched_df, config.format_id)


def test_import_data_cancel(importer: TagDataImporter):
    """
    キャンセルフラグが立っていると import_data を即座に中断するかの確認
    """
    importer._cancel_flag = True  # 事前にキャンセルフラグをON
    df = pl.DataFrame({"source_tag": ["Tag_C"], "count": [100]})
    config = ImportConfig(format_id=1)

    # TagRegisterをモックに
    mock_register = MagicMock()
    importer._register_svc = mock_register

    importer.import_data(df, config)
    # キャンセルされていればタグ登録等が呼ばれない想定
    mock_register.normalize_tags.assert_not_called()
    mock_register.insert_tags_and_attach_id.assert_not_called()
    mock_register.update_usage_counts.assert_not_called()


def test_import_data_signals(importer: TagDataImporter):
    """
    シグナルが正しく発火するか単体テスト。
    """
    # シグナルをモック化
    start_signal = MagicMock()
    finish_signal = MagicMock()
    error_signal = MagicMock()

    importer.process_started.connect(start_signal)
    importer.process_finished.connect(finish_signal)
    importer.error_occurred.connect(error_signal)

    # テスト用の最低限 DataFrame
    df = pl.DataFrame({"source_tag": ["Tag_X"], "tag": ["Tag X"]})
    config = ImportConfig(format_id=0)

    # TagRegisterをモック化
    mock_register = MagicMock()
    mock_register.normalize_tags.return_value = df
    mock_register.insert_tags_and_attach_id.return_value = df
    importer._register_svc = mock_register

    importer.import_data(df, config)

    # start, finish は呼ばれる
    start_signal.assert_called_once_with("インポート開始")
    finish_signal.assert_called_once_with("インポート完了")
    # エラーは発生していないので error_signal は呼ばれないはず
    error_signal.assert_not_called()


def test_cancel(importer: TagDataImporter):
    """
    cancel() メソッドがフラグを立てるだけになっているかを確認
    """
    assert importer._cancel_flag is False
    importer.cancel()
    assert importer._cancel_flag is True


def test_configure_import_no_columns(importer: TagDataImporter):
    """
    source_df に 'source_tag' や 'tag' がまったく存在しない場合でも
    _ensure_minimum_columns が動作してカラムを追加することを確認
    """
    df = pl.DataFrame({"count": [1, 2, 3]})
    processed_df, config = importer.configure_import(df)

    assert "source_tag" in processed_df.columns
    assert "tag" in processed_df.columns
    # 入ってないので空文字カラムとして追加されているはず
    assert processed_df["source_tag"].to_list() == ["", "", ""]
    assert processed_df["tag"].to_list() == ["", "", ""]


def test_decide_csv_header(importer: TagDataImporter, tmp_path: Path):
    """
    decide_csv_header() が1行目の文字列を確認して
    AVAILABLE_COLUMNS に該当する文字列があるかどうかでヘッダ有無を判断する。
    """
    # 仮の CSV ファイルを作成
    csv_file = tmp_path / "test.csv"

    # 例1: カラム名が含まれている -> ヘッダあり (True)
    csv_file.write_text("source_tag,count\nTag_A,100\nTag_B,200\n", encoding="utf-8")
    assert importer.decide_csv_header(csv_file) is True

    # 例2: カラム名が含まれない -> ヘッダなし (False)
    csv_file.write_text("aaa,bbb\nccc,ddd\n", encoding="utf-8")
    assert importer.decide_csv_header(csv_file) is False


def test_read_csv(importer: TagDataImporter, tmp_path: Path):
    """
    read_csv() でCSV読み込みが正常動作するか確認
    """
    # 仮の CSVファイル
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("source_tag,count\ntag_a,10\ntag_b,20\n", encoding="utf-8")

    # ヘッダありで読み込み
    df = importer.read_csv(csv_file, has_header=True)
    assert len(df) == 2
    assert df.columns == ["source_tag", "count"]

    # ヘッダなしで読み込み
    df = importer.read_csv(csv_file, has_header=False)
    assert len(df) == 3  # ヘッダ行も1行として読み込まれる
