# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'TagRegisterWidget.ui'
##
## Created by: Qt User Interface Compiler version 6.7.2
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
    QComboBox,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class Ui_TagRegisterWidget(object):
    def setupUi(self, TagRegisterWidget):
        if not TagRegisterWidget.objectName():
            TagRegisterWidget.setObjectName("TagRegisterWidget")
        TagRegisterWidget.resize(400, 500)
        self.verticalLayout = QVBoxLayout(TagRegisterWidget)
        self.verticalLayout.setObjectName("verticalLayout")
        self.lineEditTag = QLineEdit(TagRegisterWidget)
        self.lineEditTag.setObjectName("lineEditTag")

        self.verticalLayout.addWidget(self.lineEditTag)

        self.lineEditSourceTag = QLineEdit(TagRegisterWidget)
        self.lineEditSourceTag.setObjectName("lineEditSourceTag")

        self.verticalLayout.addWidget(self.lineEditSourceTag)

        self.comboBoxFormat = QComboBox(TagRegisterWidget)
        self.comboBoxFormat.setObjectName("comboBoxFormat")

        self.verticalLayout.addWidget(self.comboBoxFormat)

        self.comboBoxType = QComboBox(TagRegisterWidget)
        self.comboBoxType.setObjectName("comboBoxType")

        self.verticalLayout.addWidget(self.comboBoxType)

        self.spinBoxUseCount = QSpinBox(TagRegisterWidget)
        self.spinBoxUseCount.setObjectName("spinBoxUseCount")
        self.spinBoxUseCount.setMaximum(1000000)

        self.verticalLayout.addWidget(self.spinBoxUseCount)

        self.comboBoxLanguage = QComboBox(TagRegisterWidget)
        self.comboBoxLanguage.setObjectName("comboBoxLanguage")
        self.comboBoxLanguage.setEditable(True)

        self.verticalLayout.addWidget(self.comboBoxLanguage)

        self.lineEditTranslation = QLineEdit(TagRegisterWidget)
        self.lineEditTranslation.setObjectName("lineEditTranslation")

        self.verticalLayout.addWidget(self.lineEditTranslation)

        self.pushButtonRegister = QPushButton(TagRegisterWidget)
        self.pushButtonRegister.setObjectName("pushButtonRegister")

        self.verticalLayout.addWidget(self.pushButtonRegister)

        self.textEditOutput = QTextEdit(TagRegisterWidget)
        self.textEditOutput.setObjectName("textEditOutput")
        self.textEditOutput.setReadOnly(True)

        self.verticalLayout.addWidget(self.textEditOutput)

        self.retranslateUi(TagRegisterWidget)

        QMetaObject.connectSlotsByName(TagRegisterWidget)

    # setupUi

    def retranslateUi(self, TagRegisterWidget):
        TagRegisterWidget.setWindowTitle(
            QCoreApplication.translate(
                "TagRegisterWidget", "\u30bf\u30b0\u767b\u9332", None
            )
        )
        self.lineEditTag.setPlaceholderText(
            QCoreApplication.translate("TagRegisterWidget", "\u30bf\u30b0", None)
        )
        self.lineEditSourceTag.setPlaceholderText(
            QCoreApplication.translate("TagRegisterWidget", "\u5143\u30bf\u30b0", None)
        )
        self.comboBoxFormat.setPlaceholderText(
            QCoreApplication.translate(
                "TagRegisterWidget", "\u30d5\u30a9\u30fc\u30de\u30c3\u30c8", None
            )
        )
        self.comboBoxType.setPlaceholderText(
            QCoreApplication.translate("TagRegisterWidget", "\u30bf\u30a4\u30d7", None)
        )
        self.spinBoxUseCount.setPrefix(
            QCoreApplication.translate(
                "TagRegisterWidget", "\u4f7f\u7528\u56de\u6570: ", None
            )
        )
        self.comboBoxLanguage.setPlaceholderText(
            QCoreApplication.translate("TagRegisterWidget", "\u8a00\u8a9e", None)
        )
        self.lineEditTranslation.setPlaceholderText(
            QCoreApplication.translate("TagRegisterWidget", "\u7ffb\u8a33", None)
        )
        self.pushButtonRegister.setText(
            QCoreApplication.translate("TagRegisterWidget", "\u767b\u9332", None)
        )

    # retranslateUi
