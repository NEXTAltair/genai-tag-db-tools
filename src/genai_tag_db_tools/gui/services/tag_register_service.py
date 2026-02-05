"""Tag register service for GUI."""

from typing import TYPE_CHECKING

import polars as pl
from PySide6.QtCore import QObject

from genai_tag_db_tools.db.repository import (
    TagRepository,
)
from genai_tag_db_tools.gui.services.gui_service_base import GuiServiceBase
from genai_tag_db_tools.services.tag_register import (
    TagRegisterService as CoreTagRegisterService,
)

if TYPE_CHECKING:
    from genai_tag_db_tools.db.repository import MergedTagReader
    from genai_tag_db_tools.models import TagRegisterRequest, TagRegisterResult


class GuiTagRegisterService(GuiServiceBase):
    """GUI向けのタグ登録サービス (CoreTagRegisterService wrapper with Qt signals)"""

    def __init__(
        self,
        parent: QObject | None = None,
        repository: TagRepository | None = None,
        reader: "MergedTagReader | None" = None,
    ):
        super().__init__(parent)
        self._core = CoreTagRegisterService(repository=repository, reader=reader)
        self._repo = self._core._repo  # For legacy methods
        self._reader = self._core._reader  # For legacy methods

    def register_tag(self, request: "TagRegisterRequest") -> "TagRegisterResult":
        """Register a tag and optional metadata via the repository.

        Args:
            request: Tag registration request.
        Returns:
            TagRegisterResult indicating whether the tag was created.
        """
        try:
            result = self._core.register_tag(request)
            return result
        except Exception as e:
            self.logger.error("タグ登録中にエラー発生: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def register_or_update_tag(self, tag_info: dict) -> int:
        """タグ登録/更新を行う"""
        try:
            normalized_tag = tag_info.get("normalized_tag")
            source_tag = tag_info.get("source_tag")
            format_name = tag_info.get("format_name", "")
            type_name = tag_info.get("type_name", "")
            usage_count = tag_info.get("use_count", 0)
            language = tag_info.get("language", "")
            translation = tag_info.get("translation", "")

            if not normalized_tag or not source_tag:
                raise ValueError("タグまたはソースタグが空です")

            if format_name and type_name:
                from genai_tag_db_tools.models import TagRegisterRequest, TagTranslationInput

                translations = None
                if language and translation:
                    translations = [TagTranslationInput(language=language, translation=translation)]

                self.register_tag(
                    TagRegisterRequest(
                        tag=normalized_tag,
                        source_tag=source_tag,
                        format_name=format_name,
                        type_name=type_name,
                        translations=translations,
                    )
                )
                tag_id = self._reader.get_tag_id_by_name(normalized_tag, partial=False)
                if tag_id is None:
                    raise ValueError("登録後にタグIDが見つかりません")
                if usage_count > 0:
                    fmt_id = self._reader.get_format_id(format_name)
                    self._repo.update_usage_count(tag_id, fmt_id, usage_count)
                return tag_id

            fmt_id = self._reader.get_format_id(format_name)
            # format固有のtype_idを正しく解決する
            type_id = self._reader.get_type_id_for_format(type_name, fmt_id) if type_name else None

            tag_id = self._repo.create_tag(source_tag, normalized_tag)

            if usage_count > 0:
                self._repo.update_usage_count(tag_id, fmt_id, usage_count)

            if language and translation:
                self._repo.add_or_update_translation(tag_id, language, translation)

            self._repo.update_tag_status(
                tag_id=tag_id,
                format_id=fmt_id,
                alias=False,
                preferred_tag_id=tag_id,
                type_id=type_id,
            )

            return tag_id

        except Exception as e:
            self.logger.error("タグ登録中にエラー発生: %s", e)
            self.error_occurred.emit(str(e))
            raise

    def get_tag_details(self, tag_id: int) -> pl.DataFrame:
        """登録後のタグ詳細を取得する"""
        try:
            tag_obj = self._reader.get_tag_by_id(tag_id)
            if not tag_obj:
                return pl.DataFrame()

            status_list = self._reader.list_tag_statuses(tag_id)
            translations = self._reader.get_translations(tag_id)

            rows = [
                {
                    "tag": tag_obj.tag,
                    "source_tag": tag_obj.source_tag,
                    "formats": [s.format_id for s in status_list],
                    "types": [s.type_id for s in status_list],
                    "total_usage_count": sum(
                        self._reader.get_usage_count(tag_id, s.format_id) or 0 for s in status_list
                    ),
                    "translations": {t.language: t.translation for t in translations},
                }
            ]

            return pl.DataFrame(rows)

        except Exception as e:
            self.logger.error("タグ詳細取得中にエラー発生: %s", e)
            self.error_occurred.emit(str(e))
            raise
