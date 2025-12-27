"""TagCleanerWidget 縺ｮ繝・せ繝茨ｼ・ytest-qt 繝吶・繧ｹ・・""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from genai_tag_db_tools.gui.widgets.tag_cleaner import TagCleanerWidget
from genai_tag_db_tools.services.app_services import TagCleanerService


class MockTagCleanerService(TagCleanerService):
    """TagCleanerService 縺ｮ繝｢繝・け"""

    def __init__(self):
        self.mock_get_tag_formats = MagicMock(return_value=["danbooru", "e621"])
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
    """Widget 縺梧ｭ｣縺励￥蛻晄悄蛹悶＆繧後ｋ"""
    service = MockTagCleanerService()
    widget = TagCleanerWidget(parent=None, service=service)
    qtbot.addWidget(widget)

    assert widget._cleaner_service is service
    assert widget._initialized is False


@pytest.mark.db_tools
def test_tag_cleaner_widget_set_service(qtbot, tag_cleaner_widget):
    """set_service() 縺ｧ繧ｵ繝ｼ繝薙せ繧定ｨｭ螳壹〒縺阪ｋ"""
    new_service = MockTagCleanerService()
    tag_cleaner_widget.set_service(new_service)

    assert tag_cleaner_widget._cleaner_service is new_service
    assert tag_cleaner_widget._initialized is False


@pytest.mark.db_tools
def test_tag_cleaner_widget_showEvent_initializes_ui(qtbot, tag_cleaner_widget):
    """showEvent() 縺ｧ UI 縺悟・譛溷喧縺輔ｌ繧・""
    tag_cleaner_widget.show()
    qtbot.waitExposed(tag_cleaner_widget)

    assert tag_cleaner_widget._initialized is True
    assert tag_cleaner_widget.comboBoxFormat.count() > 0


@pytest.mark.db_tools
def test_tag_cleaner_widget_initialize_ui_populates_formats(qtbot, tag_cleaner_widget):
    """_initialize_ui() 縺ｧ繝輔か繝ｼ繝槭ャ繝医さ繝ｳ繝懊′險ｭ螳壹＆繧後ｋ"""
    tag_cleaner_widget._initialize_ui()

    assert tag_cleaner_widget.comboBoxFormat.count() == 2
    assert tag_cleaner_widget.comboBoxFormat.currentText() == "danbooru"


@pytest.mark.db_tools
def test_tag_cleaner_widget_convert_button_executes_conversion(qtbot, tag_cleaner_widget):
    """螟画鋤繝懊ち繝ｳ繧ｯ繝ｪ繝・け縺ｧ螟画鋤縺悟ｮ溯｡後＆繧後ｋ"""
    tag_cleaner_widget._initialize_ui()
    tag_cleaner_widget.plainTextEditPrompt.setPlainText("cat, dog")
    tag_cleaner_widget.comboBoxFormat.setCurrentText("danbooru")

    tag_cleaner_widget.on_pushButtonConvert_clicked()

    tag_cleaner_widget._cleaner_service.mock_convert_prompt.assert_called_once_with("cat, dog", "danbooru")
    assert tag_cleaner_widget.plainTextEditResult.toPlainText() == "converted, tags"


@pytest.mark.db_tools
def test_tag_cleaner_widget_convert_button_handles_no_service(qtbot, tag_cleaner_widget):
    """螟画鋤繝懊ち繝ｳ繧ｯ繝ｪ繝・け縺ｧ繧ｵ繝ｼ繝薙せ縺後↑縺・ｴ蜷医・繧ｨ繝ｩ繝ｼ蜃ｦ逅・""
    tag_cleaner_widget._cleaner_service = None
    tag_cleaner_widget.plainTextEditPrompt.setPlainText("cat, dog")

    tag_cleaner_widget.on_pushButtonConvert_clicked()

    assert "Error" in tag_cleaner_widget.plainTextEditResult.toPlainText()


@pytest.mark.db_tools
def test_tag_cleaner_widget_initialize_legacy_method(qtbot, tag_cleaner_widget):
    """initialize() legacy 繝｡繧ｽ繝・ラ縺悟虚菴懊☆繧・""
    new_service = MockTagCleanerService()

    tag_cleaner_widget.initialize(new_service)

    assert tag_cleaner_widget._cleaner_service is new_service


@pytest.mark.db_tools
def test_tag_cleaner_widget_set_service_after_show_initializes(qtbot):
    """Initialize when service is set after showing."""
    widget = TagCleanerWidget(parent=None, service=None)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    service = MockTagCleanerService()
    widget.set_service(service)

    assert widget._initialized is True
    assert widget.comboBoxFormat.currentText() == "danbooru"
