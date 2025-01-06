import pytest
from unittest.mock import MagicMock
from genai_tag_db_tools.services.tag_search import TagSearcher

@pytest.fixture
def mock_tag_repo():
    """
    TagRepository をモック化したフィクスチャ。
    メソッドの戻り値を自由に設定できるようにする。
    """
    return MagicMock()

@pytest.fixture
def tag_searcher(mock_tag_repo, monkeypatch):
    """
    TagSearcher のインスタンスを返すテスト用フィクスチャ。
    ただし内部の self.tag_repo を mock_tag_repo に差し替える。
    """
    # 1) TagSearcher のコンストラクタ内で TagRepository() が呼ばれるのを防ぐため、
    #    monkeypatch を使って強制的にモックを返すようにする、等のアプローチ。
    #    ただし簡易的には TagSearcher() 作成後に tag_searcher.tag_repo = mock_tag_repo でもよい。

    # シンプル実装：TagSearcher生成後に tag_repo を差し替え
    ts = TagSearcher()
    ts.tag_repo = mock_tag_repo
    return ts

def test_convert_tag_found_alias(tag_searcher, mock_tag_repo):
    """
    alias=True のケースで、preferred_tag を取得できたらタグが変換されるかのテスト。
    """
    # --- 1. モックの戻り値をセット ---
    # format_id は 2 とする (例: e621)
    mock_tag_repo.get_format_id.return_value = 2
    # タグの ID は 123
    mock_tag_repo.get_tag_id_by_name.return_value = 123
    # find_preferred_tag で返される ID は 999
    mock_tag_repo.find_preferred_tag.return_value = 999
    # preferred_tag_obj の tag を "alias_tag" として返す
    mock_preferred_tag_obj = MagicMock()
    mock_preferred_tag_obj.tag = "alias_tag"
    mock_tag_repo.get_tag_by_id.return_value = mock_preferred_tag_obj

    # --- 2. テスト実行 ---
    result = tag_searcher.convert_tag("original_tag", "e621")

    # --- 3. 結果検証 ---
    assert result == "alias_tag"
    mock_tag_repo.get_format_id.assert_called_once_with("e621")
    mock_tag_repo.get_tag_id_by_name.assert_called_once_with("original_tag", partial=False)
    mock_tag_repo.find_preferred_tag.assert_called_once_with(123, 2)
    mock_tag_repo.get_tag_by_id.assert_called_once_with(999)

def test_convert_tag_no_alias(tag_searcher, mock_tag_repo):
    """
    alias=False のケース、preferred_tag_id=None でそのまま返す。
    """
    mock_tag_repo.get_format_id.return_value = 1
    mock_tag_repo.get_tag_id_by_name.return_value = 101
    mock_tag_repo.find_preferred_tag.return_value = None  # alias=False とか TagStatusなし
    # get_tag_by_id は呼ばれない想定

    result = tag_searcher.convert_tag("some_tag", "danbooru")
    assert result == "some_tag"
    mock_tag_repo.get_tag_by_id.assert_not_called()

def test_convert_tag_no_tag_in_db(tag_searcher, mock_tag_repo):
    """
    DBにタグが存在しない場合、元のタグを返す。
    """
    mock_tag_repo.get_format_id.return_value = 1
    mock_tag_repo.get_tag_id_by_name.return_value = None  # 見つからない

    result = tag_searcher.convert_tag("unknown_tag", "danbooru")
    assert result == "unknown_tag"
    mock_tag_repo.find_preferred_tag.assert_not_called()
    mock_tag_repo.get_tag_by_id.assert_not_called()

def test_convert_tag_invalid_preferred(tag_searcher, mock_tag_repo, caplog):
    """
    preferred_tag が 'invalid tag' の場合、
    ログを出して元のタグを返す。
    """
    mock_tag_repo.get_format_id.return_value = 3
    mock_tag_repo.get_tag_id_by_name.return_value = 50
    mock_tag_repo.find_preferred_tag.return_value = 60

    mock_preferred_tag_obj = MagicMock()
    mock_preferred_tag_obj.tag = "invalid tag"
    mock_tag_repo.get_tag_by_id.return_value = mock_preferred_tag_obj

    with caplog.at_level("WARNING"):
        result = tag_searcher.convert_tag("test_tag", "derpibooru")
        assert "invalid tag" in caplog.text  # ログに「invalid tag」が出ているか
    assert result == "test_tag"

def test_convert_tag_db_error(tag_searcher, mock_tag_repo):
    """
    preferred_tag_id があるが、それに紐づくTagオブジェクトが取得できない(DB不整合)場合
    元のタグを返す。
    """
    mock_tag_repo.get_format_id.return_value = 1
    mock_tag_repo.get_tag_id_by_name.return_value = 10
    mock_tag_repo.find_preferred_tag.return_value = 20
    mock_tag_repo.get_tag_by_id.return_value = None  # 取得失敗

    result = tag_searcher.convert_tag("tag_in_db", "danbooru")
    assert result == "tag_in_db"

def test_get_tag_types(tag_searcher, mock_tag_repo):
    """
    フォーマットに紐づくタグタイプ一覧を取得。
    """
    mock_tag_repo.get_format_id.return_value = 2
    mock_tag_repo.get_tag_types.return_value = ["general", "artist", "meta"]

    result = tag_searcher.get_tag_types("e621")
    assert result == ["general", "artist", "meta"]
    mock_tag_repo.get_tag_types.assert_called_once_with(2)

def test_get_tag_types_no_format(tag_searcher, mock_tag_repo):
    """
    フォーマット名がDBに無い場合は空リストを返す。
    """
    mock_tag_repo.get_format_id.return_value = None  # フォーマット見つからない

    result = tag_searcher.get_tag_types("unknown_fmt")
    assert result == []

def test_get_tag_languages(tag_searcher, mock_tag_repo):
    """
    言語一覧を取得。
    """
    mock_tag_repo.get_tag_languages.return_value = ["en", "ja", "fr"]
    result = tag_searcher.get_tag_languages()
    assert result == ["en", "ja", "fr"]

def test_get_tag_formats(tag_searcher, mock_tag_repo):
    """
    フォーマット一覧を取得。
    """
    mock_tag_repo.get_tag_formats.return_value = ["danbooru", "e621", "All"]
    result = tag_searcher.get_tag_formats()
    assert result == ["danbooru", "e621", "All"]
