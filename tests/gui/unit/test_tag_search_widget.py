"""TagSearchWidget のテスト（pytest-qt ベース）"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest
from pydantic import ValidationError
from PySide6.QtWidgets import QMessageBox

from genai_tag_db_tools.gui.widgets.tag_search import TagSearchWidget
from genai_tag_db_tools.services.app_services import TagSearchService


class MockTagSearchService(TagSearchService):
    """TagSearchService のモック"""

    def __init__(self):
        """シグナルなしで初期化"""
        self.mock_get_tag_formats = MagicMock(return_value=["danbooru", "e621"])
        self.mock_get_tag_languages = MagicMock(return_value=["en", "ja"])
        self.mock_get_tag_types = MagicMock(return_value=["character", "general"])
        self.mock_search_tags = MagicMock(
            return_value=pl.DataFrame(
                [
                    {
                        "tag": "cat",
                        "translations": {"ja": ["猫"]},
                        "format_statuses": {
                            "danbooru": {
                                "alias": False,
                                "deprecated": False,
                                "usage_count": 50,
                                "type_id": 0,
                                "type_name": "general",
                            }
                        },
                    }
                ]
            )
        )

    def get_tag_formats(self) -> list[str]:
        return self.mock_get_tag_formats()

    def get_tag_languages(self) -> list[str]:
        return self.mock_get_tag_languages()

    def get_tag_types(self, format_name: str | None) -> list[str]:
        return self.mock_get_tag_types(format_name)

    def search_tags(self, **kwargs: Any) -> pl.DataFrame:
        return self.mock_search_tags(**kwargs)


@pytest.fixture
def tag_search_widget(qtbot):
    """TagSearchWidget fixture with mock service"""
    service = MockTagSearchService()
    widget = TagSearchWidget(service=service, parent=None)
    qtbot.addWidget(widget)
    return widget


@pytest.mark.db_tools
def test_tag_search_widget_initialization(qtbot):
    """Widget が正しく初期化される"""
    service = MockTagSearchService()
    widget = TagSearchWidget(service=service)
    qtbot.addWidget(widget)

    assert widget._service is service
    assert widget._initialized is False
    assert widget._results_model is not None
    assert widget._results_view is not None


@pytest.mark.db_tools
def test_tag_search_widget_set_service(qtbot, tag_search_widget):
    """set_service() でサービスを設定できる"""
    new_service = MockTagSearchService()
    tag_search_widget.set_service(new_service)

    assert tag_search_widget._service is new_service
    assert tag_search_widget._initialized is False


@pytest.mark.db_tools
def test_tag_search_widget_showEvent_initializes_ui(qtbot, tag_search_widget):
    """showEvent() で UI が初期化される"""
    tag_search_widget.show()
    qtbot.waitExposed(tag_search_widget)

    assert tag_search_widget._initialized is True
    assert tag_search_widget.comboBoxFormat.count() > 0
    assert tag_search_widget.comboBoxLanguage.count() > 0


@pytest.mark.db_tools
def test_tag_search_widget_initialize_ui_populates_combos(qtbot, tag_search_widget):
    """initialize_ui() でコンボボックスが設定される"""
    tag_search_widget.initialize_ui()

    # Format combo: "All" + formats
    assert tag_search_widget.comboBoxFormat.count() == 3
    assert tag_search_widget.comboBoxFormat.itemText(0) == "All"
    assert tag_search_widget.comboBoxFormat.itemText(1) == "danbooru"

    # Language combo: "All" + languages
    assert tag_search_widget.comboBoxLanguage.count() == 3
    assert tag_search_widget.comboBoxLanguage.itemText(0) == "All"


@pytest.mark.db_tools
def test_tag_search_widget_build_query_partial_search(qtbot, tag_search_widget):
    """_build_query() で部分検索クエリを構築できる"""
    tag_search_widget.lineEditKeyword.setText("cat")
    tag_search_widget.radioButtonPartial.setChecked(True)

    query = tag_search_widget._build_query()

    assert query.keyword == "cat"
    assert query.partial is True


@pytest.mark.db_tools
def test_tag_search_widget_build_query_exact_search(qtbot, tag_search_widget):
    """_build_query() で完全一致検索クエリを構築できる"""
    tag_search_widget.lineEditKeyword.setText("cat")
    tag_search_widget.radioButtonExact.setChecked(True)

    query = tag_search_widget._build_query()

    assert query.keyword == "cat"
    assert query.partial is False


@pytest.mark.db_tools
def test_tag_search_widget_build_query_with_format(qtbot, tag_search_widget):
    """_build_query() でフォーマット指定クエリを構築できる"""
    tag_search_widget.initialize_ui()
    tag_search_widget.comboBoxFormat.setCurrentText("danbooru")

    query = tag_search_widget._build_query()

    assert query.format_name == "danbooru"


@pytest.mark.db_tools
def test_tag_search_widget_build_query_normalizes_all(qtbot, tag_search_widget):
    """_build_query() で "All" を None に正規化する"""
    tag_search_widget.initialize_ui()
    tag_search_widget.comboBoxFormat.setCurrentText("All")

    query = tag_search_widget._build_query()

    assert query.format_name is None


@pytest.mark.db_tools
def test_tag_search_widget_search_button_executes_search(qtbot, tag_search_widget, monkeypatch):
    """検索ボタンクリックで検索が実行される"""
    tag_search_widget.lineEditKeyword.setText("cat")

    # MessageBox を無効化
    monkeypatch.setattr(QMessageBox, "critical", MagicMock())
    monkeypatch.setattr(QMessageBox, "warning", MagicMock())

    tag_search_widget.on_pushButtonSearch_clicked()

    tag_search_widget._service.mock_search_tags.assert_called_once()
    assert tag_search_widget._results_model.rowCount(None) > 0


@pytest.mark.db_tools
def test_tag_search_widget_search_updates_model(qtbot, tag_search_widget, monkeypatch):
    """検索結果がモデルに反映される"""
    tag_search_widget.lineEditKeyword.setText("cat")

    monkeypatch.setattr(QMessageBox, "critical", MagicMock())

    tag_search_widget.on_pushButtonSearch_clicked()

    assert tag_search_widget._results_model.rowCount(None) == 1


@pytest.mark.db_tools
def test_tag_search_widget_search_handles_validation_error(qtbot, tag_search_widget, monkeypatch):
    """検索時の ValidationError を処理する"""
    tag_search_widget._service.mock_search_tags.side_effect = ValidationError.from_exception_data(
        "test",
        [
            {
                "type": "value_error",
                "loc": ("test",),
                "msg": "Test error",
                "input": None,
                "ctx": {"error": "Test error"},
            }
        ],
    )

    mock_critical = MagicMock()
    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    error_messages = []

    def capture_error(msg: str):
        error_messages.append(msg)

    tag_search_widget.error_occurred.connect(capture_error)

    tag_search_widget.on_pushButtonSearch_clicked()

    mock_critical.assert_called_once()
    assert len(error_messages) == 1


@pytest.mark.db_tools
def test_tag_search_widget_search_handles_file_not_found(qtbot, tag_search_widget, monkeypatch):
    """検索時の FileNotFoundError を処理する"""
    tag_search_widget._service.mock_search_tags.side_effect = FileNotFoundError("Database not found")

    mock_warning = MagicMock()
    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    error_messages = []

    def capture_error(msg: str):
        error_messages.append(msg)

    tag_search_widget.error_occurred.connect(capture_error)

    tag_search_widget.on_pushButtonSearch_clicked()

    mock_warning.assert_called_once()
    assert len(error_messages) == 1


@pytest.mark.db_tools
def test_tag_search_widget_search_handles_unexpected_error(qtbot, tag_search_widget, monkeypatch):
    """検索時の予期しないエラーを処理する"""
    tag_search_widget._service.mock_search_tags.side_effect = RuntimeError("Unexpected error")

    mock_critical = MagicMock()
    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    error_messages = []

    def capture_error(msg: str):
        error_messages.append(msg)

    tag_search_widget.error_occurred.connect(capture_error)

    tag_search_widget.on_pushButtonSearch_clicked()

    mock_critical.assert_called_once()
    assert len(error_messages) == 1


@pytest.mark.db_tools
def test_tag_search_widget_update_type_combo_box_all_format(qtbot, tag_search_widget):
    """update_type_combo_box() で "All" フォーマット時に全タイプを取得"""
    tag_search_widget.initialize_ui()
    tag_search_widget.comboBoxFormat.setCurrentText("All")

    tag_search_widget.update_type_combo_box()

    assert tag_search_widget.comboBoxType.count() > 0
    tag_search_widget._service.mock_get_tag_types.assert_called_with(None)


@pytest.mark.db_tools
def test_tag_search_widget_update_type_combo_box_specific_format(qtbot, tag_search_widget):
    """update_type_combo_box() で特定フォーマット時にそのタイプを取得"""
    tag_search_widget.initialize_ui()
    tag_search_widget.comboBoxFormat.setCurrentText("danbooru")

    tag_search_widget.update_type_combo_box()

    assert tag_search_widget.comboBoxType.count() > 0
    tag_search_widget._service.mock_get_tag_types.assert_called_with("danbooru")


@pytest.mark.db_tools
def test_tag_search_widget_save_search_not_implemented(qtbot, tag_search_widget, caplog):
    """on_pushButtonSaveSearch_clicked() で未実装ログを出力"""
    import logging

    with caplog.at_level(logging.INFO):
        tag_search_widget.on_pushButtonSaveSearch_clicked()

    assert "not yet implemented" in caplog.text.lower()


@pytest.mark.db_tools
def test_tag_search_widget_result_count_label_initialization(qtbot, tag_search_widget):
    """結果件数表示ラベルが初期化される"""
    tag_search_widget._setup_results_view()

    assert tag_search_widget._result_count_label is not None
    assert "0" in tag_search_widget._result_count_label.text()


@pytest.mark.db_tools
def test_tag_search_widget_result_count_label_updates_after_search(qtbot, tag_search_widget, monkeypatch):
    """検索実行後に結果件数が更新される"""
    tag_search_widget.lineEditKeyword.setText("cat")
    tag_search_widget._setup_results_view()

    # MessageBox を無効化
    monkeypatch.setattr(QMessageBox, "critical", MagicMock())
    monkeypatch.setattr(QMessageBox, "warning", MagicMock())

    tag_search_widget.on_pushButtonSearch_clicked()

    # 件数ラベルが更新される(モックサービスは1件返す)
    assert tag_search_widget._result_count_label is not None
    assert "1" in tag_search_widget._result_count_label.text()


@pytest.mark.db_tools
def test_tag_search_widget_search_uses_unlimited_limit(qtbot, tag_search_widget, monkeypatch):
    """検索時にlimitパラメータなし（無制限）で実行される"""
    tag_search_widget.lineEditKeyword.setText("cat")

    # MessageBox を無効化
    monkeypatch.setattr(QMessageBox, "critical", MagicMock())

    tag_search_widget.on_pushButtonSearch_clicked()

    # search_tagsが呼ばれた際の引数を確認
    call_kwargs = tag_search_widget._service.mock_search_tags.call_args.kwargs

    # limit パラメータが渡されていないか、Noneであることを確認
    assert "limit" not in call_kwargs or call_kwargs.get("limit") is None


@pytest.mark.db_tools
def test_tag_search_widget_result_count_label_updates_with_multiple_results(
    qtbot, tag_search_widget, monkeypatch
):
    """複数件の検索結果で件数表示が正しく更新される"""
    # モックサービスを3件返すように変更
    tag_search_widget._service.mock_search_tags.return_value = pl.DataFrame(
        [
            {
                "tag": "cat",
                "translations": {"ja": ["猫"]},
                "format_statuses": {
                    "danbooru": {
                        "alias": False,
                        "deprecated": False,
                        "usage_count": 50,
                        "type_id": 0,
                        "type_name": "general",
                    }
                },
            },
            {
                "tag": "dog",
                "translations": {"ja": ["犬"]},
                "format_statuses": {
                    "danbooru": {
                        "alias": False,
                        "deprecated": False,
                        "usage_count": 30,
                        "type_id": 0,
                        "type_name": "general",
                    }
                },
            },
            {
                "tag": "bird",
                "translations": {"ja": ["鳥"]},
                "format_statuses": {
                    "danbooru": {
                        "alias": False,
                        "deprecated": False,
                        "usage_count": 20,
                        "type_id": 0,
                        "type_name": "general",
                    }
                },
            },
        ]
    )

    tag_search_widget.lineEditKeyword.setText("animal")
    tag_search_widget._setup_results_view()

    # MessageBox を無効化
    monkeypatch.setattr(QMessageBox, "critical", MagicMock())

    tag_search_widget.on_pushButtonSearch_clicked()

    # 件数ラベルが3件を表示
    assert tag_search_widget._result_count_label is not None
    assert "3" in tag_search_widget._result_count_label.text()
