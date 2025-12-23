# genai_tag_db_tools/gui/widgets/tag_search.py

import logging

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMessageBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from genai_tag_db_tools.gui.designer.TagSearchWidget_ui import Ui_TagSearchWidget
from genai_tag_db_tools.gui.models.dataframe_table_model import DataFrameTableModel
from genai_tag_db_tools.gui.presenters.tag_search_presenter import (
    TagSearchQuery,
    normalize_choice,
)
from genai_tag_db_tools.gui.widgets.controls.log_scale_slider import LogScaleRangeSlider
from genai_tag_db_tools.services.app_services import TagSearchService


class TagSearchWidget(QWidget, Ui_TagSearchWidget):
    """Tag search UI with injected service and a table model."""

    error_occurred = Signal(str)

    def __init__(self, service: TagSearchService | None = None, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.logger = logging.getLogger(self.__class__.__name__)
        self._service = service

        self.customSlider = LogScaleRangeSlider()
        layout = QVBoxLayout(self.usageCountSlider)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.customSlider)

        self._results_model = DataFrameTableModel()
        self._results_view = None
        self._setup_results_view()

        self._connect_signals()
        if self._service is not None:
            self.initialize_ui()

    def set_service(self, service: TagSearchService) -> None:
        self._service = service
        self.initialize_ui()

    def _connect_signals(self) -> None:
        self.radioButtonExact.setChecked(False)
        self.radioButtonPartial.setChecked(True)
        self.comboBoxFormat.currentIndexChanged.connect(self.update_type_combo_box)

    def _setup_results_view(self) -> None:
        self._results_view = QTableView(self.tabList)
        self._results_view.setModel(self._results_model)
        self._results_view.setSortingEnabled(True)
        self._results_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_view.setAlternatingRowColors(True)
        self._results_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._results_view.verticalHeader().setVisible(False)

        self.verticalLayout.replaceWidget(self.tableWidgetResults, self._results_view)
        self.tableWidgetResults.setParent(None)
        self.tableWidgetResults.deleteLater()

    def initialize_ui(self) -> None:
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItem(self.tr("All"))
        for fmt in self._service.get_tag_formats():
            self.comboBoxFormat.addItem(fmt)

        self.comboBoxLanguage.clear()
        self.comboBoxLanguage.addItem(self.tr("All"))
        for lang in self._service.get_tag_languages():
            self.comboBoxLanguage.addItem(lang)

        self.comboBoxType.clear()
        self.comboBoxType.addItem(self.tr("All"))

    def _build_query(self) -> TagSearchQuery:
        min_usage, max_usage = self.customSlider.get_range()
        return TagSearchQuery(
            keyword=self.lineEditKeyword.text().strip(),
            partial=self.radioButtonPartial.isChecked(),
            format_name=normalize_choice(self.comboBoxFormat.currentText()),
            type_name=normalize_choice(self.comboBoxType.currentText()),
            language=normalize_choice(self.comboBoxLanguage.currentText()),
            min_usage=min_usage,
            max_usage=max_usage,
            alias=None,
        )

    @Slot()
    def on_pushButtonSearch_clicked(self) -> None:
        try:
            query = self._build_query()
            df = self._service.search_tags(
                keyword=query.keyword,
                partial=query.partial,
                format_name=query.format_name,
                type_name=query.type_name,
                language=query.language,
                min_usage=query.min_usage,
                max_usage=query.max_usage,
                alias=query.alias,
            )
            self._results_model.set_dataframe(df)

        except Exception as e:
            self.logger.error("Error in on_search_button_clicked: %s", e)
            self.error_occurred.emit(str(e))
            QMessageBox.critical(self, self.tr("Search Error"), str(e))

    def update_type_combo_box(self) -> None:
        fmt = self.comboBoxFormat.currentText()
        if fmt.lower() == "all":
            tag_types = self._service.get_tag_types(None)
        else:
            tag_types = self._service.get_tag_types(fmt)

        self.comboBoxType.clear()
        self.comboBoxType.addItem(self.tr("All"))
        for tag_type in tag_types:
            self.comboBoxType.addItem(tag_type)

    @Slot()
    def on_pushButtonSaveSearch_clicked(self) -> None:
        print("[on_pushButtonSaveSearch_clicked] TODO: save search")


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    widget = TagSearchWidget(service=TagSearchService())
    widget.show()
    sys.exit(app.exec())
