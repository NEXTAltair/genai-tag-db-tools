"""TagRegisterWidget のテスト（pytest-qt ベース）"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest
from pydantic import ValidationError
from PySide6.QtWidgets import QApplication, QMessageBox

from genai_tag_db_tools.gui.widgets.tag_register import TagRegisterWidget
from genai_tag_db_tools.services.app_services import (
    TagRegisterService,
    TagSearchService,
)


class MockTagSearchService(TagSearchService):
    """TagSearchService のモック"""

    def __init__(self):
        self.mock_get_tag_formats = MagicMock(return_value=["danbooru", "e621"])
        self.mock_get_tag_languages = MagicMock(return_value=["english", "japanese"])
        self.mock_get_tag_types = MagicMock(return_value=["character", "general"])

    def get_tag_formats(self) -> list[str]:
        return self.mock_get_tag_formats()

    def get_tag_languages(self) -> list[str]:
        return self.mock_get_tag_languages()

    def get_tag_types(self, format_name: str | None) -> list[str]:
        return self.mock_get_tag_types(format_name)


class MockTagRegisterService(TagRegisterService):
    """TagRegisterService のモック"""

    def __init__(self):
        self.mock_register_or_update_tag = MagicMock(return_value=123)
        self.mock_get_tag_details = MagicMock(
            return_value=pl.DataFrame([{"tag": "cat", "type": "general", "usage_count": 50}])
        )

    def register_or_update_tag(self, tag_info: dict) -> int:
        return self.mock_register_or_update_tag(tag_info)

    def get_tag_details(self, tag_id: int) -> pl.DataFrame:
        return self.mock_get_tag_details(tag_id)


@pytest.fixture
def tag_register_widget(qtbot):
    """TagRegisterWidget fixture with mock services"""
    search_service = MockTagSearchService()
    register_service = MockTagRegisterService()
    widget = TagRegisterWidget(
        parent=None, search_service=search_service, register_service=register_service
    )
    qtbot.addWidget(widget)
    return widget


@pytest.mark.db_tools
def test_tag_register_widget_initialization(qtbot):
    """Widget が正しく初期化される"""
    search_service = MockTagSearchService()
    register_service = MockTagRegisterService()
    widget = TagRegisterWidget(
        parent=None, search_service=search_service, register_service=register_service
    )
    qtbot.addWidget(widget)

    assert widget.search_service is search_service
    assert widget.register_service is register_service
    assert widget._initialized is False


@pytest.mark.db_tools
def test_tag_register_widget_set_services(qtbot, tag_register_widget):
    """set_services() でサービスを設定できる"""
    new_search = MockTagSearchService()
    new_register = MockTagRegisterService()

    tag_register_widget.set_services(new_search, new_register)

    assert tag_register_widget.search_service is new_search
    assert tag_register_widget.register_service is new_register
    assert tag_register_widget._initialized is False


@pytest.mark.db_tools
def test_tag_register_widget_showEvent_initializes_ui(qtbot, tag_register_widget):
    """showEvent() で UI が初期化される"""
    tag_register_widget.show()
    qtbot.waitExposed(tag_register_widget)

    assert tag_register_widget._initialized is True
    assert tag_register_widget.comboBoxFormat.count() > 0
    assert tag_register_widget.comboBoxLanguage.count() > 0


@pytest.mark.db_tools
def test_tag_register_widget_initialize_ui_populates_combos(qtbot, tag_register_widget):
    """initialize_ui() でコンボボックスが設定される"""
    tag_register_widget.initialize_ui()

    # Format combo
    assert tag_register_widget.comboBoxFormat.count() == 2
    assert tag_register_widget.comboBoxFormat.itemText(0) == "danbooru"

    # Language combo
    assert tag_register_widget.comboBoxLanguage.count() == 2
    assert tag_register_widget.comboBoxLanguage.currentText() == "japanese"


@pytest.mark.db_tools
def test_tag_register_widget_format_change_updates_types(qtbot, tag_register_widget):
    """フォーマット変更でタイプコンボが更新される"""
    tag_register_widget.initialize_ui()
    tag_register_widget.comboBoxFormat.setCurrentText("danbooru")

    tag_register_widget.on_comboBoxFormat_currentIndexChanged()

    assert tag_register_widget.comboBoxType.count() > 0


@pytest.mark.db_tools
def test_tag_register_widget_register_button_success(qtbot, tag_register_widget, monkeypatch):
    """登録ボタンクリックでタグが登録される"""
    tag_register_widget.initialize_ui()
    tag_register_widget.lineEditTag.setText("cat")
    tag_register_widget.comboBoxFormat.setCurrentText("danbooru")

    monkeypatch.setattr(QMessageBox, "warning", MagicMock())
    monkeypatch.setattr(QMessageBox, "critical", MagicMock())

    tag_register_widget.on_pushButtonRegister_clicked()

    tag_register_widget.register_service.mock_register_or_update_tag.assert_called_once()
    assert tag_register_widget.lineEditTag.text() == ""  # cleared after success


@pytest.mark.db_tools
def test_tag_register_widget_register_handles_validation_error(qtbot, tag_register_widget, monkeypatch):
    """登録時の ValidationError を処理する"""
    tag_register_widget.initialize_ui()

    tag_register_widget.register_service.mock_register_or_update_tag.side_effect = (
        ValidationError.from_exception_data(
            "test",
            [
                {
                    "type": "value_error",
                    "loc": ("tag",),
                    "msg": "Invalid tag",
                    "input": None,
                    "ctx": {"error": "Invalid tag"},
                }
            ],
        )
    )

    mock_warning = MagicMock()
    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    tag_register_widget.lineEditTag.setText("invalid tag")
    tag_register_widget.on_pushButtonRegister_clicked()

    mock_warning.assert_called_once()


@pytest.mark.db_tools
def test_tag_register_widget_register_handles_value_error(qtbot, tag_register_widget, monkeypatch):
    """登録時の ValueError を処理する"""
    tag_register_widget.initialize_ui()

    tag_register_widget.register_service.mock_register_or_update_tag.side_effect = ValueError(
        "Invalid value"
    )

    mock_warning = MagicMock()
    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    tag_register_widget.lineEditTag.setText("cat")
    tag_register_widget.on_pushButtonRegister_clicked()

    mock_warning.assert_called_once()


@pytest.mark.db_tools
def test_tag_register_widget_register_handles_unexpected_error(qtbot, tag_register_widget, monkeypatch):
    """登録時の予期しないエラーを処理する"""
    tag_register_widget.initialize_ui()

    tag_register_widget.register_service.mock_register_or_update_tag.side_effect = RuntimeError(
        "Unexpected error"
    )

    mock_critical = MagicMock()
    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    tag_register_widget.lineEditTag.setText("cat")
    tag_register_widget.on_pushButtonRegister_clicked()

    mock_critical.assert_called_once()


@pytest.mark.db_tools
def test_tag_register_widget_import_button_loads_clipboard(qtbot, tag_register_widget, monkeypatch):
    """インポートボタンでクリップボードからタグを読み込む"""
    clipboard = QApplication.clipboard()
    clipboard.setText("test_tag")

    tag_register_widget.on_pushButtonImport_clicked()

    assert tag_register_widget.lineEditTag.text() == "test_tag"


@pytest.mark.db_tools
def test_tag_register_widget_clear_fields_resets_form(qtbot, tag_register_widget):
    """clear_fields() でフォームがリセットされる"""
    tag_register_widget.initialize_ui()
    tag_register_widget.lineEditTag.setText("cat")
    tag_register_widget.lineEditSourceTag.setText("source_tag")
    tag_register_widget.spinBoxUseCount.setValue(100)

    tag_register_widget.clear_fields()

    assert tag_register_widget.lineEditTag.text() == ""
    assert tag_register_widget.lineEditSourceTag.text() == ""
    assert tag_register_widget.spinBoxUseCount.value() == 0
