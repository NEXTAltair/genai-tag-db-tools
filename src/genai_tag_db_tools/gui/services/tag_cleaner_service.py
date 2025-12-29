"""Tag cleaner service for GUI."""

from PySide6.QtCore import QObject

from genai_tag_db_tools.db.repository import get_default_reader
from genai_tag_db_tools.gui.services.gui_service_base import GuiServiceBase
from genai_tag_db_tools.services.core_services import TagCoreService


class TagCleanerService(GuiServiceBase):
    """GUIの一括変換など簡易変換まとめるサービス"""

    def __init__(self, parent: QObject | None = None, core: TagCoreService | None = None):
        super().__init__(parent)
        self._core = core or TagCoreService()

    def get_tag_formats(self) -> list[str]:
        """Return available tag formats."""
        return self._core.get_tag_formats()

    def convert_prompt(self, prompt: str, format_name: str) -> str:
        """カンマ区別のタグを指定フォーマットへ変換する"""
        from genai_tag_db_tools.core_api import convert_tags

        self.logger.info("TagCleanerService: convert_prompt() called")

        reader = get_default_reader()
        return convert_tags(reader, prompt, format_name)
