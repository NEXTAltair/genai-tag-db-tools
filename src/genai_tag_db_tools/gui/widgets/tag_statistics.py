# genai_tag_db_tools/gui/widgets/tag_statistics.py

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QStackedBarSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from genai_tag_db_tools.gui.designer.TagStatisticsWidget_ui import Ui_TagStatisticsWidget
from genai_tag_db_tools.gui.presenters.tag_statistics_presenter import (
    BarChartData,
    TagStatisticsView,
    build_statistics_view,
)
from genai_tag_db_tools.services.app_services import TagStatisticsService


class TagStatisticsWidget(QWidget, Ui_TagStatisticsWidget):
    """Show tag statistics using chart widgets."""

    def __init__(
        self,
        parent: QWidget | None = None,
        service: TagStatisticsService | None = None,
    ):
        super().__init__(parent)
        self.setupUi(self)

        self.service = service
        self.view_state: TagStatisticsView | None = None
        self._initialized = False

        self.setup_chart_layouts()
        if hasattr(self, "listWidgetTopTags"):
            self.listWidgetTopTags.hide()

    def set_service(self, service: TagStatisticsService) -> None:
        """Set service instance (initialization deferred to showEvent)."""
        self.service = service
        self._initialized = False

    def showEvent(self, event: QShowEvent) -> None:
        """Widget is shown - ready for user interaction."""
        # Note: Statistics widget doesn't auto-initialize on show,
        # user must click the "Generate" button
        super().showEvent(event)

    @Slot()
    def on_statsGenerateButton_clicked(self) -> None:
        self.initialize()

    def initialize(self) -> None:
        general_stats = self.service.get_general_stats()
        usage_df = self.service.get_usage_stats()
        type_dist_df = self.service.get_type_distribution()
        translation_df = self.service.get_translation_stats()

        self.view_state = build_statistics_view(general_stats, usage_df, type_dist_df, translation_df)
        self.update_statistics(self.view_state)

    def update_statistics(self, view_state: TagStatisticsView | None) -> None:
        if view_state is None:
            return
        self.update_summary(view_state)
        self.update_distribution_chart(view_state.distribution)
        self.update_usage_chart(view_state.usage)
        self.update_language_chart(view_state.language)
        self.update_trends_chart()

    def update_summary(self, view_state: TagStatisticsView) -> None:
        self.labelSummary.setText(view_state.summary_text)

    def update_distribution_chart(self, data: BarChartData | None = None) -> None:
        if data is None:
            return

        chart = QChart()
        chart.setTitle(data.title)

        bar_series = QBarSeries()
        max_val = 0.0
        for series in data.series:
            bar_set = QBarSet(series.name)
            for value in series.values:
                bar_set.append(value)
                max_val = max(max_val, value)
            bar_series.append(bar_set)

        chart.addSeries(bar_series)

        x_axis = QBarCategoryAxis()
        x_axis.append([str(item) for item in data.categories])
        chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        bar_series.attachAxis(x_axis)

        y_axis = QValueAxis()
        y_axis.setLabelFormat("%d")
        y_axis.setRange(0.0, max_val * 1.1 if max_val else 10.0)
        chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        bar_series.attachAxis(y_axis)

        chart_view = QChartView(chart)
        if hasattr(self, "chartLayoutDistribution"):
            self.clear_layout(self.chartLayoutDistribution)
            self.chartLayoutDistribution.addWidget(chart_view)

    def update_usage_chart(self, data: BarChartData | None = None) -> None:
        if data is None:
            return

        chart = QChart()
        chart.setTitle(data.title)
        bar_series = QStackedBarSeries()
        max_val = 0.0
        for series in data.series:
            bar_set = QBarSet(series.name)
            for value in series.values:
                bar_set.append(value)
            bar_series.append(bar_set)

        for idx in range(len(data.categories)):
            total = 0.0
            for series in data.series:
                if idx < len(series.values):
                    total += float(series.values[idx])
            max_val = max(max_val, total)

        chart.addSeries(bar_series)

        x_axis = QBarCategoryAxis()
        x_axis.append([str(item) for item in data.categories])
        chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        bar_series.attachAxis(x_axis)

        y_axis = QValueAxis()
        y_axis.setLabelFormat("%d")
        y_axis.setRange(0.0, max_val * 1.1 if max_val else 10.0)
        chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        bar_series.attachAxis(y_axis)

        chart_view = QChartView(chart)
        if hasattr(self, "chartLayoutUsage"):
            self.clear_layout(self.chartLayoutUsage)
            self.chartLayoutUsage.addWidget(chart_view)

    def update_language_chart(self, data: BarChartData | None = None) -> None:
        if data is None:
            return

        chart = QChart()
        chart.setTitle(data.title)

        bar_series = QBarSeries()
        bar_set = QBarSet(data.series[0].name if data.series else "languages")

        max_val = 0.0
        for value in data.series[0].values if data.series else []:
            bar_set.append(value)
            max_val = max(max_val, value)
        bar_series.append(bar_set)
        chart.addSeries(bar_series)

        x_axis = QBarCategoryAxis()
        x_axis.append(data.categories)
        chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        bar_series.attachAxis(x_axis)

        y_axis = QValueAxis()
        y_axis.setLabelFormat("%d")
        y_axis.setRange(0.0, max_val * 1.1 if max_val else 5.0)
        chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        bar_series.attachAxis(y_axis)

        chart_view = QChartView(chart)
        if hasattr(self, "chartLayoutLanguage"):
            self.clear_layout(self.chartLayoutLanguage)
            self.chartLayoutLanguage.addWidget(chart_view)

    def update_trends_chart(self) -> None:
        if hasattr(self, "labelTrends"):
            self.labelTrends.setText("Trends chart: not implemented")

    def setup_chart_layouts(self) -> None:
        self.chartLayoutDistribution = QVBoxLayout(self.tabDistribution)
        self.chartLayoutDistribution.setObjectName("chartLayoutDistribution")

        self.chartLayoutUsage = QVBoxLayout(self.tabUsage)
        self.chartLayoutUsage.setObjectName("chartLayoutUsage")

        self.chartLayoutLanguage = QVBoxLayout(self.tabLanguage)
        self.chartLayoutLanguage.setObjectName("chartLayoutLanguage")

        self.labelTrends = QLabel(self.tabTrends)
        self.labelTrends.setObjectName("labelTrends")
        trendLayout = QVBoxLayout(self.tabTrends)
        trendLayout.addWidget(self.labelTrends)

    def clear_layout(self, layout: QVBoxLayout | None) -> None:
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
    widget = TagStatisticsWidget()
    widget.initialize()
    widget.show()
    sys.exit(app.exec())
