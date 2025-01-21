import pytest
import polars as pl
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMenu

# リファクタ後の GUI コードから PolarsModel, TagDataImportDialog をインポート
from genai_tag_db_tools.gui.widgets.tag_import import PolarsModel, TagDataImportDialog

# リファクタ後のサービスクラス
from genai_tag_db_tools.services.app_services import TagImportService, TagCoreService
from genai_tag_db_tools.services.import_data import TagDataImporter, ImportConfig
from genai_tag_db_tools.services.polars_schema import AVAILABLE_COLUMNS
from genai_tag_db_tools.services.tag_search import TagSearcher
from genai_tag_db_tools.data.tag_repository import TagRepository

def test_polars_model_data():
    """
    PolarsModel.data() が正しく文字列を返すかテスト。
    """
    df = pl.DataFrame({"col1": [10], "col2": [20]})
    model = PolarsModel(df)

    # 行0, 列0 → "10"
    assert model.data(model.index(0, 0)) == "10"
    # 行0, 列1 → "20"
    assert model.data(model.index(0, 1)) == "20"


def test_polars_model_mapping_changed(qtbot):
    """
    setMapping() が mappingChanged シグナルを発行することを確認。
    """
    df = pl.DataFrame({"col1": [10], "col2": [20]})
    model = PolarsModel(df)

    with qtbot.waitSignals([model.mappingChanged], timeout=1000) as blocker:
        model.setMapping(0, "source_tag")

    assert blocker.signal_triggered


def test_polars_model_get_mapping():
    """
    getMapping() が '未選択' を除いた辞書を返すことを確認。
    """
    df = pl.DataFrame({"col1": [10], "col2": [20]})
    model = PolarsModel(df)
    model.setMapping(0, "source_tag")  # 列0 → 'source_tag'
    # 列1 は '未選択' のまま

    mapping = model.getMapping()
    assert mapping == {"col1": "source_tag"}
    # col2 は '未選択' のため含まれない。


def create_test_service(db_session):
    """テスト用のサービスを作成するヘルパー関数"""
    def session_factory():
        return db_session
    
    repo = TagRepository(session_factory=session_factory)
    searcher = TagSearcher()
    searcher.tag_repo = repo
    core = TagCoreService(searcher=searcher)
    importer = TagDataImporter(session_factory=session_factory)
    
    return TagImportService(importer=importer, core=core)

def test_tag_data_import_dialog_initial_state(db_session):
    """
    TagDataImportDialog の初期状態を確認。
    - インポートボタンが無効化 (必須フィールド未設定)
    - sourceTagCheckBox などが未選択
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = create_test_service(db_session)
    dialog = TagDataImportDialog(df, service)

    # 初期状態で必須フィールドは未マッピング → importButton 無効
    assert not dialog.importButton.isEnabled()
    assert not dialog.sourceTagCheckBox.isChecked()
def test_import_data_preprocessing(db_session):
    """
    インポートデータの前処理をテスト。
    必須カラムの補完と型変換をテスト。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = create_test_service(db_session)
    
    # 前処理を実行
    processed_df, config = service._importer.configure_import(df, format_id=1)
    
    # 必須カラムが補完されているか確認
    assert "source_tag" in processed_df.columns
    assert "tag" in processed_df.columns
    
    # 補完されたカラムが空文字列で初期化されているか確認
    assert processed_df.select("source_tag").item() == ""
    assert processed_df.select("tag").item() == ""
    
    # 数値カラムの型変換をテスト
    df_with_count = pl.DataFrame({"source_tag": ["tag1"], "count": ["123"]})
    processed_df, _ = service._importer.configure_import(df_with_count, format_id=1)
    assert processed_df.schema["count"] == pl.Int64


def test_import_service_execution(monkeypatch, db_session):
    """
    インポートサービスの実行をテスト。
    GUIに依存せずにサービス層の動作をテスト。
    """
    df = pl.DataFrame({"source_tag": [1], "col2": [2]})
    service = create_test_service(db_session)
    
    # インポーターをモック化
    mock_importer = MagicMock()
    monkeypatch.setattr(service, "_importer", mock_importer)
    
    # インポート実行
    config = ImportConfig(
        format_id=1,
        language="ja",
        column_names=["source_tag", "col2"]
    )
    service.import_data(df, config)
    
    # インポーターが正しく呼び出されたか確認
    mock_importer.import_data.assert_called_once()
    called_df, called_config = mock_importer.import_data.call_args[0]
    assert list(called_df.columns) == ["source_tag", "col2"]
    assert called_config == config


def test_cancel_button_closes_dialog(db_session):
    """
    キャンセルボタンのスロットを呼び出したら QDialog が閉じる(Rejected)かを確認。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = create_test_service(db_session)
    dialog = TagDataImportDialog(df, service)

    # スロットを直接呼び出し
    dialog.on_cancelButton_clicked()
    # ダイアログが閉じることを確認
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_import_service_signals(db_session):
    """
    TagImportServiceのシグナル処理をテスト。
    実際のGUIを使用せずにシグナルの発行と処理をテスト。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = create_test_service(db_session)
    
    # シグナルをモック化
    mock_progress = MagicMock()
    mock_finished = MagicMock()
    mock_error = MagicMock()
    
    service._importer.progress_updated.connect(mock_progress)
    service._importer.process_finished.connect(mock_finished)
    service._importer.error_occurred.connect(mock_error)
    
    # シグナルを発行
    service._importer.progress_updated.emit(50, "Halfway done")
    service._importer.process_finished.emit("test_process")
    service._importer.error_occurred.emit("test error")
    
    # シグナルが正しく処理されたか確認
    mock_progress.assert_called_once_with(50, "Halfway done")
    mock_finished.assert_called_once_with("test_process")
    mock_error.assert_called_once_with("test error")


def test_on_import_error(qtbot, monkeypatch, db_session):
    """
    on_import_error がエラーポップアップを表示し、UIを操作可能にするか。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = create_test_service(db_session)
    dialog = TagDataImportDialog(df, service)

    with patch("genai_tag_db_tools.gui.widgets.tag_import.QMessageBox.critical") as mock_crit:
        dialog.on_import_error("Some error occurred")

        mock_crit.assert_called_once()
        # importButton が操作可能になっている (setControlsEnabled(True)) 前提
        assert dialog.importButton.isEnabled()


def test_model_mapping(db_session):
    """
    PolarsModelのマッピング機能をテスト。
    GUIウィジェットを使用せずにモデルの機能のみをテスト。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    model = PolarsModel(df)

    # カラム0に"source_tag"をマッピング
    model.setMapping(0, "source_tag")
    
    # マッピングが正しく設定されたか確認
    mapping = model.getMapping()
    assert mapping == {"col1": "source_tag"}

    # ヘッダーテキストも確認
    header_text = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
    assert header_text == "col1 → source_tag"
