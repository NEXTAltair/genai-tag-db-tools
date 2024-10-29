from PySide6.QtWidgets import QWidget
import PySide6.QtCharts
from ..designer.TagStatisticsWidget_ui import Ui_TagStatisticsWidget

import pandas as pd
import numpy as np
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

class TagStatisticsWidget(QWidget, Ui_TagStatisticsWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.tag_data = None
        self.statistics = {}
        self.initialize_charts()

    def initialize(self, tag_searcher):
        self.tag_searcher = tag_searcher
        all_tag_ids = self.tag_searcher.get_all_tag_ids()

        # 全タグの情報を取得し、1つのDataFrameに集約
        tag_data_list = []
        for tag_id in all_tag_ids:
            tag_data = self.tag_searcher.get_tag_details(tag_id)
            tag_data_list.append(tag_data)

        self.tag_data = pd.concat(tag_data_list, ignore_index=True)

        # 統計情報を計算
        self.calculate_statistics()

        # 統計情報を更新
        self.update_statistics()

    def calculate_statistics(self):
        self.statistics['total_tags'] = len(self.tag_data)
        self.statistics['unique_tags'] = self.tag_data['tag'].nunique()
        self.statistics['total_usage'] = self.tag_data['total_usage_count'].sum()
        self.statistics['formats'] = self.tag_data['formats'].str.split(',', expand=True).stack().value_counts()
        self.statistics['types'] = self.tag_data['types'].str.split(',', expand=True).stack().value_counts()
        self.statistics['languages'] = self.tag_data['translations'].str.split(',', expand=True).apply(lambda x: x.str.split(':').str[0]).stack().value_counts()
        self.statistics['top_tags'] = self.tag_data.nlargest(10, 'total_usage_count')[['tag', 'total_usage_count']]

    def update_statistics(self):
        self.update_summary()
        self.update_distribution_chart()
        self.update_usage_chart()
        self.update_language_chart()
        self.update_trends_chart()
        self.update_top_tags()

    def update_summary(self):
        summary_text = f"""
        総タグ数: {self.statistics['total_tags']}
        ユニークタグ数: {self.statistics['unique_tags']}
        総使用回数: {self.statistics['total_usage']}
        """
        self.labelSummary.setText(summary_text)

    def initialize_charts(self):
        # ここでチャートの初期化を行う
        pass

    def update_summary(self, tag_searcher):
        # タグ概要の更新
        pass

    def update_distribution_chart(self, tag_searcher):
        # 分布チャートの更新
        pass

    def update_usage_chart(self, tag_searcher):
        # 使用頻度チャートの更新
        pass

    def update_language_chart(self, tag_searcher):
        # 言語チャートの更新
        pass

    def update_trends_chart(self, tag_searcher):
        # トレンドチャートの更新
        pass

    def update_top_tags(self):
        # トップタグリストを更新
        self.listWidgetTopTags.clear()
        for _, row in self.statistics['top_tags'].iterrows():
            self.listWidgetTopTags.addItem(f"{row['tag']}: {row['total_usage_count']}")

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    from tag_search import initialize_tag_searcher

    app = QApplication(sys.argv)
    tag_searcher = initialize_tag_searcher()
    window = TagStatisticsWidget()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())