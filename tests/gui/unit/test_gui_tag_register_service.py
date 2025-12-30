"""GuiTagRegisterService unit tests - Qt Signal emission and error handling"""

from unittest.mock import MagicMock, Mock

import pytest
from PySide6.QtCore import QObject
from pytestqt.qt_compat import qt_api

from genai_tag_db_tools.gui.services.tag_register_service import GuiTagRegisterService
from genai_tag_db_tools.models import TagRegisterRequest, TagRegisterResult, TagTranslationInput


class DummyRepo:
    """Minimal repository mock for testing"""

    def __init__(self) -> None:
        self.created_tags: list[tuple[str, str]] = []
        self.status_updates: list[tuple[int, int, bool, int, int | None]] = []
        self.translations: list[tuple[int, str, str]] = []
        self.usage_updates: list[tuple[int, int, int]] = []
        self._tag_ids: dict[str, int] = {}

    def create_tag(self, source_tag: str, tag: str) -> int:
        self.created_tags.append((source_tag, tag))
        tag_id = 10
        self._tag_ids[tag] = tag_id
        return tag_id

    def update_tag_status(
        self,
        tag_id: int,
        format_id: int,
        alias: bool,
        preferred_tag_id: int,
        type_id: int | None = None,
    ) -> None:
        self.status_updates.append((tag_id, format_id, alias, preferred_tag_id, type_id))

    def add_or_update_translation(self, tag_id: int, language: str, translation: str) -> None:
        self.translations.append((tag_id, language, translation))

    def update_usage_count(self, tag_id: int, format_id: int, count: int) -> None:
        self.usage_updates.append((tag_id, format_id, count))


class DummyReader:
    """Minimal reader mock for testing"""

    def __init__(self, repo: DummyRepo) -> None:
        self.repo = repo

    def get_format_id(self, format_name: str) -> int | None:
        return {"danbooru": 1}.get(format_name)

    def get_type_id(self, type_name: str) -> int | None:
        return {"character": 2, "general": 1}.get(type_name)

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        if tag == "preferred":
            return 99
        return self.repo._tag_ids.get(tag)

    def get_tag_by_id(self, tag_id: int) -> Mock | None:
        if tag_id == 10:
            mock_tag = Mock()
            mock_tag.tag = "test_tag"
            mock_tag.source_tag = "test_tag"
            return mock_tag
        return None

    def list_tag_statuses(self, tag_id: int) -> list[Mock]:
        if tag_id == 10:
            mock_status = Mock()
            mock_status.format_id = 1
            mock_status.type_id = 2
            return [mock_status]
        return []

    def get_translations(self, tag_id: int) -> list[Mock]:
        if tag_id == 10:
            mock_translation = Mock()
            mock_translation.language = "ja"
            mock_translation.translation = "テストタグ"
            return [mock_translation]
        return []

    def get_usage_count(self, tag_id: int, format_id: int) -> int | None:
        return 100 if tag_id == 10 and format_id == 1 else None


