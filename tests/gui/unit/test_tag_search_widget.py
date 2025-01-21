import pytest
from unittest.mock import MagicMock
import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

# TagSearchWidget をインポート
from genai_tag_db_tools.gui.widgets.tag_search import TagSearchWidget
# TagSearchService などサービス層をインポート
from genai_tag_db_tools.services.app_services import TagSearchService

@pytest.fixture
def widget_fixture(qtbot):
    """
    pytest-qt の qtbot で TagSearchWidget を生成し、テスト管理下に置く。
    モック化されたサービスを注入することで、DBアクセスを回避する。
    """
    mock_service = MagicMock(spec=TagSearchService)
    # get_tag_formats() や get_tag_languages() の戻り値を定義
    mock_service.get_tag_formats.return_value = ["formatA", "formatB"]
    mock_service.get_tag_languages.return_value = ["en", "ja"]
    mock_service.get_tag_types.return_value = ["type1", "type2"]

    # 検索結果用の DataFrame サンプル
    # 例: 2行×3列くらい
    sample_df = pl.DataFrame({
        "tag_id": [101, 102],
        "tag": ["cat", "dog"],
        "usage_count": [10, 20]
    })

    # search_tags() が呼ばれたときに sample_df を返す
    mock_service.search_tags.return_value = sample_df

    widget = TagSearchWidget(service=mock_service)
    qtbot.addWidget(widget)
    widget.show()
    return widget, mock_service


def test_initialize_ui(widget_fixture):
    """
    initialize_ui() により、各コンボボックスが正しく初期化されるかをテスト。
    """
    widget, mock_service = widget_fixture

    # comboBoxFormat のアイテムを確認
    format_items = [widget.comboBoxFormat.itemText(i) for i in range(widget.comboBoxFormat.count())]
    assert "All" in format_items
    assert "formatA" in format_items
    assert "formatB" in format_items

    # comboBoxLanguage のアイテムを確認
    lang_items = [widget.comboBoxLanguage.itemText(i) for i in range(widget.comboBoxLanguage.count())]
    assert "All" in lang_items
    assert "en" in lang_items
    assert "ja" in lang_items

def test_on_pushButtonSearch_clicked(widget_fixture, qtbot):
    """
    検索ボタンを押したときに search_tags が呼ばれ、テーブルが更新されるかテスト。
    """
    widget, mock_service = widget_fixture

    # UI操作: キーワードを入力して検索ボタン押下
    widget.lineEditKeyword.setText("cat")
    qtbot.mouseClick(widget.pushButtonSearch, Qt.MouseButton.LeftButton)

    # mock_service.search_tags が呼ばれたか
    mock_service.search_tags.assert_called_once()
    _, call_kwargs = mock_service.search_tags.call_args
    # キーワード引数をチェック
    assert call_kwargs["keyword"] == "cat"
    assert call_kwargs["partial"] == True  # デフォルトのpartial検索設定

    # テーブルに表示されたか確認
    table = widget.tableWidgetResults
    assert table.rowCount() == 2
    assert table.columnCount() == 3

    # 行0, 列0 の Itemを確認
    item_0_0 = table.item(0, 0)
    assert isinstance(item_0_0, QTableWidgetItem)
    assert item_0_0.text() == "101"  # sample_df の "tag_id" 行

    # 行0, 列1 → "cat"
    item_0_1 = table.item(0, 1)
    assert item_0_1.text() == "cat"

def test_empty_result(widget_fixture, qtbot):
    """
    search_tags が空の DataFrame を返した場合、テーブルがクリアされるかテスト。
    """
    widget, mock_service = widget_fixture

    # 空DataFrame を返すように変更
    mock_service.search_tags.return_value = pl.DataFrame([])

    # 検索ボタン押下
    qtbot.mouseClick(widget.pushButtonSearch, Qt.MouseButton.LeftButton)

    # テーブルがクリアされているか
    table = widget.tableWidgetResults
    assert table.rowCount() == 0
    assert table.columnCount() == 0

def test_slider_usage_range(widget_fixture):
    """
    スライダーの get_range() が TagSearchWidget 内で使われるかをテスト。
    ここでは単純に CustomLogScaleSlider のUI操作まではテストせず、値を直接セットして確認。
    """
    widget, mock_service = widget_fixture

    # カスタムスライダー
    slider = widget.customSlider.slider  # QRangeSlider
    # 0〜100 の間でセット ( 例: (25,75) )
    slider.setValue((25, 75))

    # on_pushButtonSearch_clicked 呼び出し
    # (検索ボタンを押す手もあるが、ここでは直接メソッド呼び出しでも可)
    widget.on_pushButtonSearch_clicked()

    # mock_service.search_tags の呼び出しを確認
    _, call_kwargs = mock_service.search_tags.call_args
    assert call_kwargs["min_usage"] is not None
    assert call_kwargs["max_usage"] is not None
    # 具体的に scale_to_count(25), scale_to_count(75) の値を確認したいなら
    # slider.valueChanged等を経由して計算されるため、CustomLogScaleSliderの挙動をモック or assert

@pytest.mark.skip(reason="save 機能未実装のためスキップ")
def test_save_search_button_clicked(widget_fixture, qtbot):
    """
    [保存ボタン] クリック時に on_pushButtonSaveSearch_clicked が呼ばれるか確認。
    実際の保存処理は未実装なので、print のスタブ呼び出しをチェックする。
    """
    widget, _ = widget_fixture

    # stdoutキャプチャなどをする or print をpatch する
    # ここでは簡単にメソッドを直接呼び出すか、ボタンクリックする
    with qtbot.waitSignal(widget.error_occurred, timeout=300, raising=False) as signal_catcher:
        # signal_catcher は "error_occurred" シグナルを待つが、発生しない想定
        qtbot.mouseClick(widget.pushButtonSaveSearch, Qt.MouseButton.LeftButton)

    # シグナルが発行されていないか確認
    # signal_catcher.signal_triggered == False (発火していない) or None
    assert not signal_catcher.signal_triggered
    # 実際には "print" で "[on_pushButtonSaveSearch_clicked] 保存ロジック..." が出るが
    # 現状はそこまでテストせずに済ませる
