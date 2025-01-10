# genai_tag_db_tools/gui/widgets/tag_statistics.py

from typing import Optional, Any

from PySide6.QtWidgets import QWidget, QListWidgetItem, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Slot
from PySide6.QtCharts import (
    QChartView,
    QChart,
    QBarSeries,
    QBarSet,
    QPieSeries,
    QBarCategoryAxis,
    QValueAxis,
)

import polars as pl

from genai_tag_db_tools.gui.designer.TagStatisticsWidget_ui import Ui_TagStatisticsWidget
from genai_tag_db_tools.services.app_services import TagStatisticsService


def safe_float(val: Any) -> float:
    """
    任意の値を安全にfloat型に変換する

    Args:
        val: 変換する値

    Returns:
        float: 変換後の値。変換できない場合は0.0
    """
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

class TagStatisticsWidget(QWidget, Ui_TagStatisticsWidget):
    """
    Polarsデータを用いて統計情報を表示するウィジェットクラス。
    Qt Designerで作成した UI と連携 (setupUi) し、
    TagStatisticsService から取得した統計情報をチャートやリスト、ラベルへ反映する。
    """

    def __init__(
        self,
        parent=None,
        service: Optional[TagStatisticsService] = None,
    ):
        super().__init__(parent)
        self.setupUi(self)

        # 統計用のサービスクラス (TagStatisticsService) を注入 or デフォルト生成
        self.service = service or TagStatisticsService()

        # 統計結果を保持する変数
        # 例: {
        #   "general": {...},          # dict(総タグ数等)
        #   "usage": pl.DataFrame,     # usage用
        #   "type_dist": pl.DataFrame, # タイプ分布用
        #   "translation": pl.DataFrame, # 翻訳関連
        # }
        self.statistics: dict = {}

        # UI初期化
        self.setup_chart_layouts()  # アンダースコアを削除
        self.initialize_signals()

    def initialize_signals(self):
        """
        サービス側のエラー通知などを受け取りたい場合はシグナル接続する
        """
        self.service.error_occurred.connect(self.on_error_occurred)

    @Slot(str)
    def on_error_occurred(self, msg: str):
        """
        統計取得時等のエラーを受け取る例。
        ポップアップやステータスバー表示などを行うならこちらで。
        """
        print(f"[TagStatisticsWidget] ERROR: {msg}")

    # ----------------------------------------------------------------------
    #  メインフロー
    # ----------------------------------------------------------------------
    def initialize(self):
        """
        ウィジェットの初期化処理:
        1) サービスから統計取得
        2) 結果を self.statistics に格納
        3) update_statistics()でUI反映
        """
        # 1) 統計を取得
        general_stats = self.service.get_general_stats()       # dict
        usage_df = self.service.get_usage_stats()             # pl.DataFrame
        type_dist_df = self.service.get_type_distribution()   # pl.DataFrame
        translation_df = self.service.get_translation_stats()  # pl.DataFrame

        # 2) 取得データを self.statistics に格納
        self.statistics["general"] = general_stats
        self.statistics["usage"] = usage_df
        self.statistics["type_dist"] = type_dist_df
        self.statistics["translation"] = translation_df

        # 3) 画面更新
        self.update_statistics()

    def update_statistics(self):
        """
        self.statistics のデータをもとにGUI部品を更新
        """
        self.update_summary()
        self.update_distribution_chart()
        self.update_usage_chart()
        self.update_language_chart()
        self.update_trends_chart()
        self.update_top_tags()

    # ----------------------------------------------------------------------
    #  個別の表示更新メソッド
    # ----------------------------------------------------------------------
    def update_summary(self):
        """
        総タグ数やエイリアス数などのサマリをラベルに表示
        """
        general = self.statistics["general"]
        summary_text = (
            f"総タグ数: {general['total_tags']}\n"
            f"alias=True タグ数: {general['alias_tags']}\n"
            f"alias=False タグ数: {general['non_alias_tags']}\n"
        )
        self.labelSummary.setText(summary_text)

    def update_distribution_chart(self):
        """
        タイプ分布 (type_dist DataFrame) を棒グラフなどで可視化する例。
        self.chartLayoutDistribution (Qt Designerで配置した QVBoxLayout) に QChartView を追加
        """
        # 1) DataFrame を取得
        type_df: pl.DataFrame = self.statistics["type_dist"]
        # カラム構成: format_name (str), type_name (str), tag_count (int)

        # 2) Pivot して行=type_name, 列=format_name, 値=tag_count
        pivoted = type_df.pivot(
            on="format_name",
            index="type_name",
            values="tag_count",
            aggregate_function="first"
        ).fill_null(0)

        # pivoted のカラムは ["type_name", "danbooru", "e621", ...] 等になる想定
        pivot_cols = pivoted.columns
        if len(pivot_cols) <= 1:
            # データがなければチャート作らず return
            return

        # 先頭列 (pivot index): type_name
        col_type_name = pivot_cols[0]
        format_cols = pivot_cols[1:]  # 後ろがフォーマット名

        # 3) QChart を組み立て
        chart = QChart()
        chart.setTitle("タグタイプ別分布")

        # カテゴリ軸 (type_name)
        # type_name のソート済みリスト
        unique_types = pivoted.select(pl.col(col_type_name)).to_series().to_list()
        # PolarsのSeriesをlistに

        # BarSeries
        bar_series = QBarSeries()

        for fmt_name in format_cols:
            bar_set = QBarSet(fmt_name)
            # pivotedを iter_rows(named=True) で回し、fmt_nameの値を取り出す
            for row in pivoted.iter_rows(named=True):
                # row={ "type_name":..., "danbooru":..., "e621":... }
                val = row[fmt_name]
                # safe_floatを使用して安全に変換
                bar_set.append(safe_float(val))
            bar_series.append(bar_set)

        chart.addSeries(bar_series)

        # X 軸 (type_name)
        x_axis = QBarCategoryAxis()
        x_axis.append([str(t) for t in unique_types])
        chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        bar_series.attachAxis(x_axis)

        # Y 軸
        y_axis = QValueAxis()
        y_axis.setLabelFormat("%d")

        max_val = safe_float(type_df["tag_count"].max())
        y_axis.setRange(0.0, max_val * 1.1 if max_val else 10.0)
        chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        bar_series.attachAxis(y_axis)

        # 4) QChartView を作成してレイアウトに追加
        chart_view = QChartView(chart)
        # 既に chartLayoutDistribution に旧チャートがあるなら削除 or 差し替えが必要かも
        # ここでは単純に addWidget
        if hasattr(self, "chartLayoutDistribution"):
            self.clear_layout(self.chartLayoutDistribution)
            self.chartLayoutDistribution.addWidget(chart_view)

    def update_usage_chart(self):
        """
        使用回数 DataFrame をフォーマット別に合計し、円グラフ(QPieSeries)で可視化する例
        """
        usage_df: pl.DataFrame = self.statistics["usage"]
        # カラム: tag_id(int), format_name(str), usage_count(int)

        if usage_df.is_empty():
            return

        # フォーマット別に usage_count を合計
        grouped = usage_df.group_by("format_name").agg([
            pl.col("usage_count").sum().alias("total_usage")
        ])
        # grouped カラム: [format_name, total_usage]

        # QChart組み立て (円グラフ)
        chart = QChart()
        chart.setTitle("フォーマット別 使用回数合計")
        series = QPieSeries()

        for row in grouped.iter_rows(named=True):
            fmt = row["format_name"]
            val = safe_float(row["total_usage"])
            series.append(fmt, val)

        chart.addSeries(series)
        chart_view = QChartView(chart)

        if hasattr(self, "chartLayoutUsage"):
            self.clear_layout(self.chartLayoutUsage)
            self.chartLayoutUsage.addWidget(chart_view)

    def update_language_chart(self):
        """
        翻訳統計(translation_df)を可視化
        カラム: [tag_id, total_translations, languages(list[str])]
        """
        translation_df: pl.DataFrame = self.statistics["translation"]
        if translation_df.is_empty():
            return

        # languages を explode して言語数をカウント
        # polars 0.17 以降なら
        exploded = translation_df.explode("languages")
        # groupby("languages") で件数カウント
        freq = exploded.group_by("languages").agg([
            pl.count().alias("count")
        ])
        # freq カラム: [languages, tag_id, total_translations] など
        # "tag_id" にレコード数が入るのでリネーム
        freq = freq.rename({"tag_id": "count"}).select(["languages", "count"])
        freq = freq.sort("count", descending=True)

        if freq.is_empty():
            return

        # 棒グラフを作る
        chart = QChart()
        chart.setTitle("言語別翻訳数")
        bar_series = QBarSeries()
        bar_set = QBarSet("Languages")
        categories = []

        for row in freq.iter_rows(named=True):
            lang = row["languages"]
            count = row["count"]
            bar_set.append(safe_float(count))
            categories.append(str(lang))

        bar_series.append(bar_set)
        chart.addSeries(bar_series)

        x_axis = QBarCategoryAxis()
        x_axis.append(categories)
        chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        bar_series.attachAxis(x_axis)

        y_axis = QValueAxis()
        y_axis.setLabelFormat("%d")
        max_val_f = safe_float(freq["count"].max())
        y_axis.setRange(0.0, max_val_f * 1.1 if max_val_f else 5.0)
        chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        bar_series.attachAxis(y_axis)

        chart_view = QChartView(chart)

        if hasattr(self, "chartLayoutLanguage"):
            self.clear_layout(self.chartLayoutLanguage)
            self.chartLayoutLanguage.addWidget(chart_view)

    def update_trends_chart(self):
        """
        トレンド(時系列など)を描画するエリア。
        未実装の場合は簡易メッセージを表示する等
        """
        if hasattr(self, "labelTrends"):
            self.labelTrends.setText("トレンドチャートは未実装です。")

    def update_top_tags(self):
        """
        使用回数の合計が大きいタグ上位を listWidgetTopTags に表示
        usage_df: columns=["tag_id","format_name","usage_count"]
        """
        usage_df: pl.DataFrame = self.statistics["usage"]
        if usage_df.is_empty():
            return

        # 全フォーマット合計でソート → 上位10
        grouped = usage_df.group_by("tag_id").agg([
            pl.col("usage_count").sum().alias("sum_usage")
        ])
        top_10 = grouped.sort("sum_usage", descending=True).head(10)

        self.listWidgetTopTags.clear()
        for row in top_10.iter_rows(named=True):
            t_id = row["tag_id"]
            sum_u = row["sum_usage"]
            item_str = f"TagID={t_id}, usage={sum_u}"
            self.listWidgetTopTags.addItem(QListWidgetItem(item_str))

    # ----------------------------------------------------------------------
    #  レイアウト/チャートの初期化や補助関数
    # ----------------------------------------------------------------------
    def setup_chart_layouts(self):
        """
        各タブウィジェットにチャート表示用のレイアウトを追加
        """
        # 分布タブ
        self.chartLayoutDistribution = QVBoxLayout(self.tabDistribution)
        self.chartLayoutDistribution.setObjectName("chartLayoutDistribution")

        # 使用頻度タブ
        self.chartLayoutUsage = QVBoxLayout(self.tabUsage)
        self.chartLayoutUsage.setObjectName("chartLayoutUsage")

        # 言語タブ
        self.chartLayoutLanguage = QVBoxLayout(self.tabLanguage)
        self.chartLayoutLanguage.setObjectName("chartLayoutLanguage")

        # トレンドタブ
        self.labelTrends = QLabel(self.tabTrends)
        self.labelTrends.setObjectName("labelTrends")
        trendLayout = QVBoxLayout(self.tabTrends)
        trendLayout.addWidget(self.labelTrends)

    def clear_layout(self, layout):
        """
        レイアウトに既に追加されているウィジェットを全て削除する補助メソッド。
        同じ領域に新しいチャートを再配置したい場合などに利用。
        """
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # ウィジェット生成
    widget = TagStatisticsWidget()
    widget.initialize()  # 統計データを取得 & 画面更新
    widget.show()

    sys.exit(app.exec())
