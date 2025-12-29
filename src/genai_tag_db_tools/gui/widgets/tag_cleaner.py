# genai_tag_db_tools/widgets/tag_cleaner.py

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from genai_tag_db_tools.gui.designer.TagCleanerWidget_ui import Ui_TagCleanerWidget
from genai_tag_db_tools.gui.services import TagCleanerService


class TagCleanerWidget(QWidget, Ui_TagCleanerWidget):
    def __init__(self, parent: QWidget | None = None, service: TagCleanerService | None = None):
        super().__init__(parent)
        self.setupUi(self)
        self._cleaner_service = service
        self._initialized = False

    def set_service(self, cleaner_service: TagCleanerService) -> None:
        """Set service instance (initialization deferred to showEvent)."""
        self._cleaner_service = cleaner_service
        self._initialized = False
        if self.isVisible():
            self._initialize_ui()
            self._initialized = True

    def showEvent(self, event: QShowEvent) -> None:
        """Initialize UI when widget is first shown."""
        if self._cleaner_service and not self._initialized:
            self._initialize_ui()
            self._initialized = True
        super().showEvent(event)

    def _initialize_ui(self) -> None:
        """Initialize UI elements with service data."""
        formats = self._cleaner_service.get_tag_formats()
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItems(formats)
        default_index = self.comboBoxFormat.findText("danbooru", Qt.MatchFlag.MatchFixedString)
        if default_index >= 0:
            self.comboBoxFormat.setCurrentIndex(default_index)

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