@pytest.mark.gui
class TestGuiTagRegisterService:
    """GuiTagRegisterService tests for Qt Signal emissions and error handling"""

    @pytest.fixture
    def service(self, qtbot) -> GuiTagRegisterService:
        """Create GuiTagRegisterService with dummy dependencies"""
        repo = DummyRepo()
        reader = DummyReader(repo)
        service = GuiTagRegisterService(parent=None, repository=repo, reader=reader)
        return service

    def test_register_tag_success_no_signal_emission(self, service: GuiTagRegisterService, qtbot):
        """register_tag succeeds without emitting error signal"""
        # Setup signal spy
        error_spy = qt_api.QtTest.QSignalSpy(service.error_occurred)

        request = TagRegisterRequest(
            tag="test_tag",
            source_tag="test_tag",
            format_name="danbooru",
            type_name="character",
        )

        # Execute
        result = service.register_tag(request)

        # Verify success
        assert result.tag_id == 10
        assert result.created is True

        # Verify no error signal emitted
        assert error_spy.count() == 0

    def test_register_tag_error_emits_signal(self, service: GuiTagRegisterService, qtbot):
        """register_tag error emits error_occurred signal"""
        # Setup signal spy
        error_spy = qt_api.QtTest.QSignalSpy(service.error_occurred)

        # Invalid request (missing format_name will cause error)
        request = TagRegisterRequest(
            tag="test_tag",
            source_tag="test_tag",
            format_name="invalid_format",
            type_name="character",
        )

        # Execute and expect exception
        with pytest.raises(ValueError):
            service.register_tag(request)

        # Verify error signal emitted
        assert error_spy.count() == 1

    def test_register_or_update_tag_success(self, service: GuiTagRegisterService, qtbot):
        """register_or_update_tag succeeds with valid input"""
        tag_info = {
            "normalized_tag": "test_tag",
            "source_tag": "test_tag",
            "format_name": "danbooru",
            "type_name": "character",
            "use_count": 50,
            "language": "ja",
            "translation": "テストタグ",
        }

        # Execute
        tag_id = service.register_or_update_tag(tag_info)

        # Verify
        assert tag_id == 10

    def test_register_or_update_tag_empty_tag_raises_error(
        self, service: GuiTagRegisterService, qtbot
    ):
        """register_or_update_tag raises ValueError for empty tag"""
        error_spy = qt_api.QtTest.QSignalSpy(service.error_occurred)

        tag_info = {
            "normalized_tag": "",
            "source_tag": "test_tag",
        }

        # Execute and expect exception
        with pytest.raises(ValueError, match="タグまたはソースタグが空です"):
            service.register_or_update_tag(tag_info)

        # Verify error signal emitted
        assert error_spy.count() == 1

    def test_register_or_update_tag_empty_source_raises_error(
        self, service: GuiTagRegisterService, qtbot
    ):
        """register_or_update_tag raises ValueError for empty source_tag"""
        error_spy = qt_api.QtTest.QSignalSpy(service.error_occurred)

        tag_info = {
            "normalized_tag": "test_tag",
            "source_tag": "",
        }

        # Execute and expect exception
        with pytest.raises(ValueError, match="タグまたはソースタグが空です"):
            service.register_or_update_tag(tag_info)

        # Verify error signal emitted
        assert error_spy.count() == 1

    def test_get_tag_details_success(self, service: GuiTagRegisterService, qtbot):
        """get_tag_details returns DataFrame with tag information"""
        # Execute
        result_df = service.get_tag_details(tag_id=10)

        # Verify
        assert len(result_df) == 1
        row = result_df.row(0, named=True)
        assert row["tag"] == "test_tag"
        assert row["source_tag"] == "test_tag"
        assert row["formats"] == [1]
        assert row["types"] == [2]
        assert row["total_usage_count"] == 100
        assert row["translations"] == {"ja": "テストタグ"}

    def test_get_tag_details_nonexistent_tag_returns_empty(
        self, service: GuiTagRegisterService, qtbot
    ):
        """get_tag_details returns empty DataFrame for nonexistent tag"""
        # Execute
        result_df = service.get_tag_details(tag_id=999)

        # Verify
        assert len(result_df) == 0

    def test_get_tag_details_error_emits_signal(self, service: GuiTagRegisterService, qtbot):
        """get_tag_details error emits error_occurred signal"""
        error_spy = qt_api.QtTest.QSignalSpy(service.error_occurred)

        # Mock reader to raise exception
        service._reader.get_tag_by_id = Mock(side_effect=Exception("Database error"))

        # Execute and expect exception
        with pytest.raises(Exception, match="Database error"):
            service.get_tag_details(tag_id=10)

        # Verify error signal emitted
        assert error_spy.count() == 1

    def test_service_inheritance_from_gui_service_base(self, service: GuiTagRegisterService):
        """GuiTagRegisterService inherits from GuiServiceBase and QObject"""
        assert isinstance(service, QObject)
        assert hasattr(service, "error_occurred")
        assert hasattr(service, "progress_updated")
        assert hasattr(service, "process_finished")

    def test_service_wraps_core_service(self, service: GuiTagRegisterService):
        """GuiTagRegisterService wraps CoreTagRegisterService"""
        assert hasattr(service, "_core")
        assert service._core is not None
