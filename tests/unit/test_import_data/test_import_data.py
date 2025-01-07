import pytest
from unittest.mock import ANY
import polars as pl
from unittest.mock import MagicMock
from pathlib import Path

from genai_tag_db_tools.services.import_data import TagDataImporter, ImportConfig
from genai_tag_db_tools.data.tag_repository import TagRepository

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
    DBセッションに対しては基本的にモックを使うが、
    必要なら実際のDBを使うパターンに差し替え可能。
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
      - タグ正規化
      - tag_id付与
      - usage_counts の登録
      - etc.
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

    # TagRepository をモック化し、呼び出しを検証
    mock_repo = MagicMock(spec=TagRepository)
    # _fetch_existing_tags_as_mapの戻り値を設定
    mock_repo._fetch_existing_tags_as_map.return_value = {
        "Tag A": 1,
        "Tag B": 2
    }
    importer._tag_repo = mock_repo

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

    # mock_repo の呼び出し確認
    # bulk_insert_tags が正しい引数で呼ばれることを確認
    mock_repo.bulk_insert_tags.assert_called_once()
    call_args = mock_repo.bulk_insert_tags.call_args[0][0]
    assert isinstance(call_args, pl.DataFrame)
    assert set(call_args.columns) == {"source_tag", "tag"}
    # source_tagが空の場合はtagの値をコピー、tagが空の場合はsource_tagをクリーニング
    assert call_args["source_tag"].to_list() == ["Tag_A", "Tag B"]  # 2行目は空なのでtagからコピー
    assert call_args["tag"].to_list() == ["Tag A", "Tag B"]  # 1行目は空なのでsource_tagをクリーニング

    # update_usage_count が正しい引数で呼ばれることを確認
    assert mock_repo.update_usage_count.call_count == 2
    mock_repo.update_usage_count.assert_any_call(
        tag_id=ANY, format_id=1, count=5
    )
    mock_repo.update_usage_count.assert_any_call(
        tag_id=ANY, format_id=1, count=10
    )


def test_import_data_cancel(importer: TagDataImporter):
    """
    キャンセルフラグが立っていると import_data を即座に中断するかの確認
    """
    importer._cancel_flag = True  # 事前にキャンセルフラグをON
    df = pl.DataFrame({"source_tag": ["Tag_C"], "count": [100]})
    config = ImportConfig(format_id=1)

    # Repositoryをモックに
    mock_repo = MagicMock(spec=TagRepository)
    importer._tag_repo = mock_repo

    importer.import_data(df, config)
    # キャンセルされていればタグ登録等が呼ばれない想定
    mock_repo.bulk_insert_tags.assert_not_called()
    mock_repo.update_usage_count.assert_not_called()


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


def test_normalize_tags(importer: TagDataImporter):
    """
    _normalize_tags の内部動作チェック:
    空の source_tag / tag を相互補完し、TagCleaner.clean_formatが呼ばれる
    """
    # テスト用の DataFrame
    df = pl.DataFrame(
        {
            "source_tag": ["Tag_One", ""],
            "tag": ["", "Tag Two"],
        }
    )

    # 実行
    result_df = importer._normalize_tags(df)

    # 「source_tag が空なら tag をコピー」「tag が空なら source_tag clean_formatしてコピー」
    # -> result_df は最終的に両カラム同じ内容になる
    assert result_df["source_tag"].to_list() == ["Tag_One", "Tag Two"]  # clean_formatで `_` → ' '
    assert result_df["tag"].to_list() == ["Tag One", "Tag Two"]


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
