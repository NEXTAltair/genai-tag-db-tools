from PySide6.QtWidgets import (QWidget, QTableWidgetItem, QApplication, 
                               QSlider, QHBoxLayout, QLabel, QVBoxLayout)
from PySide6.QtCore import Qt, Slot
from superqt import QRangeSlider

from TagSearchWidget_ui import Ui_TagSearchWidget
import pandas as pd
import numpy as np
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

class CustomLogScaleSlider(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.slider = QRangeSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue((0, 100))

        self.min_label = QLabel("0")
        self.max_label = QLabel("100,000+")

        labels_layout = QHBoxLayout()
        labels_layout.addWidget(self.min_label)
        labels_layout.addStretch()
        labels_layout.addWidget(self.max_label)

        layout.addWidget(self.slider)
        layout.addLayout(labels_layout)

        self.slider.valueChanged.connect(self.update_labels)

    @Slot()
    def update_labels(self):
        min_val, max_val = self.slider.value()
        min_count = self.scale_to_count(min_val)
        max_count = self.scale_to_count(max_val)
        self.min_label.setText(f"{min_count:,}")
        self.max_label.setText(f"{max_count:,}")

    def scale_to_count(self, value):
        # 対数スケールを使用して値をマッピング
        min_count = 0
        max_count = 100_000
        if value == 0:
            return min_count
        if value == 100:
            return max_count
        log_min = np.log1p(min_count + 1)  # 0を避けるために1を加える
        log_max = np.log1p(max_count)
        log_value = log_min + (log_max - log_min) * (value / 100)
        return int(np.expm1(log_value))

    def get_range(self):
        min_val, max_val = self.slider.value()
        return (self.scale_to_count(min_val), self.scale_to_count(max_val))

class TagSearchWidget(QWidget, Ui_TagSearchWidget):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

    def initialize(self, tag_searcher):
        self.tag_searcher = tag_searcher
        self.initialize_ui()

    def initialize_ui(self):
        # コンボボックスの初期化
        self.comboBoxFormat.addItems(self.tag_searcher.get_tag_formats())
        self.comboBoxLanguage.addItems(self.tag_searcher.get_tag_langs())

        # 使用回数スライダーの初期化
        self.setup_range_slider()

        # フォーマットに対応するタイプの初期化
        self.update_type_combo_box()

    def setup_range_slider(self):
        # 既存のスライダーを削除
        if hasattr(self, 'sliderUsageCount'):
            self.verticalLayout_2.removeWidget(self.sliderUsageCount)
            self.sliderUsageCount.deleteLater()
            self.sliderUsageCount = None

        # 新しいカスタムレンジスライダーを作成
        self.usage_count_slider = CustomLogScaleSlider()
        self.verticalLayout_2.insertWidget(self.verticalLayout_2.indexOf(self.labelUsageCount) + 1, self.usage_count_slider)

    @Slot()
    def on_pushButtonSearch_clicked(self):
        keyword = self.lineEditKeyword.text()
        match_type = "exact" if self.radioButtonExact.isChecked() else "partial"
        format_name = self.comboBoxFormat.currentText()

        # search_tagsメソッドを呼び出し
        results = self.tag_searcher.search_tags(keyword, match_type, format_name)

        # クライアントサイドでのフィルタリング
        filtered_results = self.client_side_filtering(results)

        self.process_search_results(filtered_results)

    def client_side_filtering(self, df: pd.DataFrame) -> pd.DataFrame:
        # タグタイプでフィルタリング
        tag_type = self.comboBoxType.currentText()
        if tag_type and tag_type != 'All' and 'type_name' in df.columns:
            df = df[(df['type_name'] == tag_type) | (df['type_name'].isna()) | (df['type_name'] == '')]
            print(f"After type filtering (type: {tag_type}): {len(df)} rows")

        # 言語でフィルタリング
        language = self.comboBoxLanguage.currentText()
        if language != 'All' and 'language' in df.columns:
            df = df[df['language'] == language]

        # 使用回数でフィルタリング
        min_usage_count, max_usage_count = self.usage_count_slider.get_range()
        if 'usage_count' in df.columns:
            if max_usage_count < 100000:
                df = df[(df['usage_count'] >= min_usage_count) & (df['usage_count'] <= max_usage_count)]
            else:
                df = df[df['usage_count'] >= min_usage_count]

        return df

    def process_search_results(self, results: pd.DataFrame):
        print(f"検索結果の行数: {len(results)}")
        print(f"列名: {results.columns.tolist()}")

        if 'tag' in results.columns and 'usage_count' in results.columns:
            print(results[['tag', 'usage_count']])

        if 'type_name' in results.columns and 'usage_count' in results.columns:
            type_summary = results.groupby('type_name')['usage_count'].sum().sort_values(ascending=False)
            print("タイプ別の使用回数合計:")
            print(type_summary)

        self.display_results(results)

    def display_results(self, results: pd.DataFrame):
        self.tableWidgetResults.setRowCount(len(results))
        self.tableWidgetResults.setColumnCount(len(results.columns))
        self.tableWidgetResults.setHorizontalHeaderLabels(results.columns)

        for row in range(len(results)):
            for col, column_name in enumerate(results.columns):
                item = QTableWidgetItem(str(results.iloc[row][column_name]))
                self.tableWidgetResults.setItem(row, col, item)

        self.tableWidgetResults.resizeColumnsToContents()

    @Slot(int)
    def on_comboBoxFormat_currentIndexChanged(self, index):
        self.update_type_combo_box()

    def update_type_combo_box(self):
        format_name = self.comboBoxFormat.currentText()
        tag_types = self.tag_searcher.get_tag_types(format_name)
        self.comboBoxType.clear()
        self.comboBoxType.addItems(tag_types)

    @Slot()
    def on_pushButtonSaveSearch_clicked(self):
        # 現在の検索条件を保存
        print("保存ボタンがクリックされました。ここに保存ロジックを実装します。")

    @Slot(int)
    def on_comboBoxSavedSearches_currentIndexChanged(self, index):
        # 保存された検索条件を読み込み
        print(f"保存された検索条件 {index} が選択されました。ここに読み込みロジックを実装します。")

if __name__ == "__main__":
    import sys
    from pathlib import Path
    current_dir = Path(__file__).parent
    project_root = current_dir.parent
    sys.path.insert(0, str(project_root))
    from tag_search import initialize_tag_searcher

    app = QApplication(sys.argv)
    tag_searcher = initialize_tag_searcher()
    window = TagSearchWidget()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())