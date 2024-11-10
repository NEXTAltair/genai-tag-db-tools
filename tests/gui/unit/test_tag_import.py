import pytest
import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog
from genai_tag_db_tools.gui.widgets.tag_import import PolarsModel, TagDataImportDialog

# Ensure QApplication is initialized
app = QApplication.instance()
if app is None:
    app = QApplication([])


def test_polars_model_row_and_column_count():
    data = pl.DataFrame({"col1": [1, 2, 3], "col2": [4, 5, 6]})
    model = PolarsModel(data)
    assert model.rowCount() == 3
    assert model.columnCount() == 2


def test_polars_model_data_display():
    data = pl.DataFrame({"col1": [10, 20], "col2": [30, 40]})
    model = PolarsModel(data)
    index = model.index(0, 0)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "10"


def test_polars_model_header_display():
    data = pl.DataFrame({"columnA": [1, 2], "columnB": [3, 4]})
    model = PolarsModel(data)
    header = model.headerData(0, Qt.Horizontal, Qt.ItemDataRole.DisplayRole)
    assert header == "columnA"


def test_polars_model_set_and_get_mapping():
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    model = PolarsModel(data)
    model.setMapping(0, "source_tag")
    mapping = model.getMapping()
    assert mapping == {"col1": "source_tag"}
    header = model.headerData(0, Qt.Horizontal, Qt.DisplayRole)
    assert header == "col1 → source_tag"


def test_tag_data_import_dialog_initial_state():
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    assert not dialog.ui.importButton.isEnabled()
    assert not dialog.ui.sourceTagCheckBox.isChecked()


def test_tag_data_import_dialog_validate_required_fields():
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    # Map col1 to source_tag
    dialog.model.setMapping(0, "source_tag")
    dialog.validateRequiredFields()
    assert dialog.ui.importButton.isEnabled()
    assert dialog.ui.sourceTagCheckBox.isChecked()


def test_tag_data_import_dialog_on_import_clicked():
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    # Map col1 to source_tag
    dialog.model.setMapping(0, "source_tag")
    # Simulate import button click
    dialog.onImportClicked()
    # Since it's a dialog, after accept(), result should be QDialog.Accepted
    assert dialog.result() == QDialog.Accepted


def test_polars_model_header_context_menu(qtbot, monkeypatch):
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    header = dialog.ui.dataPreviewTable.horizontalHeader()
    # Simulate right-click at column 0
    pos = header.sectionPosition(0)
    point = header.mapToGlobal(header.rect().center())
    with monkeypatch.context() as m:
        m.setattr(QMenu, "exec_", lambda *args, **kwargs: None)
        dialog.showHeaderMenu(point)
    # Since the actual menu execution is mocked, we just test that the method runs without error


def test_tag_data_import_dialog_update_preview():
    data = pl.DataFrame({"col1": [1], "col2": [2]})
    dialog = TagDataImportDialog(data)
    dialog.updatePreview()
    # Since there are no mappings yet, importButton should not be enabled
    assert not dialog.ui.importButton.isEnabled()
    # Now set a mapping and update preview
    dialog.model.setMapping(0, "source_tag")
    dialog.updatePreview()
    assert dialog.ui.importButton.isEnabled()
