# genai_tag_db_tools/gui/widgets/tag_register.py

from pydantic import ValidationError
from PySide6.QtCore import Slot
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from genai_tag_db_tools.gui.designer.TagRegisterWidget_ui import Ui_TagRegisterWidget
from genai_tag_db_tools.gui.presenters.tag_register_presenter import (
    build_tag_info,
    format_tag_details,
)
from genai_tag_db_tools.services.app_services import (
    TagRegisterService,
    TagSearchService,
)


class TagRegisterWidget(QWidget, Ui_TagRegisterWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        search_service: TagSearchService | None = None,
        register_service: TagRegisterService | None = None,
    ):
        super().__init__(parent)
        self.setupUi(self)

        self.search_service = search_service
        self.register_service = register_service
        self._initialized = False

    def set_services(self, search_service: TagSearchService, register_service: TagRegisterService) -> None:
        """Set service instances (initialization deferred to showEvent)."""
        self.search_service = search_service
        self.register_service = register_service
        self._initialized = False

    def showEvent(self, event: QShowEvent) -> None:
        """Initialize UI when widget is first shown."""
        if self.search_service and self.register_service and not self._initialized:
            self.initialize_ui()
            self._initialized = True
        super().showEvent(event)

    def initialize(self) -> None:
        self.initialize_ui()

    def initialize_ui(self) -> None:
        formats = self.search_service.get_tag_formats()
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItems(formats)

        languages = self.search_service.get_tag_languages()
        self.comboBoxLanguage.clear()
        self.comboBoxLanguage.addItems(languages)

        self.comboBoxLanguage.setCurrentText("japanese")
        self.on_comboBoxFormat_currentIndexChanged()

    @Slot(int)
    def on_comboBoxFormat_currentIndexChanged(self, index=0) -> None:
        format_name = self.comboBoxFormat.currentText() or "danbooru"
        tag_types = self.search_service.get_tag_types(format_name)
        self.comboBoxType.clear()
        self.comboBoxType.addItems(["", *tag_types])

    @Slot()
    def on_pushButtonRegister_clicked(self) -> None:
        try:
            tag_info = build_tag_info(
                tag=self.lineEditTag.text().strip(),
                source_tag=self.lineEditSourceTag.text().strip(),
                format_name=self.comboBoxFormat.currentText(),
                type_name=self.comboBoxType.currentText(),
                use_count=self.spinBoxUseCount.value(),
                language=self.comboBoxLanguage.currentText(),
                translation=self.lineEditTranslation.text(),
            )
            tag_id = self.register_service.register_or_update_tag(tag_info)
            self.render_tag_details(tag_id)
            self.clear_fields()

        except ValidationError as e:
            QMessageBox.warning(self, "Validation Error", f"Invalid tag data: {e}")
            self.textEditOutput.append(f"Validation Error: {e!s}")
        except ValueError as e:
            QMessageBox.warning(self, "Value Error", str(e))
            self.textEditOutput.append(f"Value Error: {e!s}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.textEditOutput.append(f"Unexpected Error: {e!s}")

    @Slot()
    def on_pushButtonImport_clicked(self) -> None:
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        self.lineEditTag.setText(text)

    def render_tag_details(self, tag_id: int) -> None:
        details_df = self.register_service.get_tag_details(tag_id)
        self.textEditOutput.append(format_tag_details(tag_id, details_df))

    def clear_fields(self) -> None:
        self.lineEditTag.clear()
        self.lineEditSourceTag.clear()
        self.comboBoxFormat.setCurrentIndex(0)
        self.comboBoxType.setCurrentIndex(0)
        self.spinBoxUseCount.setValue(0)
        self.comboBoxLanguage.setCurrentText("japanese")
        self.lineEditTranslation.clear()


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    widget = TagRegisterWidget()
    widget.show()
    sys.exit(app.exec())
