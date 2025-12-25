# genai_tag_db_tools/gui/widgets/tag_search.py

import logging

import polars as pl
from pydantic import ValidationError
from PySide6.QtCore import QItemSelectionModel, Qt, Signal, Slot
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QSizePolicy,
    QSplitter,
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

    def __init__(self, service: TagSearchService | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setupUi(self)

        self.logger = logging.getLogger(self.__class__.__name__)
        self._service = service
        self._initialized = False
        self._raw_df = None

        self.customSlider = LogScaleRangeSlider()
        layout = QVBoxLayout(self.usageCountSlider)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.customSlider)

        self._results_model = DataFrameTableModel()
        self._results_view = None
        self._results_splitter = None
        self._translation_label = None
        self._translation_language_combo = None
        self._translation_list = None
        self._result_format_label = None
        self._result_format_combo = None
        self._result_count_label = None
        self._setup_results_view()

        self._connect_signals()

    def set_service(self, service: TagSearchService) -> None:
        """Set service instance (initialization deferred to showEvent)."""
        self._service = service
        self._initialized = False

    def showEvent(self, event: QShowEvent) -> None:
        """Initialize UI when widget is first shown."""
        if self._service and not self._initialized:
            self.initialize_ui()
            self._initialized = True
        super().showEvent(event)

    def _connect_signals(self) -> None:
        self.radioButtonExact.setChecked(False)
        self.radioButtonPartial.setChecked(True)
        self.comboBoxFormat.currentIndexChanged.connect(self.update_type_combo_box)
        self.comboBoxLanguage.currentIndexChanged.connect(self._refresh_translation_from_selection)
        if self._result_format_combo is not None:
            self._result_format_combo.currentIndexChanged.connect(self._apply_display_filters)
        if self._translation_language_combo is not None:
            self._translation_language_combo.currentIndexChanged.connect(
                self._refresh_translation_from_selection
            )

    def _setup_results_view(self) -> None:
        self._results_view = QTableView(self.tabList)
        self._results_view.setModel(self._results_model)
        self._results_view.setSortingEnabled(True)
        self._results_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_view.setAlternatingRowColors(True)
        self._results_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._results_view.verticalHeader().setVisible(False)

        self._results_splitter = QSplitter(self.tabList)
        self._results_splitter.setOrientation(Qt.Orientation.Horizontal)

        detail_panel = QWidget(self._results_splitter)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        translation_header = QWidget(detail_panel)
        translation_header_layout = QHBoxLayout(translation_header)
        translation_header_layout.setContentsMargins(0, 0, 0, 0)
        translation_header_layout.setSpacing(6)

        self._translation_label = QLabel(self.tr("Translation (ja)"), translation_header)
        self._translation_language_combo = QComboBox(translation_header)
        self._translation_language_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._translation_language_combo.setMinimumWidth(80)

        translation_header_layout.addWidget(self._translation_label)
        translation_header_layout.addStretch(1)
        translation_header_layout.addWidget(self._translation_language_combo)

        self._translation_list = QListWidget(detail_panel)
        self._translation_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        detail_layout.addWidget(translation_header)
        detail_layout.addWidget(self._translation_list)
        detail_layout.addStretch(1)

        self._results_splitter.addWidget(self._results_view)
        self._results_splitter.addWidget(detail_panel)
        self._results_splitter.setStretchFactor(0, 3)
        self._results_splitter.setStretchFactor(1, 1)

        self._setup_results_filter_bar()
        self.verticalLayout.replaceWidget(self.tableWidgetResults, self._results_splitter)
        self.tableWidgetResults.setParent(None)
        self.tableWidgetResults.deleteLater()

        selection_model = self._results_view.selectionModel()
        if selection_model:
            selection_model.selectionChanged.connect(self._on_results_selection_changed)

    def _setup_results_filter_bar(self) -> None:
        filter_bar = QWidget(self.tabList)
        layout = QHBoxLayout(filter_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._result_format_label = QLabel(self.tr("結果フォーマット:"), filter_bar)
        self._result_format_combo = QComboBox(filter_bar)
        self._result_format_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._result_format_combo.setMinimumWidth(140)
        self._result_count_label = QLabel(self.tr("件数: 0"), filter_bar)

        layout.addWidget(self._result_format_label)
        layout.addWidget(self._result_format_combo)
        layout.addStretch(1)
        layout.addWidget(self._result_count_label)

        filter_bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        filter_bar.setFixedHeight(self._result_format_combo.sizeHint().height() + 6)
        self.verticalLayout.insertWidget(0, filter_bar)

    def initialize_ui(self) -> None:
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItem(self.tr("All"))
        for fmt in self._service.get_tag_formats():
            self.comboBoxFormat.addItem(fmt)

        self.comboBoxLanguage.clear()
        self.comboBoxLanguage.addItem(self.tr("All"))
        languages = self._service.get_tag_languages()
        for lang in languages:
            self.comboBoxLanguage.addItem(lang)

        if self._translation_language_combo is not None:
            self._translation_language_combo.clear()
            if not languages:
                languages = ["ja"]
            seen = set()
            if "zh" not in languages:
                languages = ["zh", *languages]
            for lang in languages:
                if lang in seen:
                    continue
                seen.add(lang)
                self._translation_language_combo.addItem(lang)
            default_index = self._translation_language_combo.findText("ja")
            if default_index >= 0:
                self._translation_language_combo.setCurrentIndex(default_index)

        self.comboBoxType.clear()
        self.comboBoxType.addItem(self.tr("All"))

        if self._result_format_combo is not None:
            self._result_format_combo.clear()
            self._result_format_combo.addItem(self.tr("All"))
            for fmt in self._service.get_tag_formats():
                self._result_format_combo.addItem(fmt)

    def _build_query(self) -> TagSearchQuery:
        min_usage, max_usage = self.customSlider.get_range()
        if min_usage == 0:
            min_usage = None
        if max_usage >= 100_000:
            max_usage = None
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
                format_name=None,
                type_name=query.type_name,
                language=query.language,
                min_usage=query.min_usage,
                max_usage=query.max_usage,
                alias=query.alias,
            )
            self._raw_df = df
            self._apply_display_filters()

        except ValidationError as e:
            self.logger.error("Invalid search parameters: %s", e)
            self.error_occurred.emit(f"検索パラメータが不正です: {e}")
            QMessageBox.critical(self, self.tr("Search Error"), f"Invalid parameters: {e}")
        except FileNotFoundError as e:
            self.logger.warning("Database not found, using cache: %s", e)
            self.error_occurred.emit(f"データベースが見つかりません: {e}")
            QMessageBox.warning(self, self.tr("Database Not Found"), str(e))
        except Exception as e:
            self.logger.exception("Unexpected error during search")
            self.error_occurred.emit(f"予期しないエラー: {e}")
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

    def _apply_display_filters(self, *args) -> None:
        if self._raw_df is None:
            return
        if self._result_format_combo is None:
            return
        format_name = normalize_choice(self._result_format_combo.currentText())
        format_key = format_name.strip().lower() if format_name else None

        rows = []
        for row in self._raw_df.iter_rows(named=True):
            format_statuses = row.get("format_statuses") or {}
            normalized_statuses = {
                str(key).strip().lower(): value for key, value in format_statuses.items()
            }
            if format_key and format_key not in normalized_statuses:
                continue

            status = normalized_statuses.get(format_key) if format_key else None
            if format_key and not isinstance(status, dict):
                continue
            resolved_type_name = status.get("type_name") if status else None
            usage_count = status.get("usage_count") if status else None
            alias = status.get("alias") if status else None
            deprecated = status.get("deprecated") if status else None

            rows.append(
                {
                    "tag": row.get("tag", ""),
                    "type_name": resolved_type_name,
                    "usage_count": usage_count,
                    "alias": alias,
                    "deprecated": deprecated,
                    "translations": row.get("translations") or {},
                }
            )

        df = pl.DataFrame(rows)
        self._results_model.set_dataframe(
            df,
            display_columns=["tag", "type_name", "usage_count", "alias", "deprecated"],
        )
        if self._result_count_label is not None:
            self._result_count_label.setText(self.tr(f"件数: {df.height}"))
        self._select_first_row()

    def _current_translation_language(self) -> str:
        if self._translation_language_combo is not None:
            selected = normalize_choice(self._translation_language_combo.currentText())
        else:
            selected = normalize_choice(self.comboBoxLanguage.currentText())
        return selected or "ja"

    def _select_first_row(self) -> None:
        if self._results_model.rowCount(None) == 0:
            self._clear_translation_details()
            return
        index = self._results_model.index(0, 0)
        self._results_view.setCurrentIndex(index)
        self._results_view.selectionModel().select(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        self._update_translation_details(0)

    def _on_results_selection_changed(self, selected=None, deselected=None) -> None:
        if not self._results_view or not self._results_view.selectionModel():
            return
        rows = self._results_view.selectionModel().selectedRows()
        if not rows:
            self._clear_translation_details()
            return
        self._update_translation_details(rows[0].row())

    def _refresh_translation_from_selection(self, *args) -> None:
        if not self._results_view or not self._results_view.selectionModel():
            return
        rows = self._results_view.selectionModel().selectedRows()
        if not rows:
            self._clear_translation_details()
            return
        self._update_translation_details(rows[0].row())

    def _clear_translation_details(self) -> None:
        if self._translation_label is not None:
            self._translation_label.setText(self.tr("Translation"))
        if self._translation_list is not None:
            self._translation_list.clear()

    def _update_translation_details(self, row: int) -> None:
        if not self._results_model:
            return
        row_data = self._results_model.get_row(row)
        translations = row_data.get("translations") or {}
        language = self._current_translation_language()
        if language.lower() == "zh":
            values = []
            for key, items in translations.items():
                if not key:
                    continue
                if key.lower().startswith("zh"):
                    values.extend(items or [])
        else:
            values = translations.get(language, []) or []

        if self._translation_label is not None:
            self._translation_label.setText(self.tr(f"Translation ({language})"))
        if self._translation_list is not None:
            self._translation_list.clear()
            for value in values:
                self._translation_list.addItem(str(value))

    @Slot()
    def on_pushButtonSaveSearch_clicked(self) -> None:
        self.logger.info("Save search functionality not yet implemented")


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    widget = TagSearchWidget(service=TagSearchService())
    widget.show()
    sys.exit(app.exec())
