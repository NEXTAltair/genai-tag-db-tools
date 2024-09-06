# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'MainWindow.ui'
##
## Created by: Qt User Interface Compiler version 6.7.2
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
from PySide6.QtWidgets import (QApplication, QMainWindow, QSizePolicy, QStatusBar,
    QTabWidget, QVBoxLayout, QWidget)

from TagCleanerWidget import TagCleanerWidget
from TagRegisterWidget import TagRegisterWidget
from TagSearchWidget import TagSearchWidget
from TagStatisticsWidget import TagStatisticsWidget

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1000, 600)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.tabWidget = QTabWidget(self.centralwidget)
        self.tabWidget.setObjectName(u"tabWidget")
        self.tagSearch = TagSearchWidget()
        self.tagSearch.setObjectName(u"tagSearch")
        self.tabWidget.addTab(self.tagSearch, "")
        self.tagClesner = TagCleanerWidget()
        self.tagClesner.setObjectName(u"tagClesner")
        self.tabWidget.addTab(self.tagClesner, "")
        self.tagRegister = TagRegisterWidget()
        self.tagRegister.setObjectName(u"tagRegister")
        self.tabWidget.addTab(self.tagRegister, "")
        self.tagStatistics = TagStatisticsWidget()
        self.tagStatistics.setObjectName(u"tagStatistics")
        self.tabWidget.addTab(self.tagStatistics, "")

        self.verticalLayout.addWidget(self.tabWidget)

        MainWindow.setCentralWidget(self.centralwidget)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)

        self.tabWidget.setCurrentIndex(2)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"\u30bf\u30b0\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9\u30c4\u30fc\u30eb", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tagSearch), QCoreApplication.translate("MainWindow", u"\u30bf\u30b0\u691c\u7d22", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tagClesner), QCoreApplication.translate("MainWindow", u"\u30bf\u30b0\u30af\u30ea\u30fc\u30ca\u30fc", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tagRegister), QCoreApplication.translate("MainWindow", u"\u767b\u9332", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tagStatistics), QCoreApplication.translate("MainWindow", u"\u30bf\u30b0\u7d71\u8a08", None))
    # retranslateUi

