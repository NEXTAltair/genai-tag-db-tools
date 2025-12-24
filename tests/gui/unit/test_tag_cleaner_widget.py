"""TagCleanerWidget のテスト（pytest-qt ベース）"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from genai_tag_db_tools.gui.widgets.tag_cleaner import TagCleanerWidget
from genai_tag_db_tools.services.app_services import TagCleanerService


class MockTagCleanerService(TagCleanerService):
    """TagCleanerService のモック"""

    def __init__(self):
        self.mock_get_tag_formats = MagicMock(return_value=["All", "danbooru", "e621"])
        self.mock_convert_prompt = MagicMock(return_value="converted, tags")

    def get_tag_formats(self) -> list[str]:
        return self.mock_get_tag_formats()

    def convert_prompt(self, prompt: str, format_name: str) -> str:
        return self.mock_convert_prompt(prompt, format_name)


@pytest.fixture
def tag_cleaner_widget(qtbot):
    """TagCleanerWidget fixture with mock service"""
    service = MockTagCleanerService()
    widget = TagCleanerWidget(parent=None, service=service)
    qtbot.addWidget(widget)
    return widget


@pytest.mark.db_tools
def test_tag_cleaner_widget_initialization(qtbot):
    """Widget が正しく初期化される"""
    service = MockTagCleanerService()
    widget = TagCleanerWidget(parent=None, service=service)
    qtbot.addWidget(widget)

    assert widget._cleaner_service is service
    assert widget._initialized is False


@pytest.mark.db_tools
def test_tag_cleaner_widget_set_service(qtbot, tag_cleaner_widget):
    """set_service() でサービスを設定できる"""
    new_service = MockTagCleanerService()
    tag_cleaner_widget.set_service(new_service)

    assert tag_cleaner_widget._cleaner_service is new_service
    assert tag_cleaner_widget._initialized is False


@pytest.mark.db_tools
def test_tag_cleaner_widget_showEvent_initializes_ui(qtbot, tag_cleaner_widget):
    """showEvent() で UI が初期化される"""
    tag_cleaner_widget.show()
    qtbot.waitExposed(tag_cleaner_widget)

    assert tag_cleaner_widget._initialized is True
    assert tag_cleaner_widget.comboBoxFormat.count() > 0


@pytest.mark.db_tools
def test_tag_cleaner_widget_initialize_ui_populates_formats(qtbot, tag_cleaner_widget):
    """_initialize_ui() でフォーマットコンボが設定される"""
    tag_cleaner_widget._initialize_ui()

    assert tag_cleaner_widget.comboBoxFormat.count() == 3
    assert tag_cleaner_widget.comboBoxFormat.itemText(0) == "All"


@pytest.mark.db_tools
def test_tag_cleaner_widget_convert_button_executes_conversion(qtbot, tag_cleaner_widget):
    """変換ボタンクリックで変換が実行される"""
    tag_cleaner_widget._initialize_ui()
    tag_cleaner_widget.plainTextEditPrompt.setPlainText("cat, dog")
    tag_cleaner_widget.comboBoxFormat.setCurrentText("danbooru")

    tag_cleaner_widget.on_pushButtonConvert_clicked()

    tag_cleaner_widget._cleaner_service.mock_convert_prompt.assert_called_once_with(
        "cat, dog", "danbooru"
    )
    assert tag_cleaner_widget.plainTextEditResult.toPlainText() == "converted, tags"


@pytest.mark.db_tools
def test_tag_cleaner_widget_convert_button_handles_no_service(qtbot, tag_cleaner_widget):
    """変換ボタンクリックでサービスがない場合のエラー処理"""
    tag_cleaner_widget._cleaner_service = None
    tag_cleaner_widget.plainTextEditPrompt.setPlainText("cat, dog")

    tag_cleaner_widget.on_pushButtonConvert_clicked()

    assert "Error" in tag_cleaner_widget.plainTextEditResult.toPlainText()


@pytest.mark.db_tools
def test_tag_cleaner_widget_initialize_legacy_method(qtbot, tag_cleaner_widget):
    """initialize() legacy メソッドが動作する"""
    new_service = MockTagCleanerService()

    tag_cleaner_widget.initialize(new_service)

    assert tag_cleaner_widget._cleaner_service is new_service
