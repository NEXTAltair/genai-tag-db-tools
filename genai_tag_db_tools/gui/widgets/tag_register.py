from PySide6.QtWidgets import QWidget, QMessageBox
from PySide6.QtCore import Slot
from genai_tag_db_tools.gui.designer.TagRegisterWidget_ui import Ui_TagRegisterWidget
from genai_tag_db_tools.services.processor import CSVToDatabaseProcessor


class TagRegisterWidget(QWidget, Ui_TagRegisterWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.tag_searcher = None

    def initialize(self, tag_searcher):
        self.tag_searcher = tag_searcher
        self.initialize_ui()

    def initialize_ui(self):
        self.comboBoxFormat.addItems(self.tag_searcher.get_tag_formats())
        self.comboBoxLanguage.addItems(self.tag_searcher.get_tag_languages())
        self.comboBoxLanguage.setCurrentText("japanese")
        self.on_comboBoxFormat_currentIndexChanged()

    @Slot(int)
    def on_comboBoxFormat_currentIndexChanged(self, index=0):
        format_name = self.comboBoxFormat.currentText()
        tag_types = self.tag_searcher.get_tag_types(format_name)
        self.comboBoxType.clear()
        self.comboBoxType.addItems([""] + tag_types)

    @Slot()
    def on_pushButtonRegister_clicked(self):
        try:
            tag_info = self.get_tag_info()

            tag_id = self.tag_searcher.register_or_update_tag(tag_info)
            self.display_tag_details(tag_id)
            self.clear_fields()
        except Exception as e:
            QMessageBox.warning(self, "エラー", str(e))
            self.textEditOutput.append(f"エラー: {str(e)}")

    def get_tag_info(self):
        tag = self.lineEditTag.text().strip()
        source_tag = self.lineEditSourceTag.text().strip() or tag

        if not tag and not source_tag:
            raise ValueError("タグまたは元タグは必須です。")
        if "," in tag or "," in source_tag:
            raise ValueError("登録するタグは単一のタグである必要があります。")

        if source_tag == tag:
            source_tag = tag
        else:
            normalized_tag = CSVToDatabaseProcessor.normalize_tag(source_tag)

        return {
            "normalized_tag": normalized_tag,
            "source_tag": source_tag,
            "format_name": self.comboBoxFormat.currentText(),
            "type_name": self.comboBoxType.currentText(),
            "use_count": self.spinBoxUseCount.value(),
            "language": self.comboBoxLanguage.currentText(),
            "translation": self.lineEditTranslation.text(),
        }

    def display_tag_details(self, tag_id):
        details = self.tag_searcher.get_tag_details(tag_id)
        if details.empty:
            self.textEditOutput.append(f"タグID {tag_id} の情報が見つかりません。")
            return

        info = details.iloc[0]
        result = f"タグ情報 (ID: {tag_id}):\n"
        result += f"タグ: {info['tag']}\n"
        result += f"元タグ: {info['source_tag']}\n"
        result += f"フォーマット: {info['formats']}\n"
        result += f"タイプ: {info['types']}\n"
        result += f"使用回数: {info['total_usage_count']}\n"
        result += f"翻訳: {info['translations']}\n"
        result += "-" * 40 + "\n"
        self.textEditOutput.append(result)

    def clear_fields(self):
        self.lineEditTag.clear()
        self.lineEditSourceTag.clear()
        self.comboBoxFormat.setCurrentIndex(0)
        self.comboBoxType.setCurrentIndex(0)
        self.spinBoxUseCount.setValue(0)
        self.comboBoxLanguage.setCurrentText("japanese")
        self.lineEditTranslation.clear()


if __name__ == "__main__":
    from genai_tag_db_tools.gui.widgets.tag_register import initialize_tag_searcher
    from PySide6.QtWidgets import QApplication
    from ..designer.TagRegisterWidget import TagRegisterWidget

    app = QApplication([])
    tag_searcher = initialize_tag_searcher()
    widget = TagRegisterWidget()
    widget.initialize(tag_searcher)
    widget.show()
    app.exec()
