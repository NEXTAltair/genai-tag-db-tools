from unittest.mock import MagicMock

import pytest

# テスト対象クラスをインポート
from genai_tag_db_tools.data.tag_repository import TagRepository
from genai_tag_db_tools.db.db_maintenance_tool import DatabaseMaintenanceTool

# ↑ 実際のファイル構成に合わせて import パスを調整してください


@pytest.fixture
def mock_tag_repository() -> MagicMock:
    """
    TagRepositoryのモックを返すフィクスチャ。
    各テストでリポジトリの振る舞いを自由に差し替えられるようにします。
    """
    return MagicMock(spec=TagRepository)


@pytest.fixture
def db_tool(mock_tag_repository) -> DatabaseMaintenanceTool:
    """
    DatabaseMaintenanceToolを初期化し、内部のtag_repositoryをモックに差し替えたものを返すフィクスチャ。
    db_pathはダミー（今回は使用しない）を渡しています。
    """
    tool = DatabaseMaintenanceTool(db_path="dummy_path.db")
    tool.tag_repository = mock_tag_repository
    return tool


def test_detect_duplicates_in_tag_status(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_duplicates_in_tag_status のテスト。
    - list_tag_statuses() が重複ステータスを返すようにモックし、
      期待通りに「重複一覧」が取得できるかを検証。
    """
    # テスト用のダミーデータ: 重複する (tag_id=10, format_id=1) が2つあるケース
    mock_status_dup = MagicMock(tag_id=10, format_id=1, alias=False, preferred_tag_id=20)
    mock_status_dup_2 = MagicMock(tag_id=10, format_id=1, alias=True, preferred_tag_id=30)
    # 通常の一意なステータス
    mock_status_unique = MagicMock(tag_id=15, format_id=2, alias=False, preferred_tag_id=15)

    # TagRepositoryのモック: list_tag_statuses() が上記ステータスを返す
    mock_tag_repository.list_tag_statuses.return_value = [
        mock_status_dup,
        mock_status_dup_2,
        mock_status_unique,
    ]

    # tag_id=10 に紐づく Tagオブジェクト
    mock_tag_10 = MagicMock(tag="duplicate_tag_10")
    # preferred_tag_id=20 / 30 が指すTag
    mock_tag_20 = MagicMock(tag="pref_tag_20")
    mock_tag_30 = MagicMock(tag="pref_tag_30")

    def fake_get_tag_by_id(tag_id):
        if tag_id == 10:
            return mock_tag_10
        elif tag_id == 20:
            return mock_tag_20
        elif tag_id == 30:
            return mock_tag_30
        elif tag_id == 15:
            return MagicMock(tag="unique_tag_15")
        return None

    mock_tag_repository.get_tag_by_id.side_effect = fake_get_tag_by_id

    # フォーマット名リスト （format_idは1開始）
    mock_tag_repository.get_tag_formats.return_value = ["danbooru", "e621", "derpibooru"]

    # 実行
    duplicates = db_tool.detect_duplicates_in_tag_status()

    # 検証:
    # (tag_id=10, format_id=1)が2つ存在するので1件の重複情報が返るはず
    assert len(duplicates) == 1
    dup_info = duplicates[0]
    assert dup_info["tag"] == "duplicate_tag_10"
    assert dup_info["format"] == "danbooru"  # format_id=1 → インデックス0
    # alias, preferred_tag など、最初の status を参照している
    assert dup_info["alias"] == bool(mock_status_dup.alias)
    assert dup_info["preferred_tag"] == "pref_tag_20"


def test_detect_usage_counts_for_tags(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_usage_counts_for_tags のテスト。
    - get_all_tag_ids() / get_tag_by_id() / get_tag_format_ids() / get_usage_count() をモックし、
      使用回数情報が期待通りに取得されるかを検証。
    """
    mock_tag_repository.get_all_tag_ids.return_value = [1, 2]
    mock_tag_repository.get_tag_by_id.side_effect = lambda tid: MagicMock(tag=f"tag_{tid}")

    # フォーマットID: [1,2,3], get_tag_formats()は ["danbooru", "e621", "derpibooru"]
    mock_tag_repository.get_tag_format_ids.return_value = [1, 2, 3]
    mock_tag_repository.get_tag_formats.return_value = ["danbooru", "e621", "derpibooru"]

    # 使用回数のモック: (tag_id, format_id)ごとに返す値
    def fake_get_usage_count(tag_id, format_id):
        # 適当なダミー
        if tag_id == 1 and format_id == 1:
            return 10
        if tag_id == 1 and format_id == 2:
            return 0
        if tag_id == 2 and format_id == 3:
            return 99
        return None

    mock_tag_repository.get_usage_count.side_effect = fake_get_usage_count

    usage_list = db_tool.detect_usage_counts_for_tags()
    # 期待結果:
    # tag_id=1, format_id=1 → use_count=10
    # tag_id=2, format_id=3 → use_count=99
    # それ以外は0 or Noneでスキップ
    assert len(usage_list) == 2

    # 内訳をチェック
    record1 = usage_list[0]
    record2 = usage_list[1]

    # ソートして検証してもOK。ここでは順番どおり来る前提でテスト
    assert record1["tag"] == "tag_1"
    assert record1["format_name"] == "danbooru"
    assert record1["use_count"] == 10

    assert record2["tag"] == "tag_2"
    assert record2["format_name"] == "derpibooru"
    assert record2["use_count"] == 99


def test_detect_foreign_key_issues(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_foreign_key_issues のテスト。
    - list_tag_statuses() が存在しない tag_id を持つステータスを返した場合、
      (tag_id, None) が結果に含まれるかを検証。
    """
    # 存在しないtag_id=99のステータス
    mock_status_1 = MagicMock(tag_id=99, format_id=1, alias=False, preferred_tag_id=None)
    # 正常タグ
    mock_status_2 = MagicMock(tag_id=10, format_id=2, alias=False, preferred_tag_id=10)
    mock_tag_repository.list_tag_statuses.return_value = [mock_status_1, mock_status_2]

    def fake_get_tag_by_id(tag_id):
        if tag_id == 99:
            return None  # 存在しない
        return MagicMock(tag="some_valid_tag")

    mock_tag_repository.get_tag_by_id.side_effect = fake_get_tag_by_id

    issues = db_tool.detect_foreign_key_issues()
    assert len(issues) == 1
    assert issues[0] == (99, None)


def test_detect_orphan_records(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_orphan_records のテスト。
    - 孤立した翻訳 / ステータス / usage_counts を想定しているが、
      ここでは翻訳とステータスのみ簡易的に検証。
    """
    # get_all_tag_ids は [1,2]
    mock_tag_repository.get_all_tag_ids.return_value = [1, 2]

    # タグ1,2 は存在
    mock_tag_repository.get_tag_by_id.side_effect = (
        lambda tid: MagicMock(tag=f"tag_{tid}") if tid in [1, 2] else None
    )

    # 翻訳: tag_id=2→OK, tag_id=99→孤立
    mock_translation_1 = MagicMock(tag_id=2, language="en", translation="foo")
    mock_translation_2 = MagicMock(tag_id=99, language="ja", translation="bar")

    def fake_get_translations(tag_id):
        if tag_id == 1:
            return []
        elif tag_id == 2:
            return [mock_translation_1, mock_translation_2]
        return []

    mock_tag_repository.get_translations.side_effect = fake_get_translations

    # ステータス: tag_id=2→OK, tag_id=3→孤立
    mock_status_ok = MagicMock(tag_id=2, format_id=1)
    mock_status_orphan = MagicMock(tag_id=3, format_id=1)
    mock_tag_repository.list_tag_statuses.return_value = [mock_status_ok, mock_status_orphan]

    orphans = db_tool.detect_orphan_records()
    # 期待: translations に(99,)が, status に(3,)が含まれる
    assert len(orphans["translations"]) == 1
    assert orphans["translations"][0] == (99,)
    assert len(orphans["status"]) == 1
    assert orphans["status"][0] == (3,)
    # usage_countsは未実装で空想定
    assert len(orphans["usage_counts"]) == 0


def test_detect_inconsistent_alias_status(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_inconsistent_alias_status のテスト。
    - alias=Falseなのにpreferred_tag_id != tag_id
    - alias=True なのにpreferred_tag_id == tag_id
    """
    s1 = MagicMock(tag_id=10, format_id=1, alias=False, preferred_tag_id=11)  # 不整合
    s2 = MagicMock(tag_id=20, format_id=1, alias=True, preferred_tag_id=20)  # 不整合
    s3 = MagicMock(tag_id=30, format_id=2, alias=False, preferred_tag_id=30)  # OK
    s4 = MagicMock(tag_id=40, format_id=2, alias=True, preferred_tag_id=50)  # OK
    mock_tag_repository.list_tag_statuses.return_value = [s1, s2, s3, s4]

    results = db_tool.detect_inconsistent_alias_status()
    assert len(results) == 2

    # 個別チェック
    inconsistent1 = results[0]
    inconsistent2 = results[1]

    # どちらが先でもよいが alias=False and pref!=tag_id なら reason=...
    all_reasons = [r["reason"] for r in results]
    assert "alias=Falseなのにpreferred_tag_id != tag_id" in all_reasons
    assert "alias=Trueなのにpreferred_tag_id == tag_id" in all_reasons


def test_detect_missing_translations(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_missing_translations のテスト。
    - get_tag_languages() が ["en","ja"] を返す場合、
      タグごとの翻訳が部分的に欠けているケースをチェック。
    """
    # デフォルトで required_languages=None なら全言語対象
    mock_tag_repository.get_tag_languages.return_value = ["en", "ja"]

    # 存在するtag_id=[100,101]
    mock_tag_repository.get_all_tag_ids.return_value = [100, 101]

    mock_tag_100 = MagicMock(tag="tag_100")
    mock_tag_101 = MagicMock(tag="tag_101")

    def fake_get_tag_by_id(tid):
        if tid == 100:
            return mock_tag_100
        elif tid == 101:
            return mock_tag_101
        return None

    mock_tag_repository.get_tag_by_id.side_effect = fake_get_tag_by_id

    # タグ100は "en" しか翻訳が無い
    mock_trans_100_en = MagicMock(tag_id=100, language="en", translation="hello")
    # タグ101は "en", "ja" が全部ある
    mock_trans_101_en = MagicMock(tag_id=101, language="en", translation="foo")
    mock_trans_101_ja = MagicMock(tag_id=101, language="ja", translation="バー")

    def fake_get_translations(tid):
        if tid == 100:
            return [mock_trans_100_en]
        elif tid == 101:
            return [mock_trans_101_en, mock_trans_101_ja]
        return []

    mock_tag_repository.get_translations.side_effect = fake_get_translations

    # 実行
    missing = db_tool.detect_missing_translations()
    # タグ100 は "ja" が不足しているはず
    assert len(missing) == 1
    assert missing[0]["tag_id"] == 100
    assert missing[0]["missing_languages"] == ["ja"]
    # タグ101 は 全言語揃っているため不足なし


def test_detect_abnormal_usage_counts(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_abnormal_usage_counts のテスト。
    - 0未満 or max_threshold(デフォルト1000000)を超える場合を異常値とする。
    """
    mock_tag_repository.get_all_tag_ids.return_value = [5, 6]
    mock_tag_repository.get_tag_format_ids.return_value = [1, 2]
    mock_tag_repository.get_tag_formats.return_value = ["danbooru", "e621"]

    def fake_usage_count(tid, fid):
        # tid=5, fid=1 → -1 (異常: 負数)
        # tid=5, fid=2 → 100
        # tid=6, fid=1 → 999999999 (異常: 上限超)
        # tid=6, fid=2 → None
        if tid == 5 and fid == 1:
            return -1
        if tid == 5 and fid == 2:
            return 100
        if tid == 6 and fid == 1:
            return 999999999
        return None

    mock_tag_repository.get_usage_count.side_effect = fake_usage_count

    def fake_get_tag_by_id(tid):
        return MagicMock(tag=f"tag_{tid}")

    mock_tag_repository.get_tag_by_id.side_effect = fake_get_tag_by_id

    abnormal = db_tool.detect_abnormal_usage_counts(max_threshold=1000000)
    # 期待: tid=5, fid=1 と tid=6, fid=1 が異常
    assert len(abnormal) == 2
    # 具体的内容
    rec1 = abnormal[0]
    rec2 = abnormal[1]

    # rec1 → count=-1
    assert rec1["tag_id"] == 5
    assert rec1["count"] == -1
    assert "範囲外" in rec1["reason"]

    # rec2 → count=999999999
    assert rec2["tag_id"] == 6
    assert rec2["count"] == 999999999


def test_fix_inconsistent_alias_status(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    fix_inconsistent_alias_status のテスト。
    - (tag_id, format_id)を指定し、alias=Falseかつ preferred_tag_id != tag_idのケースを修正。
    """
    # ダミーのタグステータス
    mock_status = MagicMock(tag_id=10, format_id=1, alias=False, preferred_tag_id=15, type_id=None)

    mock_tag_repository.get_tag_status.return_value = mock_status

    # 実行
    db_tool.fix_inconsistent_alias_status((10, 1))

    # 呼ばれたかを検証
    mock_tag_repository.update_tag_status.assert_called_once_with(
        tag_id=10,
        format_id=1,
        alias=False,
        preferred_tag_id=10,  # fix で tag_idと一致させる
        type_id=None,
    )


def test_fix_duplicate_status(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    fix_duplicate_status のテスト。
    - 重複ステータスが複数存在する場合、最初の1つを残し、残りを削除する想定。
    """
    # 2つのstatus（重複） + 1つの他フォーマット status
    s1 = MagicMock(tag_id=5, format_id=1, updated_at="2023-01-01")
    s2 = MagicMock(tag_id=5, format_id=1, updated_at="2023-01-02")
    s_other = MagicMock(tag_id=5, format_id=2)
    mock_tag_repository.list_tag_statuses.return_value = [s1, s2, s_other]

    # 実行
    db_tool.fix_duplicate_status(5, 1)

    # s1とs2が同じformat_id=1 → s1残す, s2削除
    mock_tag_repository.delete_tag_status.assert_called_once_with(s2.tag_id, s2.format_id)
    # 他フォーマット s_other は影響なし


def test_detect_invalid_tag_id(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_invalid_tag_id のテスト。
    - "invalid tag" が見つからなければ "invalid_tag" を再検索する挙動を検証。
    """
    # 最初 "invalid tag" はNoneを返す → 2番目 "invalid_tag" は999を返す
    mock_tag_repository.get_tag_id_by_name.side_effect = [None, 999]

    result = db_tool.detect_invalid_tag_id()
    assert result == 999

    # モック呼び出しが確認できる
    assert mock_tag_repository.get_tag_id_by_name.call_count == 2
    mock_tag_repository.get_tag_id_by_name.assert_any_call("invalid tag")
    mock_tag_repository.get_tag_id_by_name.assert_any_call("invalid_tag")


def test_detect_invalid_preferred_tags(db_tool: DatabaseMaintenanceTool, mock_tag_repository: MagicMock):
    """
    detect_invalid_preferred_tags のテスト。
    - invalid_tag_idをpreferred_tag_idに持つレコードを検出。
    """
    # 全ステータス
    s1 = MagicMock(tag_id=10, format_id=1, alias=False, preferred_tag_id=999)  # invalid
    s2 = MagicMock(tag_id=11, format_id=1, alias=False, preferred_tag_id=12)
    s3 = MagicMock(tag_id=12, format_id=1, alias=True, preferred_tag_id=999)  # invalid
    mock_tag_repository.list_tag_statuses.return_value = [s1, s2, s3]

    # それぞれのタグ
    def fake_tag_by_id(tid):
        return MagicMock(tag=f"tag_{tid}")

    mock_tag_repository.get_tag_by_id.side_effect = fake_tag_by_id

    invalid_prefs = db_tool.detect_invalid_preferred_tags(999)
    # s1, s3 が invalid
    assert len(invalid_prefs) == 2
    # (tag_id=10, "tag_10"), (tag_id=12, "tag_12") が返るはず
    assert invalid_prefs[0] == (10, "tag_10")
    assert invalid_prefs[1] == (12, "tag_12")
