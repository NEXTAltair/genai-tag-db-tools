# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'TagStatisticsWidget.ui'
##
## Created by: Qt User Interface Compiler version 6.8.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QLabel, QListWidget, QListWidgetItem,
    QSizePolicy, QTabWidget, QVBoxLayout, QWidget)

class Ui_TagStatisticsWidget(object):
    def setupUi(self, TagStatisticsWidget):
        if not TagStatisticsWidget.objectName():
            TagStatisticsWidget.setObjectName(u"TagStatisticsWidget")
        TagStatisticsWidget.resize(400, 300)
        self.verticalLayout = QVBoxLayout(TagStatisticsWidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.labelSummary = QLabel(TagStatisticsWidget)
        self.labelSummary.setObjectName(u"labelSummary")

        self.verticalLayout.addWidget(self.labelSummary)

        self.tabWidgetCharts = QTabWidget(TagStatisticsWidget)
        self.tabWidgetCharts.setObjectName(u"tabWidgetCharts")
        self.tabDistribution = QWidget()
        self.tabDistribution.setObjectName(u"tabDistribution")
        self.tabWidgetCharts.addTab(self.tabDistribution, "")
        self.tabUsage = QWidget()
        self.tabUsage.setObjectName(u"tabUsage")
        self.tabWidgetCharts.addTab(self.tabUsage, "")
        self.tabLanguage = QWidget()
        self.tabLanguage.setObjectName(u"tabLanguage")
        self.tabWidgetCharts.addTab(self.tabLanguage, "")
        self.tabTrends = QWidget()
        self.tabTrends.setObjectName(u"tabTrends")
        self.tabWidgetCharts.addTab(self.tabTrends, "")

        self.verticalLayout.addWidget(self.tabWidgetCharts)

        self.listWidgetTopTags = QListWidget(TagStatisticsWidget)
        self.listWidgetTopTags.setObjectName(u"listWidgetTopTags")

        self.verticalLayout.addWidget(self.listWidgetTopTags)


        self.retranslateUi(TagStatisticsWidget)

        QMetaObject.connectSlotsByName(TagStatisticsWidget)
    # setupUi

    def retranslateUi(self, TagStatisticsWidget):
        TagStatisticsWidget.setWindowTitle(QCoreApplication.translate("TagStatisticsWidget", u"\u30bf\u30b0\u7d71\u8a08", None))
        self.labelSummary.setText(QCoreApplication.translate("TagStatisticsWidget", u"\u30bf\u30b0\u6982\u8981", None))
        self.tabWidgetCharts.setTabText(self.tabWidgetCharts.indexOf(self.tabDistribution), QCoreApplication.translate("TagStatisticsWidget", u"\u5206\u5e03", None))
        self.tabWidgetCharts.setTabText(self.tabWidgetCharts.indexOf(self.tabUsage), QCoreApplication.translate("TagStatisticsWidget", u"\u4f7f\u7528\u983b\u5ea6", None))
        self.tabWidgetCharts.setTabText(self.tabWidgetCharts.indexOf(self.tabLanguage), QCoreApplication.translate("TagStatisticsWidget", u"\u8a00\u8a9e", None))
        self.tabWidgetCharts.setTabText(self.tabWidgetCharts.indexOf(self.tabTrends), QCoreApplication.translate("TagStatisticsWidget", u"\u30c8\u30ec\u30f3\u30c9", None))
    # retranslateUi

