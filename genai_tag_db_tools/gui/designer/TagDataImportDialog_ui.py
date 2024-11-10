# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'TagDataImportDialog.ui'
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QPushButton, QSizePolicy, QSpacerItem, QTableView,
    QVBoxLayout, QWidget)

class Ui_TagDataImportDialog(object):
    def setupUi(self, TagDataImportDialog):
        if not TagDataImportDialog.objectName():
            TagDataImportDialog.setObjectName(u"TagDataImportDialog")
        TagDataImportDialog.resize(800, 600)
        self.verticalLayout = QVBoxLayout(TagDataImportDialog)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.headerLayout = QHBoxLayout()
        self.headerLayout.setObjectName(u"headerLayout")
        self.formatGroupBox = QGroupBox(TagDataImportDialog)
        self.formatGroupBox.setObjectName(u"formatGroupBox")
        self.horizontalLayout = QHBoxLayout(self.formatGroupBox)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.formatComboBox = QComboBox(self.formatGroupBox)
        self.formatComboBox.addItem("")
        self.formatComboBox.setObjectName(u"formatComboBox")

        self.horizontalLayout.addWidget(self.formatComboBox)


        self.headerLayout.addWidget(self.formatGroupBox)

        self.languageGroupBox = QGroupBox(TagDataImportDialog)
        self.languageGroupBox.setObjectName(u"languageGroupBox")
        self.horizontalLayout_2 = QHBoxLayout(self.languageGroupBox)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.languageComboBox = QComboBox(self.languageGroupBox)
        self.languageComboBox.addItem("")
        self.languageComboBox.setObjectName(u"languageComboBox")

        self.horizontalLayout_2.addWidget(self.languageComboBox)


        self.headerLayout.addWidget(self.languageGroupBox)


        self.verticalLayout.addLayout(self.headerLayout)

        self.requiredColumnsGroupBox = QGroupBox(TagDataImportDialog)
        self.requiredColumnsGroupBox.setObjectName(u"requiredColumnsGroupBox")
        self.horizontalLayout_3 = QHBoxLayout(self.requiredColumnsGroupBox)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.sourceTagCheckBox = QCheckBox(self.requiredColumnsGroupBox)
        self.sourceTagCheckBox.setObjectName(u"sourceTagCheckBox")
        self.sourceTagCheckBox.setEnabled(False)
        self.sourceTagCheckBox.setChecked(False)

        self.horizontalLayout_3.addWidget(self.sourceTagCheckBox)

        self.tagCheckBox = QCheckBox(self.requiredColumnsGroupBox)
        self.tagCheckBox.setObjectName(u"tagCheckBox")
        self.tagCheckBox.setEnabled(False)

        self.horizontalLayout_3.addWidget(self.tagCheckBox)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_3.addItem(self.horizontalSpacer_2)


        self.verticalLayout.addWidget(self.requiredColumnsGroupBox)

        self.dataPreviewGroupBox = QGroupBox(TagDataImportDialog)
        self.dataPreviewGroupBox.setObjectName(u"dataPreviewGroupBox")
        self.verticalLayout_2 = QVBoxLayout(self.dataPreviewGroupBox)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.dataPreviewTable = QTableView(self.dataPreviewGroupBox)
        self.dataPreviewTable.setObjectName(u"dataPreviewTable")
        self.dataPreviewTable.setSelectionMode(QAbstractItemView.SingleSelection)
        self.dataPreviewTable.setSelectionBehavior(QAbstractItemView.SelectColumns)
        self.dataPreviewTable.horizontalHeader().setStretchLastSection(True)

        self.verticalLayout_2.addWidget(self.dataPreviewTable)


        self.verticalLayout.addWidget(self.dataPreviewGroupBox)

        self.buttonLayout = QHBoxLayout()
        self.buttonLayout.setObjectName(u"buttonLayout")
        self.previewButton = QPushButton(TagDataImportDialog)
        self.previewButton.setObjectName(u"previewButton")

        self.buttonLayout.addWidget(self.previewButton)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.buttonLayout.addItem(self.horizontalSpacer)

        self.cancelButton = QPushButton(TagDataImportDialog)
        self.cancelButton.setObjectName(u"cancelButton")

        self.buttonLayout.addWidget(self.cancelButton)

        self.importButton = QPushButton(TagDataImportDialog)
        self.importButton.setObjectName(u"importButton")
        self.importButton.setEnabled(False)

        self.buttonLayout.addWidget(self.importButton)


        self.verticalLayout.addLayout(self.buttonLayout)


        self.retranslateUi(TagDataImportDialog)

        QMetaObject.connectSlotsByName(TagDataImportDialog)
    # setupUi

    def retranslateUi(self, TagDataImportDialog):
        TagDataImportDialog.setWindowTitle(QCoreApplication.translate("TagDataImportDialog", u"\u30bf\u30b0\u30c7\u30fc\u30bf\u30a4\u30f3\u30dd\u30fc\u30c8", None))
        self.formatGroupBox.setTitle(QCoreApplication.translate("TagDataImportDialog", u"\u30d5\u30a9\u30fc\u30de\u30c3\u30c8", None))
        self.formatComboBox.setItemText(0, QCoreApplication.translate("TagDataImportDialog", u"Unknown", None))

        self.languageGroupBox.setTitle(QCoreApplication.translate("TagDataImportDialog", u"\u8a00\u8a9e", None))
        self.languageComboBox.setItemText(0, QCoreApplication.translate("TagDataImportDialog", u"None", None))

        self.requiredColumnsGroupBox.setTitle(QCoreApplication.translate("TagDataImportDialog", u"\u5fc5\u9808\u30ab\u30e9\u30e0", None))
        self.sourceTagCheckBox.setText(QCoreApplication.translate("TagDataImportDialog", u"source_tag", None))
        self.tagCheckBox.setText(QCoreApplication.translate("TagDataImportDialog", u"tag", None))
        self.dataPreviewGroupBox.setTitle(QCoreApplication.translate("TagDataImportDialog", u"\u30c7\u30fc\u30bf\u30d7\u30ec\u30d3\u30e5\u30fc\uff08\u30c0\u30d6\u30eb\u30af\u30ea\u30c3\u30af\u3067\u30ab\u30e9\u30e0\u306e\u7a2e\u985e\u3092\u9078\u629e\uff09", None))
        self.previewButton.setText(QCoreApplication.translate("TagDataImportDialog", u"\u30d7\u30ec\u30d3\u30e5\u30fc\u66f4\u65b0", None))
        self.cancelButton.setText(QCoreApplication.translate("TagDataImportDialog", u"\u30ad\u30e3\u30f3\u30bb\u30eb", None))
        self.importButton.setText(QCoreApplication.translate("TagDataImportDialog", u"\u30a4\u30f3\u30dd\u30fc\u30c8", None))
    # retranslateUi

