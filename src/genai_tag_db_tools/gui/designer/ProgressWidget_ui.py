# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ProgressWidget.ui'
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
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget


class Ui_ProgressWidget(object):
    def setupUi(self, ProgressWidget):
        if not ProgressWidget.objectName():
            ProgressWidget.setObjectName("ProgressWidget")
        ProgressWidget.setWindowModality(Qt.WindowModality.WindowModal)
        ProgressWidget.resize(400, 113)
        self.verticalLayout = QVBoxLayout(ProgressWidget)
        self.verticalLayout.setObjectName("verticalLayout")
        self.statusLabel = QLabel(ProgressWidget)
        self.statusLabel.setObjectName("statusLabel")

        self.verticalLayout.addWidget(self.statusLabel, 0, Qt.AlignmentFlag.AlignLeft)

        self.cancelButton = QPushButton(ProgressWidget)
        self.cancelButton.setObjectName("cancelButton")

        self.verticalLayout.addWidget(self.cancelButton, 0, Qt.AlignmentFlag.AlignRight)

        self.retranslateUi(ProgressWidget)

        QMetaObject.connectSlotsByName(ProgressWidget)

    # setupUi

    def retranslateUi(self, ProgressWidget):
        ProgressWidget.setWindowTitle(QCoreApplication.translate("ProgressWidget", "Form", None))
        self.statusLabel.setText(
            QCoreApplication.translate("ProgressWidget", "\u5f85\u6a5f\u4e2d...", None)
        )
        self.cancelButton.setText(
            QCoreApplication.translate("ProgressWidget", "\u30ad\u30e3\u30f3\u30bb\u30eb", None)
        )

    # retranslateUi
