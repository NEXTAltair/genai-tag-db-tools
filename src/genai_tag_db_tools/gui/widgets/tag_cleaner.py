# genai_tag_db_tools/widgets/tag_cleaner.py

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget

from genai_tag_db_tools.gui.designer.TagCleanerWidget_ui import Ui_TagCleanerWidget
from genai_tag_db_tools.services.app_services import TagCleanerService


class TagCleanerWidget(QWidget, Ui_TagCleanerWidget):
    def __init__(self, parent=None, service: TagCleanerService | None = None):
        super().__init__(parent)
        self.setupUi(self)
        self._cleaner_service = service
        if service is not None:
            formats = self._cleaner_service.get_tag_formats()
            self.comboBoxFormat.clear()
            self.comboBoxFormat.addItems(formats)

    def set_service(self, cleaner_service: TagCleanerService) -> None:
        self._cleaner_service = cleaner_service
        formats = self._cleaner_service.get_tag_formats()
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItems(formats)

    def initialize(self, cleaner_service: TagCleanerService) -> None:
        self.set_service(cleaner_service)

    @Slot()
    def on_pushButtonConvert_clicked(self) -> None:
        if not self._cleaner_service:
            self.plainTextEditResult.setPlainText("Error: service is not initialized.")
            return

        plain_text = self.plainTextEditPrompt.toPlainText()
        selected_format = self.comboBoxFormat.currentText()

        converted_tags = self._cleaner_service.convert_prompt(plain_text, selected_format)
        self.plainTextEditResult.setPlainText(converted_tags)


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    widget = TagCleanerWidget(service=TagCleanerService())
    widget.show()
    sys.exit(app.exec())
