# genai_tag_db_tools/gui/widgets/tag_search.py

import logging

import polars as pl
import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel,QTableWidgetItem,QMessageBox,
)
from PySide6.QtCore import Qt, Slot, Signal

from superqt import QRangeSlider

from genai_tag_db_tools.gui.designer.TagSearchWidget_ui import Ui_TagSearchWidget
# 例: TagSearchService (または TagSearcher などサービス層) を利用
from genai_tag_db_tools.services.app_services import TagSearchService


class CustomLogScaleSlider(QWidget):
    """
    使用回数を対数スケールで可視化する RangeSlider。
    ゼロ～10万の範囲を0～100にマッピング。
    (UI内にはQWidget(usageCountSlider)が配置されており、
     そこにレイアウトを追加して使う)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.slider = QRangeSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue((0, 100))  # 初期は全範囲

        self.min_label = QLabel("0")
        self.max_label = QLabel("100,000+")

        labels_layout = QHBoxLayout()
        labels_layout.addWidget(self.min_label)
        labels_layout.addStretch()
        labels_layout.addWidget(self.max_label)

        layout.addWidget(self.slider)
        layout.addLayout(labels_layout)

        # スライダーが変更されたらラベル更新
        self.slider.valueChanged.connect(self.update_labels)

    @Slot()
    def update_labels(self):
        min_val, max_val = self.slider.value()
        min_count = self.scale_to_count(min_val)
        max_count = self.scale_to_count(max_val)
        self.min_label.setText(f"{min_count:,}")
        self.max_label.setText(f"{max_count:,}")

    def scale_to_count(self, value: int) -> int:
        """
        0〜100 のスライダー値を 0〜100,000 の使用回数に対数変換でマッピングする。
        """
        min_count = 0
        max_count = 100_000
        if value == 0:
            return min_count
        if value == 100:
            return max_count

        log_min = np.log1p(min_count + 1)  # 0を避けるため +1
        log_max = np.log1p(max_count)
        # value / 100 の割合で補間
        log_value = log_min + (log_max - log_min) * (value / 100.0)
        return int(np.expm1(log_value))

    def get_range(self) -> tuple[int, int]:
        """
        スライダーの現在の(最小, 最大)値を実際の使用回数の範囲として返す。
        """
        min_val, max_val = self.slider.value()
        return (self.scale_to_count(min_val), self.scale_to_count(max_val))


class TagSearchWidget(QWidget, Ui_TagSearchWidget):
    """
    QtDesignerの Ui_TagSearchWidget を継承し、
    setupUi(self) で定義されたウィジェットを利用可能にする。
    さらに TagSearchService (DB操作ロジック) を連携し、イベントハンドラを実装する。
    """

    error_occurred = Signal(str)

    def __init__(self, service: TagSearchService, parent=None):
        super().__init__(parent)
        # QtDesignerで自動生成されたUIを適用
        self.setupUi(self)

        self.logger = logging.getLogger(self.__class__.__name__)
        self._service = service

        # usageCountSlider という空の QWidget を
        # CustomLogScaleSlider に差し替える or レイアウトを追加する
        self.customSlider = CustomLogScaleSlider()
        layout = QVBoxLayout(self.usageCountSlider)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.customSlider)

        # シグナル/スロットの接続
        self.init_connections()

        # UI 初期化 (フォーマット・言語など)
        self.initialize_ui()

    def init_connections(self):
        """
        イベントの接続をまとめる
        """
        self.radioButtonExact.setChecked(False)
        self.radioButtonPartial.setChecked(True)  # デフォルトを部分一致
        self.comboBoxFormat.currentIndexChanged.connect(self.update_type_combo_box)

    def initialize_ui(self):
        """
        TagSearchService からフォーマット/言語/タイプなどを取得し、
        コンボボックスを初期化。
        """
        # format
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItem(self.tr("All"))
        for fmt in self._service.get_tag_formats():
            self.comboBoxFormat.addItem(fmt)

        # language
        self.comboBoxLanguage.clear()
        self.comboBoxLanguage.addItem(self.tr("All"))
        for lang in self._service.get_tag_languages():
            self.comboBoxLanguage.addItem(lang)

        # type (最初は "All" のみ。format 選択時に update_type_combo_box() で再設定)
        self.comboBoxType.clear()
        self.comboBoxType.addItem(self.tr("All"))

    @Slot()
    def on_pushButtonSearch_clicked(self):
        """
        [検索] ボタン押下時の処理
        """
        keyword = self.lineEditKeyword.text().strip()
        partial = self.radioButtonPartial.isChecked()
        format_name = self.comboBoxFormat.currentText()
        if format_name.lower() == "all":
            format_name = None

        language = self.comboBoxLanguage.currentText()
        if language.lower() == "all":
            language = None

        type_name = self.comboBoxType.currentText()
        if type_name.lower() == "all":
            type_name = None

        # usage_count range
        min_usage, max_usage = self.customSlider.get_range()

        try:
            df = self._service.search_tags(
                keyword=keyword,
                partial=partial,
                format_name=format_name,
                type_name=type_name,
                language=language,
                min_usage=min_usage,
                max_usage=max_usage,
                alias=None,  # 必要に応じてGUIで設定
            )
            # df は polars の DataFrame

            if df.is_empty():
                self.tableWidgetResults.clear()
                self.tableWidgetResults.setRowCount(0)
                self.tableWidgetResults.setColumnCount(0)
                return

            # テーブル表示
            self.populate_table(df)

        except Exception as e:
            self.logger.error("Error in on_search_button_clicked: %s", e)
            self.error_occurred.emit(str(e))
            QMessageBox.critical(self, self.tr("Search Error"), str(e))

    def populate_table(self, df: pl.DataFrame):
        columns = df.columns
        self.tableWidgetResults.setRowCount(len(df))
        self.tableWidgetResults.setColumnCount(len(columns))
        self.tableWidgetResults.setHorizontalHeaderLabels(columns)

        for row_idx in range(len(df)):
            # row_tuple は (val0, val1, val2, ...)
            row_tuple = df.row(row_idx)  # -> tuple of actual scalar values
            # これで row_tuple[col_idx] すればスカラーが取れる

            for col_idx, col_name in enumerate(columns):
                cell_value = row_tuple[col_idx]  # ここはスカラー
                item = QTableWidgetItem(str(cell_value))
                self.tableWidgetResults.setItem(row_idx, col_idx, item)

        self.tableWidgetResults.resizeColumnsToContents()

    def update_type_combo_box(self):
        """
        フォーマット選択変更時にタグタイプの一覧を更新
        """
        fmt = self.comboBoxFormat.currentText()
        if fmt.lower() == "all":
            # 全タイプ (Service側に "None"指定)
            tag_types = self._service.get_tag_types(None)
        else:
            tag_types = self._service.get_tag_types(fmt)

        self.comboBoxType.clear()
        self.comboBoxType.addItem(self.tr("All"))
        for t in tag_types:
            self.comboBoxType.addItem(t)

    @Slot()
    def on_pushButtonSaveSearch_clicked(self):
        """
        検索条件を保存するボタン
        """
        # 今の検索条件を取得し、どこかに保存...
        print("[on_pushButtonSaveSearch_clicked] 保存ロジックを実装する...")
    # TODO:
    # ここではgroupBoxSavedSearches, comboBoxSavedSearches などを使って
    # 複数の検索条件をロードしたりする処理を追加実装できる。


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # 例: TagSearchServiceを生成
    from genai_tag_db_tools.services.app_services import TagSearchService
    service = TagSearchService()

    widget = TagSearchWidget(service=service)
    widget.show()

    sys.exit(app.exec())
