# genai_tag_db_tools/services/app_services.py

import logging
from typing import Any

import polars as pl
from PySide6.QtCore import QObject, Signal
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.services.import_data import ImportConfig, TagDataImporter
from genai_tag_db_tools.services.tag_search import TagSearcher
from genai_tag_db_tools.services.tag_statistics import TagStatistics


class GuiServiceBase(QObject):
    """
    PySide6 縺ｮ繧ｷ繧ｰ繝翫Ν繧・・騾壹・繝ｭ繧ｬ繝ｼ蛻晄悄蛹悶↑縺ｩ繧定｡後≧蝓ｺ蠎輔け繝ｩ繧ｹ縲・    騾ｲ謐鈴夂衍繧・お繝ｩ繝ｼ騾夂衍縺ｪ縺ｩ縲；UI縺ｨ縺ｮ騾｣謳ｺ縺ｧ繧医￥菴ｿ縺・ｩ溯・繧偵∪縺ｨ繧√ｋ縲・    """

    # GUI蜷代￠縺ｫ騾ｲ謐励ｄ螳御ｺ・√お繝ｩ繝ｼ繧帝夂衍縺吶ｋ縺溘ａ縺ｮ繧ｷ繧ｰ繝翫Ν繧貞・騾壼ｮ夂ｾｩ
    progress_updated = Signal(int, str)  # (騾ｲ謐怜ｺｦ, 繝｡繝・そ繝ｼ繧ｸ)
    process_finished = Signal(str)  # (螳御ｺ・凾縺ｮ繝｡繝・そ繝ｼ繧ｸ繧・・逅・錐)
    error_occurred = Signal(str)  # (繧ｨ繝ｩ繝ｼ蜀・ｮｹ)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        # 蜷・し繝ｼ繝薙せ繧ｯ繝ｩ繧ｹ縺ｧ蜈ｱ騾壹＠縺ｦ菴ｿ縺・◆縺・Ο繧ｬ繝ｼ
        self.logger = logging.getLogger(self.__class__.__name__)


