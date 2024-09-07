from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Slot
from TagCleanerWidget_ui import Ui_TagCleanerWidget
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

class TagCleanerWidget(QWidget, Ui_TagCleanerWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def initialize(self, tag_searcher):
        self.tag_searcher = tag_searcher
        self.comboBoxFormat.addItems(self.tag_searcher.get_tag_formats())

    @Slot()
    def on_pushButtonConvert_clicked(self):
        plain_text = self.plainTextEditPrompt.toPlainText()
        converted_tags = self.tag_searcher.prompt_convert(plain_text, self.comboBoxFormat.currentText())
        self.plainTextEditResult.setPlainText(converted_tags)

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    from tag_search import initialize_tag_searcher

    app = QApplication(sys.argv)
    tag_searcher = initialize_tag_searcher()
    window = TagCleanerWidget()
    window.initialize(tag_searcher)
    window.show()
    sys.exit(app.exec())

