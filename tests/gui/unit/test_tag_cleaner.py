import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
from genai_tag_db_tools.gui.widgets.tag_cleaner import TagCleanerWidget


@pytest.fixture
def widget_fixture(qtbot):
    """
    pytest-qt でウィジェットを生成し、テスト後に破棄するためのフィクスチャ。
    """
    widget = TagCleanerWidget()
    qtbot.addWidget(widget)  # ウィジェットをテスト管理下に置く
    return widget


def test_initialize(widget_fixture):
    """
    タグ検索(変換)サービスをモック化し、initialize() でコンボボックスに
    正しいフォーマットが追加されるか確認する。
    """
    # モックのサービス(またはTagCleanerService相当)を用意
    mock_service = MagicMock()
    mock_service.get_tag_formats.return_value = ["formatA", "formatB"]

    # ウィジェットのinitialize()を呼ぶ
    widget_fixture.initialize(mock_service)

    # コンボボックスにアイテムが追加されたか検証
    combo = widget_fixture.comboBoxFormat
    assert combo.count() == 2
    assert combo.itemText(0) == "formatA"
    assert combo.itemText(1) == "formatB"


def test_on_pushButtonConvert_clicked(widget_fixture, qtbot):
    """
    - plainTextEditPrompt に入力した文字列が、サービスの convert_prompt() に渡されるか
    - 戻り値が plainTextEditResult にセットされるか
    を確認する。
    """
    mock_service = MagicMock()
    mock_service.get_tag_formats.return_value = ["mockFormat"]
    mock_service.convert_prompt.return_value = "converted_tags"

    # initialize して、モックサービスをセット
    widget_fixture.initialize(mock_service)

    # prompt入力欄に文字列をセット
    widget_fixture.plainTextEditPrompt.setPlainText("original_tags")

    # コンボボックスの選択を模擬（本来はUI操作だが、直接セットでもOK）
    widget_fixture.comboBoxFormat.setCurrentText("mockFormat")

    # ボタン押下のシグナルをトリガー (あるいは直接メソッド呼び出しでもOK)
    with qtbot.waitSignal(widget_fixture.plainTextEditResult.textChanged, timeout=1000):
        # 直接 Slot を呼び出すサンプル
        widget_fixture.on_pushButtonConvert_clicked()
        # もしGUIのbutton.clicked.connect(...) をテストしたい場合：
        # widget_fixture.pushButtonConvert.click()

    # モックが呼ばれたか
    mock_service.convert_prompt.assert_called_once_with("original_tags", "mockFormat")

    # 結果が setPlainText() されたか
    assert widget_fixture.plainTextEditResult.toPlainText() == "converted_tags"


def test_on_pushButtonConvert_clicked_no_service(widget_fixture, qtbot):
    """
    もしinitialize() でサービス未設定のままボタンを押すと、
    エラー扱いになる仕様ならその動作を検証する。
    例として、いきなり on_pushButtonConvert_clicked() を呼んだ場合。
    """
    # plainTextEditPromptに何か入れておく
    widget_fixture.plainTextEditPrompt.setPlainText("test input")

    # コンボボックスの選択肢も何もない状態
    # 直接スロット呼び出し
    with qtbot.waitSignal(widget_fixture.plainTextEditResult.textChanged, timeout=1000):
        widget_fixture.on_pushButtonConvert_clicked()

    # 例: "Error: service not set" のような文言を表示する仕様ならその確認
    # (実際の仕様に合わせてチェック)
    assert widget_fixture.plainTextEditResult.toPlainText() != ""
    # もしくは「空のままである」等、仕様に合わせて検証する
