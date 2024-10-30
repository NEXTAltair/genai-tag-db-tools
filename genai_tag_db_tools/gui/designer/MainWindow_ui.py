# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'MainWindow.ui'
##
## Created by: Qt User Interface Compiler version 6.8.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (
    QCoreApplication,
    QDate,
    QDateTime,
    QLocale,
    QMetaObject,
    QObject,
    QPoint,
    QRect,
    QSize,
    QTime,
    QUrl,
    Qt,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QFontDatabase,
    QGradient,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets.tag_cleaner import TagCleanerWidget
from ..widgets.tag_register import TagRegisterWidget
from ..widgets.tag_search import TagSearchWidget
from ..widgets.tag_statistics import TagStatisticsWidget


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1000, 600)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName("verticalLayout")
        self.tabWidget = QTabWidget(self.centralwidget)
        self.tabWidget.setObjectName("tabWidget")
        self.tagSearch = TagSearchWidget()
        self.tagSearch.setObjectName("tagSearch")
        self.tabWidget.addTab(self.tagSearch, "")
        self.tagCleaner = TagCleanerWidget()
        self.tagCleaner.setObjectName("tagCleaner")
        self.tabWidget.addTab(self.tagCleaner, "")
        self.tagRegister = TagRegisterWidget()
        self.tagRegister.setObjectName("tagRegister")
        self.tabWidget.addTab(self.tagRegister, "")
        self.tagStatistics = TagStatisticsWidget()
        self.tagStatistics.setObjectName("tagStatistics")
        self.tabWidget.addTab(self.tagStatistics, "")

        self.verticalLayout.addWidget(self.tabWidget)

        MainWindow.setCentralWidget(self.centralwidget)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)

        self.tabWidget.setCurrentIndex(2)

        QMetaObject.connectSlotsByName(MainWindow)

    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(
            QCoreApplication.translate(
                "MainWindow",
                "\u30bf\u30b0\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9\u30c4\u30fc\u30eb",
                None,
            )
        )
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tagSearch),
            QCoreApplication.translate("MainWindow", "\u30bf\u30b0\u691c\u7d22", None),
        )
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tagCleaner),
            QCoreApplication.translate(
                "MainWindow", "\u30bf\u30b0\u30af\u30ea\u30fc\u30ca\u30fc", None
            ),
        )
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tagRegister),
            QCoreApplication.translate("MainWindow", "\u767b\u9332", None),
        )
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tagStatistics),
            QCoreApplication.translate("MainWindow", "\u30bf\u30b0\u7d71\u8a08", None),
        )

    # retranslateUi
