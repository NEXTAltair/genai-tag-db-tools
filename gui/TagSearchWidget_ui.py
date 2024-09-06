# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'TagSearchWidget.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QRadioButton, QSizePolicy, QSlider,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

class Ui_TagSearchWidget(object):
    def setupUi(self, TagSearchWidget):
        if not TagSearchWidget.objectName():
            TagSearchWidget.setObjectName(u"TagSearchWidget")
        TagSearchWidget.resize(900, 637)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(TagSearchWidget.sizePolicy().hasHeightForWidth())
        TagSearchWidget.setSizePolicy(sizePolicy)
        self.horizontalLayout = QHBoxLayout(TagSearchWidget)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.mainSplitter = QSplitter(TagSearchWidget)
        self.mainSplitter.setObjectName(u"mainSplitter")
        self.mainSplitter.setOrientation(Qt.Orientation.Horizontal)
        self.searchPanel = QWidget(self.mainSplitter)
        self.searchPanel.setObjectName(u"searchPanel")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.searchPanel.sizePolicy().hasHeightForWidth())
        self.searchPanel.setSizePolicy(sizePolicy1)
        self.gridLayout = QGridLayout(self.searchPanel)
        self.gridLayout.setObjectName(u"gridLayout")
        self.groupBoxSearchCriteria = QGroupBox(self.searchPanel)
        self.groupBoxSearchCriteria.setObjectName(u"groupBoxSearchCriteria")
        self.verticalLayout_2 = QVBoxLayout(self.groupBoxSearchCriteria)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.lineEditKeyword = QLineEdit(self.groupBoxSearchCriteria)
        self.lineEditKeyword.setObjectName(u"lineEditKeyword")

        self.verticalLayout_2.addWidget(self.lineEditKeyword)

        self.groupBoxMatchType = QGroupBox(self.groupBoxSearchCriteria)
        self.groupBoxMatchType.setObjectName(u"groupBoxMatchType")
        self.horizontalLayout_2 = QHBoxLayout(self.groupBoxMatchType)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.radioButtonExact = QRadioButton(self.groupBoxMatchType)
        self.radioButtonExact.setObjectName(u"radioButtonExact")

        self.horizontalLayout_2.addWidget(self.radioButtonExact)

        self.radioButtonPartial = QRadioButton(self.groupBoxMatchType)
        self.radioButtonPartial.setObjectName(u"radioButtonPartial")
        self.radioButtonPartial.setChecked(True)

        self.horizontalLayout_2.addWidget(self.radioButtonPartial)


        self.verticalLayout_2.addWidget(self.groupBoxMatchType)

        self.labelFormat = QLabel(self.groupBoxSearchCriteria)
        self.labelFormat.setObjectName(u"labelFormat")

        self.verticalLayout_2.addWidget(self.labelFormat)

        self.comboBoxFormat = QComboBox(self.groupBoxSearchCriteria)
        self.comboBoxFormat.setObjectName(u"comboBoxFormat")

        self.verticalLayout_2.addWidget(self.comboBoxFormat)

        self.labelType = QLabel(self.groupBoxSearchCriteria)
        self.labelType.setObjectName(u"labelType")

        self.verticalLayout_2.addWidget(self.labelType)

        self.comboBoxType = QComboBox(self.groupBoxSearchCriteria)
        self.comboBoxType.setObjectName(u"comboBoxType")

        self.verticalLayout_2.addWidget(self.comboBoxType)

        self.labelLanguage = QLabel(self.groupBoxSearchCriteria)
        self.labelLanguage.setObjectName(u"labelLanguage")

        self.verticalLayout_2.addWidget(self.labelLanguage)

        self.comboBoxLanguage = QComboBox(self.groupBoxSearchCriteria)
        self.comboBoxLanguage.setObjectName(u"comboBoxLanguage")

        self.verticalLayout_2.addWidget(self.comboBoxLanguage)

        self.labelUsageCount = QLabel(self.groupBoxSearchCriteria)
        self.labelUsageCount.setObjectName(u"labelUsageCount")

        self.verticalLayout_2.addWidget(self.labelUsageCount)

        self.sliderUsageCount = QSlider(self.groupBoxSearchCriteria)
        self.sliderUsageCount.setObjectName(u"sliderUsageCount")
        self.sliderUsageCount.setOrientation(Qt.Orientation.Horizontal)

        self.verticalLayout_2.addWidget(self.sliderUsageCount)

        self.pushButtonSearch = QPushButton(self.groupBoxSearchCriteria)
        self.pushButtonSearch.setObjectName(u"pushButtonSearch")

        self.verticalLayout_2.addWidget(self.pushButtonSearch)


        self.gridLayout.addWidget(self.groupBoxSearchCriteria, 0, 0, 1, 1)

        self.groupBoxSavedSearches = QGroupBox(self.searchPanel)
        self.groupBoxSavedSearches.setObjectName(u"groupBoxSavedSearches")
        self.verticalLayout_3 = QVBoxLayout(self.groupBoxSavedSearches)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.comboBoxSavedSearches = QComboBox(self.groupBoxSavedSearches)
        self.comboBoxSavedSearches.setObjectName(u"comboBoxSavedSearches")

        self.verticalLayout_3.addWidget(self.comboBoxSavedSearches)

        self.pushButtonSaveSearch = QPushButton(self.groupBoxSavedSearches)
        self.pushButtonSaveSearch.setObjectName(u"pushButtonSaveSearch")

        self.verticalLayout_3.addWidget(self.pushButtonSaveSearch)


        self.gridLayout.addWidget(self.groupBoxSavedSearches, 1, 0, 1, 1)

        self.mainSplitter.addWidget(self.searchPanel)
        self.tabWidgetResults = QTabWidget(self.mainSplitter)
        self.tabWidgetResults.setObjectName(u"tabWidgetResults")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy2.setHorizontalStretch(2)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.tabWidgetResults.sizePolicy().hasHeightForWidth())
        self.tabWidgetResults.setSizePolicy(sizePolicy2)
        self.tabList = QWidget()
        self.tabList.setObjectName(u"tabList")
        self.verticalLayout = QVBoxLayout(self.tabList)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.tableWidgetResults = QTableWidget(self.tabList)
        self.tableWidgetResults.setObjectName(u"tableWidgetResults")

        self.verticalLayout.addWidget(self.tableWidgetResults)

        self.tabWidgetResults.addTab(self.tabList, "")
        self.tabStatistics = QWidget()
        self.tabStatistics.setObjectName(u"tabStatistics")
        self.verticalLayout_6 = QVBoxLayout(self.tabStatistics)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.ChartPlaceholderWidget = QWidget(self.tabStatistics)
        self.ChartPlaceholderWidget.setObjectName(u"ChartPlaceholderWidget")

        self.verticalLayout_6.addWidget(self.ChartPlaceholderWidget)

        self.tabWidgetResults.addTab(self.tabStatistics, "")
        self.mainSplitter.addWidget(self.tabWidgetResults)

        self.horizontalLayout.addWidget(self.mainSplitter)


        self.retranslateUi(TagSearchWidget)

        self.tabWidgetResults.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(TagSearchWidget)
    # setupUi

    def retranslateUi(self, TagSearchWidget):
        TagSearchWidget.setWindowTitle(QCoreApplication.translate("TagSearchWidget", u"\u30bf\u30b0\u691c\u7d22", None))
        self.groupBoxSearchCriteria.setTitle(QCoreApplication.translate("TagSearchWidget", u"\u691c\u7d22\u6761\u4ef6", None))
        self.lineEditKeyword.setPlaceholderText(QCoreApplication.translate("TagSearchWidget", u"\u30ad\u30fc\u30ef\u30fc\u30c9\u3092\u5165\u529b...", None))
        self.groupBoxMatchType.setTitle(QCoreApplication.translate("TagSearchWidget", u"\u4e00\u81f4\u30bf\u30a4\u30d7", None))
        self.radioButtonExact.setText(QCoreApplication.translate("TagSearchWidget", u"\u5b8c\u5168\u4e00\u81f4", None))
        self.radioButtonPartial.setText(QCoreApplication.translate("TagSearchWidget", u"\u90e8\u5206\u4e00\u81f4", None))
        self.labelFormat.setText(QCoreApplication.translate("TagSearchWidget", u"\u30d5\u30a9\u30fc\u30de\u30c3\u30c8:", None))
        self.labelType.setText(QCoreApplication.translate("TagSearchWidget", u"\u30bf\u30a4\u30d7:", None))
        self.labelLanguage.setText(QCoreApplication.translate("TagSearchWidget", u"\u8a00\u8a9e:", None))
        self.labelUsageCount.setText(QCoreApplication.translate("TagSearchWidget", u"\u4f7f\u7528\u56de\u6570:", None))
        self.pushButtonSearch.setText(QCoreApplication.translate("TagSearchWidget", u"\u691c\u7d22", None))
        self.groupBoxSavedSearches.setTitle(QCoreApplication.translate("TagSearchWidget", u"\u4fdd\u5b58\u3055\u308c\u305f\u691c\u7d22", None))
        self.pushButtonSaveSearch.setText(QCoreApplication.translate("TagSearchWidget", u"\u73fe\u5728\u306e\u691c\u7d22\u3092\u4fdd\u5b58", None))
        self.tabWidgetResults.setTabText(self.tabWidgetResults.indexOf(self.tabList), QCoreApplication.translate("TagSearchWidget", u"\u30ea\u30b9\u30c8\u8868\u793a", None))
        self.tabWidgetResults.setTabText(self.tabWidgetResults.indexOf(self.tabStatistics), QCoreApplication.translate("TagSearchWidget", u"\u7d71\u8a08", None))
    # retranslateUi