class TagCoreService:
    """
    繧ｿ繧ｰ讀懃ｴ｢繧・ヵ繧ｩ繝ｼ繝槭ャ繝亥叙蠕励↑縺ｩ縲．B謫堺ｽ懊・繧ｳ繧｢繝ｭ繧ｸ繝・け繧偵∪縺ｨ繧√◆繧ｯ繝ｩ繧ｹ縲・    縺吶∋縺ｦ縺ｮ繧ｵ繝ｼ繝薙せ(Import/Clean/Cleanup/Search/etc.)縺悟・騾壹〒菴ｿ縺医ｋ讖溯・繧帝寔邏・・    """

    def __init__(self, searcher: TagSearcher | None = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        # TagSearcher 繧貞・蛹・        self._searcher = searcher or TagSearcher()

    def get_tag_formats(self) -> list[str]:
        """
        DB縺九ｉ繧ｿ繧ｰ繝輔か繝ｼ繝槭ャ繝井ｸ隕ｧ繧貞叙蠕励＠縺ｦ霑斐☆縲・        """
        return self._searcher.get_tag_formats()

    def get_tag_languages(self) -> list[str]:
        """
        DB縺九ｉ險隱樔ｸ隕ｧ繧貞叙蠕励＠縺ｦ霑斐☆縲・        """
        return self._searcher.get_tag_languages()

    def get_format_id(self, format_name: str) -> int:
        """
        繝輔か繝ｼ繝槭ャ繝亥錐縺九ｉ繝輔か繝ｼ繝槭ャ繝・D繧貞叙蠕励・        """
        return self._searcher.tag_repo.get_format_id(format_name)

    def convert_tag(self, tag: str, format_id: int) -> str:
        """
        蜊倅ｸ縺ｮ繧ｿ繧ｰ譁・ｭ怜・繧呈欠螳壹ヵ繧ｩ繝ｼ繝槭ャ繝・D縺ｫ蝓ｺ縺･縺榊､画鋤縲・        TagSearcher.convert_tag() 繧貞・驛ｨ蛻ｩ逕ｨ縲・        """
        return self._searcher.convert_tag(tag, format_id)


class TagSearchService(GuiServiceBase):
    """
    TagSearcher繧貞・驛ｨ縺ｧ蛻ｩ逕ｨ縺励；UI逕ｨ縺ｮ繝｡繧ｽ繝・ラ・域､懃ｴ｢繧・ヵ繧ｩ繝ｼ繝槭ャ繝井ｸ隕ｧ蜿門ｾ励↑縺ｩ・峨ｒ縺ｾ縺ｨ繧√ｋ縲・    """

    def __init__(self, parent: QObject | None = None, searcher: TagSearcher | None = None):
        super().__init__(parent)
        self._searcher = searcher or TagSearcher()

    def get_tag_formats(self) -> list[str]:
        """
        DB 縺九ｉ繧ｿ繧ｰ繝輔か繝ｼ繝槭ャ繝井ｸ隕ｧ繧貞叙蠕励・        """
        try:
            return self._searcher.get_tag_formats()
        except Exception as e:
            self.logger.error(f"繝輔か繝ｼ繝槭ャ繝井ｸ隕ｧ蜿門ｾ嶺ｸｭ縺ｫ繧ｨ繝ｩ繝ｼ: {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_tag_languages(self) -> list[str]:
        """
        DB 縺九ｉ險隱樔ｸ隕ｧ繧貞叙蠕励・        """
        try:
            return self._searcher.get_tag_languages()
        except Exception as e:
            self.logger.error(f"險隱樔ｸ隕ｧ蜿門ｾ嶺ｸｭ縺ｫ繧ｨ繝ｩ繝ｼ: {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_tag_types(self, format_name: str | None) -> list[str]:
        """
        謖・ｮ壹ヵ繧ｩ繝ｼ繝槭ャ繝医↓邏舌▼縺上ち繧ｰ繧ｿ繧､繝嶺ｸ隕ｧ繧貞叙蠕励・
        Args:
            format_name (str): 繝輔か繝ｼ繝槭ャ繝亥錐縲・one 縺ｮ蝣ｴ蜷医・蜈ｨ讀懃ｴ｢縲・        """
        try:
            if format_name is None:
                return self._searcher.get_all_types()
            return self._searcher.get_tag_types(format_name)
        except Exception as e:
            self.logger.error(f"繧ｿ繧ｰ繧ｿ繧､繝嶺ｸ隕ｧ蜿門ｾ嶺ｸｭ縺ｫ繧ｨ繝ｩ繝ｼ: {e}")
            self.error_occurred.emit(str(e))
            raise

    def search_tags(
        self,
        keyword: str,
        partial: bool = False,
        format_name: str | None = None,
        type_name: str | None = None,
        language: str | None = None,
        min_usage: int | None = None,
        max_usage: int | None = None,
        alias: bool | None = None,
    ) -> pl.DataFrame:
        """
        繧ｿ繧ｰ繧呈､懃ｴ｢縺励∫ｵ先棡繧・list[dict] 蠖｢蠑上〒霑斐☆諠ｳ螳壹・        partial=True 縺ｮ蝣ｴ蜷医・驛ｨ蛻・ｸ閾ｴ縲｝artial=False 縺ｯ螳悟・荳閾ｴ縲・        format_name=None 縺ｮ蝣ｴ蜷医・繝輔か繝ｼ繝槭ャ繝域欠螳壹↑縺・蜈ｨ讀懃ｴ｢)
        """
        try:
            return self._searcher.search_tags(
                keyword=keyword,
                partial=partial,
                format_name=format_name,
                type_name=type_name,
                language=language,
                min_usage=min_usage,
                max_usage=max_usage,
                alias=alias,
            )
        except Exception as e:
            self.logger.error(f"繧ｿ繧ｰ讀懃ｴ｢荳ｭ縺ｫ繧ｨ繝ｩ繝ｼ: {e}")
            self.error_occurred.emit(str(e))
            raise


class TagCleanerService(GuiServiceBase):
    """
    GUI縺ｪ縺ｩ縺ｧ縲後ち繧ｰ縺ｮ荳諡ｬ螟画鋤縲阪ｄ縲後ヵ繧ｩ繝ｼ繝槭ャ繝井ｸ隕ｧ蜿門ｾ・+ 'All'繧貞・鬆ｭ縺ｫ霑ｽ蜉縲阪↑縺ｩ
    霆ｽ驥上↑螟画鋤繝ｭ繧ｸ繝・け繧定｡後≧繧ｵ繝ｼ繝薙せ繧ｯ繝ｩ繧ｹ縲・
    - DB繧｢繧ｯ繧ｻ繧ｹ繧・ち繧ｰ謫堺ｽ懊・ TagCoreService 縺ｫ蟋碑ｭｲ縺励・    - GUI逕ｨ縺ｮ繧ｷ繧ｰ繝翫Ν繧・Ο繧ｬ繝ｼ縺ｯ GuiServiceBase 縺ｮ邯呎価縺ｧ菴ｿ縺・・    """

    def __init__(self, parent: QObject | None = None, core: TagCoreService | None = None):
        super().__init__(parent)
        self._core = core or TagCoreService()

    def get_tag_formats(self) -> list[str]:
        """
        繧ｳ繧｢繝ｭ繧ｸ繝・け縺ｮ繝輔か繝ｼ繝槭ャ繝井ｸ隕ｧ繧貞叙蠕励＠縲∝・鬆ｭ縺ｫ 'All' 繧定ｿｽ蜉縺励※霑斐☆縲・        """
        format_list = ["All"]
        format_list.extend(self._core.get_tag_formats())
        return format_list

    def convert_prompt(self, prompt: str, format_name: str) -> str:
        """
        繧ｫ繝ｳ繝槫玄蛻・ｊ縺ｮ隍・焚繧ｿ繧ｰ繧・DB縺ｧ讀懃ｴ｢繝ｻ螟画鋤縺励∽ｸ諡ｬ縺ｧ鄂ｮ縺肴鋤縺医ｋ縲・        萓・ "1boy, 1girl" + "e621" 竊・DB繧貞盾辣ｧ縺励※蜷・ち繧ｰ繧貞､画鋤 竊・"male, female" (莉ｮ)
        """
        self.logger.info("TagCleanerService: convert_prompt() called")

        # 繝輔か繝ｼ繝槭ャ繝・D繧貞叙蠕・        format_id = self._core.get_format_id(format_name)
        if format_id is None:
            self.logger.warning(f"Unknown format: {format_name}")
            return prompt

        raw_tags = [t.strip() for t in prompt.split(",")]
        converted_list = []
        for tag in raw_tags:
            converted = self._core.convert_tag(tag, format_id)
            converted_list.append(converted)

        # 繧ｫ繝ｳ繝槫玄蛻・ｊ縺ｧ邨仙粋縺励※霑斐☆
        return ", ".join(converted_list)


class TagImportService(GuiServiceBase):
    """
    繝・・繧ｿ繧､繝ｳ繝昴・繝医ｒ諡・ｽ薙☆繧九し繝ｼ繝薙せ繧ｯ繝ｩ繧ｹ縲・    - DB縺ｨ縺ｮ繧・ｊ蜿悶ｊ縺ｯ TagDataImporter (蜀・Κ), TagCoreService(繝輔か繝ｼ繝槭ャ繝亥捉繧・ 繧剃ｽｿ縺・    - PySide6 Signals (progress_updated, process_finished, error_occurred) 繧呈戟縺､
    """

    def __init__(
        self,
        parent: QObject | None = None,
        importer: TagDataImporter | None = None,
        core: TagCoreService | None = None,
    ):
        super().__init__(parent)
        self._importer = importer or TagDataImporter()
        self._core = core or TagCoreService()

        # TagDataImporter 縺檎匱陦後☆繧九す繧ｰ繝翫Ν繧偵√％縺ｮ繧ｯ繝ｩ繧ｹ縺ｮ繧ｷ繧ｰ繝翫Ν縺ｫ繝ｪ繝ｬ繝ｼ縺吶ｋ萓・        self._importer.progress_updated.connect(self._on_importer_progress)
        self._importer.process_finished.connect(self._on_importer_finished)
        self._importer.error_occurred.connect(self._on_importer_error)

    def _on_importer_progress(self, value: int, message: str):
        """
        TagDataImporter 縺九ｉ蜿励￠蜿悶▲縺滄ｲ謐励ｒ縲√％縺ｮ繧ｵ繝ｼ繝薙せ縺ｮ progress_updated 縺ｧ蜀埼夂衍縲・        """
        self.logger.debug(f"Import progress: {value}% {message}")
        self.progress_updated.emit(value, message)

    def _on_importer_finished(self, msg: str):
        """
        Import螳御ｺ・ｒ蜀埼夂衍縲・        """
        self.logger.info("Import finished.")
        self.process_finished.emit(msg)

    def _on_importer_error(self, err_msg: str):
        """
        繧ｨ繝ｩ繝ｼ逋ｺ逕溘ｒ蜀埼夂衍縲・        """
        self.logger.error(f"Import error: {err_msg}")
        self.error_occurred.emit(err_msg)

    @property
    def importer(self) -> TagDataImporter:
        """
        GUI蛛ｴ縺・TagDataImporter 縺ｮ繧ｷ繧ｰ繝翫Ν繧・Γ繧ｽ繝・ラ縺ｫ逶ｴ謗･繧｢繧ｯ繧ｻ繧ｹ縺励◆縺・ｴ蜷医↓菴ｿ縺・・        縺薙％縺ｧ縺ｯProperty縺ｨ縺励※蜈ｬ髢九・        """
        return self._importer

    # ----------------------------------------------------------------------
    #  繧､繝ｳ繝昴・繝磯未騾｣繝｡繧ｽ繝・ラ
    # ----------------------------------------------------------------------

    def import_data(self, df: pl.DataFrame, config: ImportConfig) -> None:
        """
        TagDataImporter 繧堤畑縺・※繝・・繧ｿ繝輔Ξ繝ｼ繝繧奪B縺ｫ繧､繝ｳ繝昴・繝医☆繧九・        """
        self.logger.info("TagImportService: import_data() called.")
        self._importer.import_data(df, config)

    def cancel_import(self) -> None:
        """
        繧､繝ｳ繝昴・繝亥・逅・ｒ繧ｭ繝｣繝ｳ繧ｻ繝ｫ縲・        """
        self.logger.info("TagImportService: cancel_import() called.")
        self._importer.cancel()

    # ----------------------------------------------------------------------
    #  DB諠・ｱ蜿門ｾ鈴未騾｣ (TagCoreService 邨檎罰)
    # ----------------------------------------------------------------------

    def get_tag_formats(self) -> list[str]:
        """
        DB 縺ｫ逋ｻ骭ｲ縺輔ｌ縺ｦ縺・ｋ繝輔か繝ｼ繝槭ャ繝井ｸ隕ｧ繧貞叙蠕励・        """
        return self._core.get_tag_formats()

    def get_tag_languages(self) -> list[str]:
        """
        DB 縺ｫ逋ｻ骭ｲ縺輔ｌ縺ｦ縺・ｋ險隱樔ｸ隕ｧ繧貞叙蠕励・        """
        return self._core.get_tag_languages()

    def get_format_id(self, format_name: str) -> int:
        return self._core.get_format_id(format_name)


class TagRegisterService(GuiServiceBase):
    """
    GUI縺ｫ騾ｲ謐励ｄ繧ｨ繝ｩ繝ｼ繧帝夂衍縺吶ｋ縺溘ａ縺ｫ縲；uiServiceBase繧堤ｶ呎価縺励◆繧ｿ繧ｰ逋ｻ骭ｲ繧ｵ繝ｼ繝薙せ縲・    """

    def __init__(self, parent=None, repository: TagRepository | None = None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._repo = repository if repository else TagRepository()

    def register_or_update_tag(self, tag_info: dict) -> int:
        """
        繧ｿ繧ｰ逋ｻ骭ｲ/譖ｴ譁ｰ蜃ｦ逅・ｒ陦後＞縲∽ｽ輔ｉ縺九・DB繧ｨ繝ｩ繝ｼ縺瑚ｵｷ縺阪◆繧峨す繧ｰ繝翫Ν縺ｧGUI縺ｫ騾夂衍縺吶ｋ縲・        """
        try:
            normalized_tag = tag_info.get("normalized_tag")
            source_tag = tag_info.get("source_tag")
            format_name = tag_info.get("format_name", "")
            type_name = tag_info.get("type_name", "")
            usage_count = tag_info.get("use_count", 0)
            language = tag_info.get("language", "")
            translation = tag_info.get("translation", "")

            if not normalized_tag or not source_tag:
                raise ValueError("繧ｿ繧ｰ縺ｾ縺溘・蜈・ち繧ｰ縺檎ｩｺ縺ｧ縺吶・)

            # 1) 繝輔か繝ｼ繝槭ャ繝・D, 繧ｿ繧､繝悠D 縺ｮ蜿門ｾ・            fmt_id = self._repo.get_format_id(format_name)
            type_id = None
            if type_name:
                type_id = self._repo.get_type_id(type_name)

            # 2) 繧ｿ繧ｰ繧剃ｽ懈・ or 譌｢蟄露D蜿門ｾ・            tag_id = self._repo.create_tag(source_tag, normalized_tag)

            # 3) usage_count (菴ｿ逕ｨ蝗樊焚) 逋ｻ骭ｲ
            if usage_count > 0:
                self._repo.update_usage_count(tag_id, fmt_id, usage_count)

            # 4) 鄙ｻ險ｳ逋ｻ骭ｲ
            if language and translation:
                self._repo.add_or_update_translation(tag_id, language, translation)

            # 5) TagStatus 譖ｴ譁ｰ (alias=False縺ｧ逋ｻ骭ｲ萓・
            self._repo.update_tag_status(
                tag_id=tag_id, format_id=fmt_id, alias=False, preferred_tag_id=tag_id, type_id=type_id
            )

            return tag_id

        except Exception as e:
            self.logger.error(f"繧ｿ繧ｰ逋ｻ骭ｲ荳ｭ縺ｫ繧ｨ繝ｩ繝ｼ逋ｺ逕・ {e}")
            # <-- GUI縺ｫ繧ｨ繝ｩ繝ｼ繧帝夂衍縺吶ｋ繧ｷ繧ｰ繝翫Ν繧堤匱陦・            self.error_occurred.emit(str(e))
            # 繧ｨ繝ｩ繝ｼ繧貞・蠎ｦ螟悶↓謚輔￡縺溘＞蝣ｴ蜷医・縺薙％縺ｧ raise 縺励※繧ゅｈ縺・            raise

    def get_tag_details(self, tag_id: int) -> pl.DataFrame:
        """
        逋ｻ骭ｲ蠕後・繧ｿ繧ｰ隧ｳ邏ｰ繧貞叙蠕励＠縺ｦDataFrame蛹悶＠縺ｦ霑斐☆縲・        (DB繧ｨ繝ｩ繝ｼ縺瑚ｵｷ縺阪ｋ蜿ｯ閭ｽ諤ｧ縺後≠繧句ｴ蜷医ｂ蜷梧ｧ倥↓繧ｷ繧ｰ繝翫Ν縺ｧ騾夂衍)
        """
        try:
            tag_obj = self._repo.get_tag_by_id(tag_id)
            if not tag_obj:
                return pl.DataFrame()

            status_list = self._repo.list_tag_statuses(tag_id)
            translations = self._repo.get_translations(tag_id)

            rows = [
                {
                    "tag": tag_obj.tag,
                    "source_tag": tag_obj.source_tag,
                    "formats": [s.format_id for s in status_list],
                    "types": [s.type_id for s in status_list],
                    "total_usage_count": sum(
                        self._repo.get_usage_count(tag_id, s.format_id) or 0 for s in status_list
                    ),
                    "translations": {t.language: t.translation for t in translations},
                }
            ]

            return pl.DataFrame(rows)

        except Exception as e:
            self.logger.error(f"繧ｿ繧ｰ隧ｳ邏ｰ蜿門ｾ嶺ｸｭ縺ｫ繧ｨ繝ｩ繝ｼ逋ｺ逕・ {e}")
            self.error_occurred.emit(str(e))
            raise


class TagStatisticsService(GuiServiceBase):
    """
    TagStatistics(繝ｭ繧ｸ繝・け繧ｯ繝ｩ繧ｹ)繧貞・驛ｨ縺ｫ謖√■縲・    GUI 縺九ｉ蜻ｼ縺ｰ繧後ｋ縲檎ｵｱ險亥叙蠕励阪瑚ｨ育ｮ励咲ｭ峨・蜃ｦ逅・ｒ縺ｾ縺ｨ繧√◆繧ｵ繝ｼ繝薙せ繧ｯ繝ｩ繧ｹ縲・
    - TagStatistics 縺ｯ繝・・繧ｿ繝吶・繧ｹ縺ｫ繧｢繧ｯ繧ｻ繧ｹ縺・Polars DataFrame 繧・dict 縺ｧ邨ｱ險医ｒ霑斐☆
    - GUI螻､縺ｧ縺ｯ繧ｷ繧ｰ繝翫Ν縺ｫ繧医ｋ繧ｨ繝ｩ繝ｼ繝上Φ繝峨Μ繝ｳ繧ｰ繧貞茜逕ｨ蜿ｯ閭ｽ
    """

    def __init__(
        self,
        parent: QObject | None = None,
        session: Session | None = None,
    ):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._stats = TagStatistics(session=session)  # 竊・Polars繝吶・繧ｹ縺ｮ邨ｱ險亥・逅・
    def get_general_stats(self) -> dict[str, Any]:
        """
        蜈ｨ菴鍋噪縺ｪ繧ｵ繝槭Μ(邱上ち繧ｰ謨ｰ/繧ｨ繧､繝ｪ繧｢繧ｹ謨ｰ縺ｪ縺ｩ)繧・dict 縺ｧ蜿門ｾ・        """
        try:
            return self._stats.get_general_stats()
        except Exception as e:
            self.logger.error(f"邨ｱ險亥叙蠕嶺ｸｭ縺ｫ繧ｨ繝ｩ繝ｼ縺檎匱逕・ {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_usage_stats(self) -> pl.DataFrame:
        """
        繧ｿ繧ｰ菴ｿ逕ｨ蝗樊焚縺ｮ DataFrame 繧貞叙蠕・(Polars)
        columns: [tag_id, format_name, usage_count]
        """
        try:
            return self._stats.get_usage_stats()
        except Exception as e:
            self.logger.error(f"菴ｿ逕ｨ蝗樊焚邨ｱ險亥叙蠕嶺ｸｭ縺ｫ繧ｨ繝ｩ繝ｼ縺檎匱逕・ {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_type_distribution(self) -> pl.DataFrame:
        """
        繧ｿ繧､繝・繧ｿ繧ｰ繧ｫ繝・ざ繝ｪ)蛻･縺ｮ繧ｿ繧ｰ謨ｰ蛻・ｸ・        columns: [format_name, type_name, tag_count]
        """
        try:
            return self._stats.get_type_distribution()
        except Exception as e:
            self.logger.error(f"繧ｿ繧､繝怜・蟶・ｵｱ險亥叙蠕嶺ｸｭ縺ｫ繧ｨ繝ｩ繝ｼ縺檎匱逕・ {e}")
            self.error_occurred.emit(str(e))
            raise

    def get_translation_stats(self) -> pl.DataFrame:
        """
        鄙ｻ險ｳ諠・ｱ縺ｮ邨ｱ險・        columns: [tag_id, total_translations, languages (List[str])]
        """
        try:
            return self._stats.get_translation_stats()
        except Exception as e:
            self.logger.error(f"鄙ｻ險ｳ邨ｱ險亥叙蠕嶺ｸｭ縺ｫ繧ｨ繝ｩ繝ｼ縺檎匱逕・ {e}")
            self.error_occurred.emit(str(e))
            raise


if __name__ == "__main__":
    """
    邁｡譏灘虚菴懊ユ繧ｹ繝・
      - TagCleanerService 縺ｧ隍・焚繧ｿ繧ｰ繧貞､画鋤
      - TagImportService 縺ｧ繝・・繧ｿ繧､繝ｳ繝昴・繝・繝繝溘・)
    """

    # 1) 繧ｿ繧ｰ繧ｯ繝ｪ繝ｼ繝翫・縺ｮ繝・せ繝・(Polars縺ｧ縺ｯ縺ｪ縺丞腰邏斐↑譁・ｭ怜・螟画鋤)
    cleaner = TagCleanerService()
    all_formats = cleaner.get_tag_formats()
    print("DB縺九ｉ蜿門ｾ励＠縺溘ヵ繧ｩ繝ｼ繝槭ャ繝井ｸ隕ｧ (+ All):", all_formats)

    sample_text = "1boy, 1girl, 2boys"
    format_name = "e621"  # 萓・ DB縺ｫ逋ｻ骭ｲ縺励※縺ゅｋ繝輔か繝ｼ繝槭ャ繝亥錐
    result = cleaner.convert_prompt(sample_text, format_name)
    print(f"[convert_prompt] '{sample_text}' 竊・'{result}' (format='{format_name}')")

    # 2) 繧､繝ｳ繝昴・繝医し繝ｼ繝薙せ縺ｮ繝・せ繝・(Polars DataFrame 繧堤畑諢・
    importer_service = TagImportService()
    dummy_df = pl.DataFrame({"tag": ["1boy", "2girls"], "count": [10, 20]})
    config = ImportConfig(format_id=importer_service.get_format_id("danbooru"), language="en")

    importer_service.import_data(dummy_df, config)
    print("Import finished.")

