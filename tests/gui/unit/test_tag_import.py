# tests/gui/unit/test_tag_import.py

from multiprocessing import process
from unittest.mock import MagicMock, patch

import polars as pl
import pytest  # noqa: F401
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from genai_tag_db_tools.gui.widgets.tag_import import PolarsModel, TagDataImportDialog
from genai_tag_db_tools.services.app_services import TagImportService

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
    service = TagImportService()  # 新しいサービスを用意
    dialog = TagDataImportDialog(data, service=service)
    # マッピングが設定されていないので、"source_tag" が未選択
    assert not dialog.model.hasRequiredMapping("source_tag")
    # インポートボタンは無効化されているはず
    assert not dialog.importButton.isEnabled()
    # SourceTagCheckBoxは未選択であるべき
    assert not dialog.sourceTagCheckBox.isChecked()


def test_polars_model_has_required_mapping():
    """PolarsModelのhasRequiredMappingが正しく動作することを確認するテスト"""
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
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)

    # col1をsource_tagにマッピング
    dialog.model.setMapping(0, "source_tag")
    # formatComboBoxで "danbooru" を選択 (例)
    dialog.formatComboBox.setCurrentText("danbooru")
    # 必須フィールドの検証をトリガー
    dialog.on_sourceTagCheckBox_stateChanged()

    # 必須フィールドが揃ったのでインポートボタンが有効化されていることを確認
    assert dialog.model.hasRequiredMapping("source_tag")
    assert dialog.importButton.isEnabled()

    # TagDataImporter をモック化
    mock_importer = MagicMock()
    monkeypatch.setattr(dialog._service, "_importer", mock_importer)

    # インポートボタンクリックをシミュレート
    dialog.importButton.click()

    # import_data が呼び出されたことを確認
    mock_importer.import_data.assert_called_once()


def test_tag_data_import_dialog_popup_handling(qtbot, monkeypatch):
    """source_tag がマッピングされていて、クリックした時にwarningが呼ばれないことを確認"""
    data = pl.DataFrame({"col1": [1], "col2": [2], "source_tag": [3]})
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)
    dialog.model.setMapping(0, "source_tag")
    dialog.on_sourceTagCheckBox_stateChanged()

    with patch("genai_tag_db_tools.gui.widgets.tag_import.QMessageBox.warning") as mock_warning:
        dialog.importButton.click()
        mock_warning.assert_not_called()


def test_polars_model_header_context_menu(qtbot, monkeypatch):
    """テーブルヘッダ右クリックメニューを開く動作のテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)
    header = dialog.dataPreviewTable.horizontalHeader()

    pos = header.sectionPosition(0)
    point = header.mapToGlobal(header.rect().center())
    with monkeypatch.context() as m:
        m.setattr(QMenu, "exec_", lambda *args, **kwargs: None)
        dialog.showHeaderMenu(point)
    # メソッドがエラーなく実行されればOK


def test_tag_data_import_dialog_show_header_menu(qtbot, monkeypatch):
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)
    header = dialog.dataPreviewTable.horizontalHeader()
    # 指定位置での右クリックをシミュレート
    pos = QPoint(0, 0)
    with monkeypatch.context() as m:
        m.setattr(QMenu, "exec_", lambda *args, **kwargs: None)
        dialog.showHeaderMenu(pos)
    # メソッドがエラーなく実行されることをテスト


def test_header_mapping(qtbot):
    """ヘッダーのマッピングが正しく動作することを確認するテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2], "col3": [3], "col4": [4], "col5": [5]})
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)

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

    # マッピング設定後の確認
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
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)

    qtbot.mouseClick(dialog.cancelButton, Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.close()


def test_update_progress(qtbot):
    """update_progressスロットがウィンドウタイトルを正しく更新することを確認するテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)

    # モックされたインポーターを作成
    mock_importer = MagicMock()
    # ここでは dialog._service._importer を差し替える
    dialog._service._importer = mock_importer

    # progress_updatedシグナルを擬似発火させる
    qtbot.addWidget(dialog)
    dialog.update_progress(50, "Halfway done")

    # ウィンドウタイトルが更新されたことを確認
    # ※ リファクタ後のコードでは "インポート中... 50%, Halfway done" のような表記かもしれない
    #   実際のダイアログ側の実装に合わせて調整してください
    assert dialog.windowTitle().startswith("インポート中")
    assert "50" in dialog.windowTitle()


def test_import_finished(qtbot):
    """インポート完了時にタイトルが更新されることをテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)

    mock_importer = MagicMock()
    dialog._service._importer = mock_importer

    # インポート完了処理を直接呼び出し
    qtbot.addWidget(dialog)
    dialog.import_finished("Import process")

    # ウィンドウタイトルが更新されたことを確認
    assert dialog.windowTitle().startswith("インポート完了")


def test_polars_model_set_mapping_emits_signal(qtbot):
    """setMapping が mappingChanged シグナルを発行することを確認するテスト"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    model = PolarsModel(data)

    with qtbot.waitSignals([model.mappingChanged], timeout=1000, raising=True) as blocker:
        model.setMapping(0, "source_tag")

    assert blocker.signal_triggered


def test_on_importButton_clicked_with_custom_mapping(qtbot, monkeypatch):
    """on_importButton_clickedのテスト。カスタムマッピングが使用されることを確認"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)
    dialog.model.setMapping(0, "source_tag")
    dialog.model.setMapping(1, "custom_tag")

    dialog.formatComboBox.setCurrentText("danbooru")
    dialog.on_sourceTagCheckBox_stateChanged()

    # source_tag が必須フィールドに含まれている
    assert dialog.model.hasRequiredMapping("source_tag")
    # インポートボタンが有効
    assert dialog.importButton.isEnabled()

    mock_importer = MagicMock()
    monkeypatch.setattr(dialog._service, "_importer", mock_importer)

    dialog.importButton.click()

    mock_importer.import_data.assert_called_once()
    called_args = mock_importer.import_data.call_args[0]
    new_df = called_args[0]

    # リネーム後のカラムチェック
    assert new_df.columns == ["source_tag", "custom_tag"]


def test_on_importButton_clicked_with_no_mapping(qtbot, monkeypatch):
    """on_importButton_clickedのテスト。マッピングがない場合、import_dataは呼ばれない"""
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    service = TagImportService()
    dialog = TagDataImportDialog(data, service=service)

    dialog.on_sourceTagCheckBox_stateChanged()

    assert not dialog.model.hasRequiredMapping("source_tag")
    assert not dialog.importButton.isEnabled()

    mock_importer = MagicMock()
    monkeypatch.setattr(dialog._service, "_importer", mock_importer)

    dialog.importButton.click()

    mock_importer.import_data.assert_not_called()
