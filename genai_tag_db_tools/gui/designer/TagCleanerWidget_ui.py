# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'TagCleanerWidget.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget)

class Ui_TagCleanerWidget(object):
    def setupUi(self, TagCleanerWidget):
        if not TagCleanerWidget.objectName():
            TagCleanerWidget.setObjectName(u"TagCleanerWidget")
        TagCleanerWidget.resize(400, 300)
        self.verticalLayout = QVBoxLayout(TagCleanerWidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.labelPrompt = QLabel(TagCleanerWidget)
        self.labelPrompt.setObjectName(u"labelPrompt")

        self.verticalLayout.addWidget(self.labelPrompt)

        self.plainTextEditPrompt = QPlainTextEdit(TagCleanerWidget)
        self.plainTextEditPrompt.setObjectName(u"plainTextEditPrompt")

        self.verticalLayout.addWidget(self.plainTextEditPrompt)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.labelFormat = QLabel(TagCleanerWidget)
        self.labelFormat.setObjectName(u"labelFormat")

        self.horizontalLayout.addWidget(self.labelFormat)

        self.comboBoxFormat = QComboBox(TagCleanerWidget)
        self.comboBoxFormat.setObjectName(u"comboBoxFormat")

        self.horizontalLayout.addWidget(self.comboBoxFormat)

        self.pushButtonConvert = QPushButton(TagCleanerWidget)
        self.pushButtonConvert.setObjectName(u"pushButtonConvert")

        self.horizontalLayout.addWidget(self.pushButtonConvert)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.labelResult = QLabel(TagCleanerWidget)
        self.labelResult.setObjectName(u"labelResult")

        self.verticalLayout.addWidget(self.labelResult)

        self.plainTextEditResult = QPlainTextEdit(TagCleanerWidget)
        self.plainTextEditResult.setObjectName(u"plainTextEditResult")
        self.plainTextEditResult.setReadOnly(True)

        self.verticalLayout.addWidget(self.plainTextEditResult)


        self.retranslateUi(TagCleanerWidget)

        QMetaObject.connectSlotsByName(TagCleanerWidget)
    # setupUi

    def retranslateUi(self, TagCleanerWidget):
        TagCleanerWidget.setWindowTitle(QCoreApplication.translate("TagCleanerWidget", u"\u30bf\u30b0\u30af\u30ea\u30fc\u30ca\u30fc", None))
        self.labelPrompt.setText(QCoreApplication.translate("TagCleanerWidget", u"\u30bf\u30b0\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\uff08\u30ab\u30f3\u30de\u533a\u5207\u308a\uff09\uff1a", None))
        self.plainTextEditPrompt.setPlaceholderText(QCoreApplication.translate("TagCleanerWidget", u"\u4f8b\uff1a1boy, 1girl, \u9752\u9aea, \u8d64\u76ee", None))
        self.labelFormat.setText(QCoreApplication.translate("TagCleanerWidget", u"\u30d5\u30a9\u30fc\u30de\u30c3\u30c8\uff1a", None))
        self.pushButtonConvert.setText(QCoreApplication.translate("TagCleanerWidget", u"\u5909\u63db", None))
        self.labelResult.setText(QCoreApplication.translate("TagCleanerWidget", u"\u5909\u63db\u5f8c\u306e\u30bf\u30b0\uff1a", None))
    # retranslateUi

