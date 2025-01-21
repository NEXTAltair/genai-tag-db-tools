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
    format_id = mock_tag_repo.get_format_id("e621")
    result = tag_searcher.convert_tag("original_tag", format_id)

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

    format_id = mock_tag_repo.get_format_id("danbooru")
    result = tag_searcher.convert_tag("some_tag", format_id)
    assert result == "some_tag"
    mock_tag_repo.get_tag_by_id.assert_not_called()

def test_convert_tag_no_tag_in_db(tag_searcher, mock_tag_repo):
    """
    DBにタグが存在しない場合、元のタグを返す。
    """
    mock_tag_repo.get_format_id.return_value = 1
    mock_tag_repo.get_tag_id_by_name.return_value = None  # 見つからない

    format_id = mock_tag_repo.get_format_id("danbooru")
    result = tag_searcher.convert_tag("unknown_tag", format_id)
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
        format_id = mock_tag_repo.get_format_id("derpibooru")
        result = tag_searcher.convert_tag("test_tag", format_id)
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

    format_id = mock_tag_repo.get_format_id("danbooru")
    result = tag_searcher.convert_tag("tag_in_db", format_id)
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

def test_search_tags_with_logging(tag_searcher, mock_tag_repo, caplog):
    """
    ログ出力のテスト。
    79-80行のカバレッジ用。
    """
    with caplog.at_level("INFO"):
        mock_tag_repo.search_tag_ids.return_value = [1]
        mock_tag_repo.get_tag_by_id.return_value = MagicMock(tag="tag1", source_tag="src1")
        mock_tag_repo.get_translations.return_value = []

        result = tag_searcher.search_tags("test", partial=True)
        assert len(result) == 1
        assert "search_tags" in caplog.text
        assert "test" in caplog.text  # キーワードがログに含まれているか
        assert "partial=True" in caplog.text  # パラメータがログに含まれているか

def test_search_tags_with_format_all(tag_searcher, mock_tag_repo):
    """
    フォーマット名が "All" の場合のテスト。
    97, 106-107行のカバレッジ用。
    """
    mock_tag_repo.search_tag_ids.return_value = [1, 2]
    mock_tag_repo.get_tag_by_id.side_effect = lambda id: {
        1: MagicMock(tag=f"tag{id}", source_tag=f"src{id}"),
        2: MagicMock(tag=f"tag{id}", source_tag=f"src{id}")
    }.get(id)
    mock_tag_repo.get_translations.return_value = []

    result = tag_searcher.search_tags("test", format_name="All")
    assert len(result) == 2
    # フォーマットによる絞り込みは呼ばれないはず
    mock_tag_repo.search_tag_ids_by_format_name.assert_not_called()

def test_search_tags_with_alias_and_status(tag_searcher, mock_tag_repo):
    """
    エイリアスフィルターとステータスの組み合わせテスト。
    120-121, 129-131行のカバレッジ用。
    """
    mock_tag_repo.search_tag_ids.return_value = [1, 2]
    mock_tag_repo.get_format_id.return_value = 1
    mock_tag_repo.search_tag_ids_by_format_name.return_value = [1, 2]
    mock_tag_repo.search_tag_ids_by_alias.return_value = [1]

    # タグ情報
    mock_tag_repo.get_tag_by_id.side_effect = lambda id: {
        1: MagicMock(tag=f"tag{id}", source_tag=f"src{id}")
    }.get(id)
    mock_tag_repo.get_translations.return_value = []

    # ステータス情報
    mock_status = MagicMock(alias=True, type_id=None)  # type_id が None
    mock_tag_repo.get_tag_status.return_value = mock_status

    result = tag_searcher.search_tags(
        "test",
        format_name="e621",
        alias=True
    )
    assert len(result) == 1
    assert result["tag"].to_list() == ["tag1"]
    assert result["type_name"].to_list() == [""]  # type_id が None なので空文字

def test_search_tags_collect_info_with_translations(tag_searcher, mock_tag_repo):
    """
    タグ情報収集で翻訳がある場合のテスト。
    148-149, 157行のカバレッジ用。
    """
    mock_tag_repo.search_tag_ids.return_value = [1]
    mock_tag_repo.get_tag_by_id.return_value = MagicMock(tag="tag1", source_tag="src1")
    mock_tag_repo.get_translations.return_value = [
        MagicMock(language="ja", translation="タグ1"),
        MagicMock(language="en", translation="tag1")
    ]
    mock_tag_repo.get_tag_status.return_value = None

    result = tag_searcher.search_tags("test")
    assert len(result) == 1
    assert result["tag"].to_list() == ["tag1"]
    assert result["translations"].to_list() == [{"ja": "タグ1", "en": "tag1"}]

def test_search_tags_with_invalid_language(tag_searcher, mock_tag_repo):
    """
    存在しない言語を指定した場合のテスト。
    194行のカバレッジ用。
    """
    mock_tag_repo.search_tag_ids.return_value = [1]
    mock_tag_repo.get_tag_by_id.return_value = MagicMock(tag="tag1", source_tag="src1")
    mock_tag_repo.get_translations.return_value = [
        MagicMock(language="ja", translation="タグ1")
    ]

    result = tag_searcher.search_tags("test", language="unknown")
    assert len(result) == 0  # 指定した言語の翻訳がないので0件

def test_get_format_id_with_none(tag_searcher, mock_tag_repo):
    """
    get_format_id に None を渡した場合のテスト。
    292行のカバレッジ用。
    """
    result = tag_searcher.get_format_id(None)
    assert result == 0
    mock_tag_repo.get_format_id.assert_not_called()  # None の場合は呼ばれない

def test_get_tag_types_with_none(tag_searcher, mock_tag_repo):
    """
    get_tag_types に None を渡した場合のテスト。
    format_name が None の場合、get_format_id は None を返し、
    結果として空リストが返される。
    """
    # get_format_id が None を返すケースをテスト
    mock_tag_repo.get_format_id.return_value = None
    # get_tag_types の戻り値を空リストに設定
    mock_tag_repo.get_tag_types.return_value = []

    result = tag_searcher.get_tag_types(None)
    assert result == []
    mock_tag_repo.get_format_id.assert_called_once_with(None)  # None を引数として呼ばれる
    mock_tag_repo.get_tag_types.assert_not_called()  # format_id が None なので呼ばれない
