# genai_tag_db_tools/gui/widgets/tag_search.py
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QComboBox,
    QRadioButton,
    QGroupBox,
    QGridLayout,
)
from PySide6.QtCore import Qt, Slot, Signal

from superqt import QRangeSlider
import numpy as np


class CustomLogScaleSlider(QWidget):
    """
    使用回数を対数スケールで可視化するRangeSlider。
    ゼロ～10万の範囲を0～100にマッピング。
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


class TagSearchWidget(QWidget):
    """
    TagSearcher を使ってタグ検索＆フィルタリングする簡易UI。
    """
    # エラーや完了等を通知したい場合にシグナルを用意
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.tag_searcher = None
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        # -- Search Condition Area --
        search_group = QGroupBox("Search Conditions")
        search_layout = QGridLayout()

        # キーワード入力
        search_layout.addWidget(QLabel("Keyword:"), 0, 0)
        self.lineEditKeyword = QLineEdit()
        search_layout.addWidget(self.lineEditKeyword, 0, 1, 1, 2)

        # 部分一致 / 完全一致
        self.radioExact = QRadioButton("Exact Match")
        self.radioPartial = QRadioButton("Partial Match")
        self.radioPartial.setChecked(True)  # デフォルトを部分一致に

        search_layout.addWidget(self.radioExact, 1, 0)
        search_layout.addWidget(self.radioPartial, 1, 1)

        # Format 選択
        search_layout.addWidget(QLabel("Format:"), 2, 0)
        self.comboBoxFormat = QComboBox()
        search_layout.addWidget(self.comboBoxFormat, 2, 1)

        # Type 選択
        search_layout.addWidget(QLabel("Type:"), 3, 0)
        self.comboBoxType = QComboBox()
        self.comboBoxType.addItem("All")  # とりあえずAllを追加
        search_layout.addWidget(self.comboBoxType, 3, 1)

        # Language 選択
        search_layout.addWidget(QLabel("Language:"), 4, 0)
        self.comboBoxLanguage = QComboBox()
        self.comboBoxLanguage.addItem("All")  # デフォルト
        search_layout.addWidget(self.comboBoxLanguage, 4, 1)

        # 使用回数ラベル＆スライダー
        self.labelUsageCount = QLabel("Usage Count Range:")
        search_layout.addWidget(self.labelUsageCount, 5, 0)
        self.usageSliderContainer = QWidget()
        self.usageSliderLayout = QVBoxLayout(self.usageSliderContainer)
        self.usage_count_slider = CustomLogScaleSlider()
        self.usageSliderLayout.addWidget(self.usage_count_slider)
        search_layout.addWidget(self.usageSliderContainer, 5, 1, 1, 2)

        # 検索ボタン
        self.buttonSearch = QPushButton("Search")
        self.buttonSearch.clicked.connect(self.on_search_button_clicked)
        search_layout.addWidget(self.buttonSearch, 6, 0, 1, 2)

        search_group.setLayout(search_layout)
        main_layout.addWidget(search_group)

        # -- Result Table --
        self.tableWidgetResults = QTableWidget()
        main_layout.addWidget(self.tableWidgetResults)

        # -- Optional Save/Load Buttons --
        button_layout = QHBoxLayout()
        self.buttonSaveSearch = QPushButton("Save Search")
        self.buttonSaveSearch.clicked.connect(self.on_save_search_clicked)
        self.buttonLoadSearch = QPushButton("Load Search")
        self.buttonLoadSearch.clicked.connect(self.on_load_search_clicked)
        button_layout.addWidget(self.buttonSaveSearch)
        button_layout.addWidget(self.buttonLoadSearch)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

        # コンボボックス変更時に type を更新
        self.comboBoxFormat.currentIndexChanged.connect(self.update_type_combo_box)

    def initialize(self, tag_searcher):
        """
        メインウィンドウなどから TagSearcher を渡して初期化する想定。
        """
        self.tag_searcher = tag_searcher

        # コンボボックス初期化
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItem("All")
        if hasattr(self.tag_searcher, "get_tag_formats"):
            # TagSearcherから取得できるなら追加
            formats = self.tag_searcher.get_tag_formats()  # list[str]
            for fmt in formats:
                self.comboBoxFormat.addItem(fmt)

        self.comboBoxLanguage.clear()
        self.comboBoxLanguage.addItem("All")
        if hasattr(self.tag_searcher, "get_tag_languages"):
            languages = self.tag_searcher.get_tag_languages()  # list[str]
            for lang in languages:
                self.comboBoxLanguage.addItem(lang)

        # タイプ更新
        self.update_type_combo_box()

    @Slot()
    def on_search_button_clicked(self):
        if not self.tag_searcher:
            self.error_occurred.emit("TagSearcher が未初期化です。")
            return

        keyword = self.lineEditKeyword.text().strip()
        match_type = "exact" if self.radioExact.isChecked() else "partial"
        selected_format = self.comboBoxFormat.currentText()

        try:
            # TagSearcher の検索メソッドを呼ぶ
            results = self.tag_searcher.search_tags(
                keyword=keyword,
                match_type=match_type,
                format_name=None if selected_format == "All" else selected_format
            )
            # results は list[dict] や list[モデル] 等を想定

            # クライアントサイド・フィルタリング
            filtered = self.client_side_filtering(results)

            # 結果をテーブル表示
            self.display_results(filtered)

        except Exception as e:
            self.error_occurred.emit(str(e))

    def client_side_filtering(self, results):
        """
        例: list[dict] の検索結果を使用回数/タイプ/言語で絞り込む。
        """
        if not results:
            return []

        # usage_count の範囲
        min_usage, max_usage = self.usage_count_slider.get_range()

        # 選択タイプ
        selected_type = self.comboBoxType.currentText()
        # 選択言語
        selected_lang = self.comboBoxLanguage.currentText()

        filtered = []
        for row in results:
            usage_count = row.get("usage_count", 0)
            type_name = row.get("type_name", "")
            language = row.get("language", "")

            # 使用回数フィルタ
            if usage_count < min_usage:
                continue
            if max_usage < 100000 and usage_count > max_usage:
                continue

            # タイプフィルタ
            if selected_type != "All" and type_name != selected_type:
                continue

            # 言語フィルタ
            if selected_lang != "All" and language != selected_lang:
                continue

            filtered.append(row)

        return filtered

    def display_results(self, results):
        """
        list[dict] をテーブルに表示する。
        """
        if not results:
            self.tableWidgetResults.clear()
            self.tableWidgetResults.setRowCount(0)
            self.tableWidgetResults.setColumnCount(0)
            return

        # dictキー一覧 (一番目の要素からカラム名を取得)
        columns = list(results[0].keys())

        # テーブル初期化
        self.tableWidgetResults.setRowCount(len(results))
        self.tableWidgetResults.setColumnCount(len(columns))
        self.tableWidgetResults.setHorizontalHeaderLabels(columns)

        # セル埋め込み
        for row_idx, row_data in enumerate(results):
            for col_idx, col_name in enumerate(columns):
                cell_value = row_data.get(col_name, "")
                item = QTableWidgetItem(str(cell_value))
                self.tableWidgetResults.setItem(row_idx, col_idx, item)

        self.tableWidgetResults.resizeColumnsToContents()

    @Slot()
    def on_save_search_clicked(self):
        # 現在の検索条件を保存 (実装例は任意)
        print("検索条件を保存する処理を実装してください。")

    @Slot()
    def on_load_search_clicked(self):
        # 保存された検索条件を読み込む (実装例は任意)
        print("保存された検索条件を読み込む処理を実装してください。")

    def update_type_combo_box(self):
        """
        Formatごとにタイプの候補を TagSearcher から取得して設定
        """
        if not self.tag_searcher:
            return

        current_format = self.comboBoxFormat.currentText()
        if current_format == "All":
            # "All"の場合は全タイプを表示
            tag_types = self.tag_searcher.get_tag_types(None)
        else:
            tag_types = self.tag_searcher.get_tag_types(current_format)

        self.comboBoxType.clear()
        self.comboBoxType.addItem("All")
        for t in tag_types:
            self.comboBoxType.addItem(t)

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    from pathlib import Path

    current_dir = Path(__file__).parent
    project_root = current_dir.parent
    sys.path.insert(0, str(project_root))
    from genai_tag_db_tools.services.tag_search import TagSearcher

    app = QApplication(sys.argv)
    tag_searcher = TagSearcher()
    window = TagSearchWidget()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())
