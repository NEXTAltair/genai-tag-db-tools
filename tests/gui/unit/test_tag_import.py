from multiprocessing import process
from unittest import mock
from unittest.mock import MagicMock, patch

import polars as pl
import pytest  # noqa: F401
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from genai_tag_db_tools.gui.widgets.tag_import import PolarsModel, TagDataImportDialog

app = QApplication.instance()
if app is None:
    app = QApplication([])


def test_polars_model_data():
    """PolarsModelのdataメソッドが正しく動作することを確認するテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    model = PolarsModel(data)
    # データの取得
    assert model.data(model.index(0, 0)) == "1"
    assert model.data(model.index(0, 1)) == "2"


def test_tag_data_import_dialog_initial_state():
    """TagDataImportDialogの初期状態が正しいことを確認するテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    # hasRequiredMapping を使用してインポートボタンが無効化されていることを確認
    # "source_tag" が未選択のため、インポートボタンは無効化されている
    assert not dialog.model.hasRequiredMapping("source_tag")
    assert not dialog.importButton.isEnabled()
    # SourceTagCheckBoxは未選択であるべき
    assert not dialog.sourceTagCheckBox.isChecked()


def test_polars_model_has_required_mapping():
    """PolarsModelのhasRequiredMappingが正しく動作することを確認するテスト
    必須フィールドが選択されたときのみ､インポートボタンが有効化されることを確認する
    """
    data = pl.DataFrame({"col1": [1], "col2": [2], "col3": [3]})
    model = PolarsModel(data)

    # マッピング未設定時
    assert not model.hasRequiredMapping("source_tag")

    # col1をsource_tagにマッピング
    model.setMapping(0, "source_tag")
    assert model.hasRequiredMapping("source_tag")

    # 別の必須フィールドをマッピング
    model.setMapping(1, "another_field")
    assert model.hasRequiredMapping("source_tag")

    # source_tagのマッピングを解除
    model.setMapping(0, "未選択")
    assert not model.hasRequiredMapping("source_tag")


def test_tag_data_import_dialog_on_import_button_clicked(qtbot, monkeypatch):
    """TagDataImportDialogのインポートボタンが正しく動作することを確認するテスト"""

    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    # col1をsource_tagにマッピング
    dialog.model.setMapping(0, "source_tag")
    # 必須フィールドの検証をトリガー
    dialog.on_sourceTagCheckBox_stateChanged()
    # hasRequiredMapping を使用してインポートボタンが有効化されていることを確認
    assert dialog.model.hasRequiredMapping("source_tag")
    # インポートボタンが有効化されていることを確認
    assert dialog.importButton.isEnabled()

    # TagDataImporter をモック化
    mock_importer = MagicMock()
    mock_importer.import_data.return_value = None
    monkeypatch.setattr(dialog, "importer", mock_importer)

    # インポートボタンクリックをシミュレート
    dialog.importButton.click()

    # import_data が呼び出されたことを確認
    mock_importer.import_data.assert_called_once()

    # ダイアログが Accepted 状態になっていることを確認
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_tag_data_import_dialog_popup_handling(qtbot, monkeypatch):
    data = pl.DataFrame({"col1": [1], "col2": [2], "source_tag": [3]})
    dialog = TagDataImportDialog(data)
    dialog.model.setMapping(0, "source_tag")
    dialog.on_sourceTagCheckBox_stateChanged()

    with patch(
        "genai_tag_db_tools.gui.widgets.tag_import.QMessageBox.warning"
    ) as mock_warning:
        dialog.importButton.click()
        mock_warning.assert_not_called()  # ポップアップが表示されないことを確認


def test_polars_model_header_context_menu(qtbot, monkeypatch):
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    header = dialog.dataPreviewTable.horizontalHeader()
    # カラムでの右クリックをシミュレート
    pos = header.sectionPosition(0)
    point = header.mapToGlobal(header.rect().center())
    with monkeypatch.context() as m:
        m.setattr(QMenu, "exec_", lambda *args, **kwargs: None)
        dialog.showHeaderMenu(point)
    # 実際のメニュー実行はモック化されているため、メソッドがエラーなく実行されることをテスト


def test_tag_data_import_dialog_show_header_menu(qtbot, monkeypatch):
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    header = dialog.dataPreviewTable.horizontalHeader()
    # 指定位置での右クリックをシミュレート
    pos = QPoint(0, 0)
    with monkeypatch.context() as m:
        m.setattr(QMenu, "exec_", lambda *args, **kwargs: None)
        dialog.showHeaderMenu(pos)
    # メソッドがエラーなく実行されることをテスト


def test_header_mapping(qtbot):
    """ヘッダーのマッピングが正しく動作することを確認するテスト"""
    data = pl.DataFrame(
        {"col1": [1], "col2": [2], "col3": [3], "col4": [4], "col5": [5]}
    )
    dialog = TagDataImportDialog(data)
    # マッピング未設定時
    assert dialog.model._mapping == {
        0: "未選択",
        1: "未選択",
        2: "未選択",
        3: "未選択",
        4: "未選択",
    }
    # マッピング設定
    dialog.model.setMapping(0, "source_tag")
    dialog.model.setMapping(1, "tag_id")
    dialog.model.setMapping(2, "count")
    dialog.model.setMapping(3, "deprecated_tags")
    # マッピング設定後
    assert dialog.model._mapping == {
        0: "source_tag",
        1: "tag_id",
        2: "count",
        3: "deprecated_tags",
        4: "未選択",
    }


def test_on_cancelButton_clicked(qtbot):
    """キャンセルボタンがクリックされたときにダイアログが閉じることを確認するテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    qtbot.mouseClick(dialog.cancelButton, Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.close()


def test_update_progress(qtbot):
    """update_progressスロットがウィンドウタイトルを正しく更新することを確認するテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)

    # モックされたインポーターを作成
    mock_importer = MagicMock()
    dialog.importer = mock_importer

    # progress_updatedシグナルをモック
    def emit_progress(progress, message):
        dialog.update_progress(progress, message)

    mock_importer.progress_updated.connect = MagicMock(
        side_effect=lambda slot: emit_progress
    )

    # シグナルを発行
    qtbot.addWidget(dialog)
    dialog.update_progress(50, "Halfway done")

    # ウィンドウタイトルが更新されたことを確認
    assert dialog.windowTitle() == "インポート中... 50%"


def test_import_finished(qtbot):
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)

    mock_importer = MagicMock()
    dialog.importer = mock_importer

    # インポート完了シグナルをモック
    def emit_process_finished(process_name):
        dialog.import_finished(process_name)

    mock_importer.process_finished.connect = MagicMock(
        side_effect=lambda slot: emit_process_finished
    )

    # シグナルを発行
    qtbot.addWidget(dialog)
    dialog.import_finished("Import process")

    # ウィンドウタイトルが更新されたことを確認
    assert dialog.windowTitle() == "インポート完了"


def test_polars_model_set_mapping_emits_signal(qtbot):
    """setMapping が mappingChanged シグナルを発行することを確認するテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    model = PolarsModel(data)
    with qtbot.waitSignal(model.mappingChanged):
        model.setMapping(0, "source_tag")
