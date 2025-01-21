import polars as pl
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMenu

# リファクタ後の GUI コードから PolarsModel, TagDataImportDialog をインポート
from genai_tag_db_tools.gui.widgets.tag_import import PolarsModel, TagDataImportDialog

# リファクタ後のサービスクラス
from genai_tag_db_tools.services.app_services import TagImportService

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


def test_tag_data_import_dialog_initial_state():
    """
    TagDataImportDialog の初期状態を確認。
    - インポートボタンが無効化 (必須フィールド未設定)
    - sourceTagCheckBox などが未選択
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()  # 依存性注入
    dialog = TagDataImportDialog(df, service)

    # 初期状態で必須フィールドは未マッピング → importButton 無効
    assert not dialog.importButton.isEnabled()
    assert not dialog.sourceTagCheckBox.isChecked()


def test_on_sourceTagCheckBox_stateChanged_enables_import(qtbot):
    """
    on_sourceTagCheckBox_stateChanged() を呼び出し、
    必須フィールドが設定されたら importButton が有効になるかをテスト。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(df, service)

    # col1 を source_tag にマッピング
    dialog.model.setMapping(0, "source_tag")
    # フォーマット選択 (例: "danbooru")
    dialog.formatComboBox.setCurrentText("danbooru")

    dialog.on_sourceTagCheckBox_stateChanged()
    # この時点で source_tag が必須フィールドに含まれ、かつフォーマット選択済み → importButton 有効
    assert dialog.importButton.isEnabled()


def test_import_button_click_triggers_import_data(qtbot, monkeypatch):
    """
    on_importButton_clicked() が import_data を呼び出すか確認。
    なお、_service._importer をモック化して呼び出し確認を行う。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(df, service)

    # マッピング設定 + フォーマット選択
    dialog.model.setMapping(0, "source_tag")
    dialog.formatComboBox.setCurrentText("danbooru")
    dialog.on_sourceTagCheckBox_stateChanged()
    assert dialog.importButton.isEnabled()

    # モック化
    mock_importer = MagicMock()
    monkeypatch.setattr(dialog._service, "_importer", mock_importer)

    # クリック
    qtbot.mouseClick(dialog.importButton, Qt.MouseButton.LeftButton)
    mock_importer.import_data.assert_called_once()
    # 引数チェックなども可能:
    args, _ = mock_importer.import_data.call_args
    new_df = args[0]  # rename後DataFrame
    assert new_df.columns == ["source_tag", "col2"]


def test_cancel_button_click_closes_dialog(qtbot):
    """
    キャンセルボタンを押したら QDialog が閉じる(Rejected)かを確認。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(df, service)

    qtbot.mouseClick(dialog.cancelButton, Qt.MouseButton.LeftButton)
    # ダイアログが閉じることを確認
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_update_progress(qtbot):
    """
    update_progress でウィンドウタイトルが更新されるかをテスト。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(df, service)

    qtbot.addWidget(dialog)

    # 直接スロットを呼ぶ
    dialog.update_progress(50, "Halfway done")
    assert "インポート中... 50%, Halfway done" in dialog.windowTitle()


def test_import_finished(qtbot):
    """
    import_finished でタイトルが更新され、ダイアログが受理(accept)されるか。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(df, service)

    qtbot.addWidget(dialog)
    dialog.import_finished("some_process")

    assert "インポート完了" in dialog.windowTitle()
    # ダイアログが accept されたか確認
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_on_import_error(qtbot, monkeypatch):
    """
    on_import_error がエラーポップアップを表示し、UIを操作可能にするか。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(df, service)

    with patch("genai_tag_db_tools.gui.widgets.tag_import.QMessageBox.critical") as mock_crit:
        dialog.on_import_error("Some error occurred")

        mock_crit.assert_called_once()
        # importButton が操作可能になっている (setControlsEnabled(True)) 前提
        assert dialog.importButton.isEnabled()


def test_show_header_menu(qtbot, monkeypatch):
    """
    テーブルヘッダを右クリックした時に、カラムマッピング用のメニューが表示されるか。
    QMenu.exec_ をモックにして確認。
    """
    df = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(df, service)
    header = dialog.dataPreviewTable.horizontalHeader()

    pos = header.mapToGlobal(header.rect().center())
    with monkeypatch.context() as m:
        m.setattr(QMenu, "exec_", lambda *a, **kw: None)  # モック
        dialog.showHeaderMenu(pos)
    # エラーにならなければOK
