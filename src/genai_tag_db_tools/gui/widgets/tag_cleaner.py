# genai_tag_db_tools/widgets/tag_cleaner.py
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget

from genai_tag_db_tools.gui.designer.TagCleanerWidget_ui import Ui_TagCleanerWidget

# まとめたサービスモジュールから必要なクラスをインポート
from genai_tag_db_tools.services.app_services import TagCleanerService


class TagCleanerWidget(QWidget, Ui_TagCleanerWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._cleaner_service = None

    def initialize(self, cleaner_service: TagCleanerService):
        """
        サービスクラスを外部から受け取り、UIの初期化を行う。
        """
        self._cleaner_service = cleaner_service
        formats = self._cleaner_service.get_tag_formats()
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItems(formats)

    @Slot()
    def on_pushButtonConvert_clicked(self):
        if not self._cleaner_service:
            self.plainTextEditResult.setPlainText("「エラー: サービスが設定されていません」")
            return

        plain_text = self.plainTextEditPrompt.toPlainText()
        selected_format = self.comboBoxFormat.currentText()

        converted_tags = self._cleaner_service.convert_prompt(plain_text, selected_format)
        self.plainTextEditResult.setPlainText(converted_tags)


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    widget = TagCleanerWidget()
    service = TagCleanerService()
    widget.initialize(service)
    widget.show()
    sys.exit(app.exec())
