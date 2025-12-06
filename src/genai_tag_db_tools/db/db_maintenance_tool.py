from typing import Any

from genai_tag_db_tools.data.tag_repository import TagRepository


class DatabaseMaintenanceTool:
    """データベースのメンテナンス機能を提供するクラス

    TAGSテーブルとその関連テーブルに対する以下の機能を提供:
    - 重複レコードの検出と修正
    - 使用回数の集計と異常値検出
    - 外部キー整合性チェック
    - 孤立レコードの検出
    - エイリアス整合性チェック
    - 翻訳カバレッジチェック
    - インデックスの最適化
    - invalid tagの検出

    全ての機能はTagRepositoryを利用して実装されており、DBへの直接アクセスは行いません。
    """

    def __init__(self, db_path: str):
        """
        Args:
            db_path (str): データベースファイルのパス
        """
        self.tag_repository = TagRepository()

    def detect_duplicates_in_tag_status(self) -> list[dict[str, Any]]:
        """TAG_STATUSテーブルの重複レコードを検出し、詳細情報を返す

        Returns:
            List[Dict[str, Any]]: 重複レコードのリスト（関連するタグ、フォーマット、タイプ、およびpreferred_tag情報を含む）
        """
        # 全てのタグステータスを取得
        all_statuses = self.tag_repository.list_tag_statuses()

        # tag_idとformat_idの組み合わせでグループ化
        status_groups: dict[tuple, list] = {}
        for status in all_statuses:
            key = (status.tag_id, status.format_id)
            if key not in status_groups:
                status_groups[key] = []
            status_groups[key].append(status)

        # 重複があるものだけを抽出
        duplicates = []
        for (tag_id, format_id), statuses in status_groups.items():
            if len(statuses) > 1:
                tag = self.tag_repository.get_tag_by_id(tag_id)
                if not tag:
                    continue

                status = statuses[0]  # 最初のステータスを使用
                preferred_tag = (
                    self.tag_repository.get_tag_by_id(status.preferred_tag_id)
                    if status.preferred_tag_id
                    else None
                )

                duplicates.append(
                    {
                        "tag": tag.tag,
                        "format": self.tag_repository.get_tag_formats()[
                            format_id - 1
                        ],  # format_idは1から始まる
                        "type": None,  # type_idからtype_nameへの変換は現在未実装
                        "alias": bool(status.alias),
                        "preferred_tag": preferred_tag.tag if preferred_tag else None,
                    }
                )

        return duplicates

    def detect_usage_counts_for_tags(self) -> list[dict[str, Any]]:
        """TAG_USAGE_COUNTSの使用回数を検出し、各タグの使用頻度を返す

        Returns:
            List[Dict[str, Any]]: タグとその使用回数のリスト
        """
        tag_ids = self.tag_repository.get_all_tag_ids()
        format_ids = self.tag_repository.get_tag_format_ids()

        usage_counts = []
        for tag_id in tag_ids:
            tag = self.tag_repository.get_tag_by_id(tag_id)
            if not tag:
                continue

            for format_id in format_ids:
                count = self.tag_repository.get_usage_count(tag_id, format_id)
                if count:
                    format_name = self.tag_repository.get_tag_formats()[
                        format_id - 1
                    ]  # format_idは1から始まる
                    usage_counts.append({"tag": tag.tag, "format_name": format_name, "use_count": count})

        return usage_counts

    def detect_foreign_key_issues(self) -> list[tuple]:
        """外部キーの整合性をチェック

        Returns:
            List[tuple]: 外部キー制約違反のレコードリスト
        """
        # TAG_STATUSテーブルの全レコードを取得
        all_statuses = self.tag_repository.list_tag_statuses()

        # 外部キー違反を検出
        missing_tags = []
        for status in all_statuses:
            tag = self.tag_repository.get_tag_by_id(status.tag_id)
            if not tag:
                missing_tags.append((status.tag_id, None))  # source_tagは取得できないのでNone

        return missing_tags

    def detect_orphan_records(self) -> dict[str, list[tuple]]:
        """孤立したレコードを検出（拡張版）

        以下のテーブルの孤立レコードを検出:
        - TAG_TRANSLATIONS
        - TAG_STATUS
        - TAG_USAGE_COUNTS

        Returns:
            Dict[str, List[tuple]]: テーブル名をキーとした孤立レコードのリスト
        """
        all_tag_ids = set(self.tag_repository.get_all_tag_ids())
        orphans = {"translations": [], "status": [], "usage_counts": []}

        # TAG_TRANSLATIONSの孤立レコード
        for tag_id in all_tag_ids:
            translations = self.tag_repository.get_translations(tag_id)
            for trans in translations:
                if trans.tag_id not in all_tag_ids:
                    orphans["translations"].append((trans.tag_id,))

        # TAG_STATUSの孤立レコード
        all_statuses = self.tag_repository.list_tag_statuses()
        for status in all_statuses:
            if status.tag_id not in all_tag_ids:
                orphans["status"].append((status.tag_id,))

        # TAG_USAGE_COUNTSの孤立レコード（実装予定）
        # Note: TagRepositoryにget_all_usage_countsのような機能が必要

        return orphans

    def detect_inconsistent_alias_status(self) -> list[dict[str, Any]]:
        """エイリアス整合性が崩れているTagStatusを検出

        以下のケースを検出:
        1. alias=Falseなのにpreferred_tag_id != tag_id
        2. alias=Trueなのにpreferred_tag_id == tag_id

        Returns:
            List[Dict[str, Any]]: 整合性が崩れているレコードのリスト
        """
        inconsistencies = []
        all_statuses = self.tag_repository.list_tag_statuses()

        for status in all_statuses:
            if not status.alias and status.preferred_tag_id != status.tag_id:
                inconsistencies.append(
                    {
                        "tag_id": status.tag_id,
                        "format_id": status.format_id,
                        "alias": status.alias,
                        "preferred_tag_id": status.preferred_tag_id,
                        "reason": "alias=Falseなのにpreferred_tag_id != tag_id",
                    }
                )
            if status.alias and status.preferred_tag_id == status.tag_id:
                inconsistencies.append(
                    {
                        "tag_id": status.tag_id,
                        "format_id": status.format_id,
                        "alias": status.alias,
                        "preferred_tag_id": status.preferred_tag_id,
                        "reason": "alias=Trueなのにpreferred_tag_id == tag_id",
                    }
                )

        return inconsistencies

    def detect_missing_translations(
        self, required_languages: set[str] | None = None
    ) -> list[dict[str, Any]]:
        """タグ翻訳の多言語カバレッジをチェック

        Args:
            required_languages (Optional[Set[str]]): 必須言語のセット。
                指定がない場合は登録済みの全言語を対象とする。

        Returns:
            List[Dict[str, Any]]: 翻訳が不足しているタグのリスト
        """
        if required_languages is None:
            required_languages = set(self.tag_repository.get_tag_languages())

        missing_translations = []
        for tag_id in self.tag_repository.get_all_tag_ids():
            tag = self.tag_repository.get_tag_by_id(tag_id)
            if not tag:
                continue

            translations = self.tag_repository.get_translations(tag_id)
            existing_languages = {t.language for t in translations}
            missing_languages = required_languages - existing_languages

            if missing_languages:
                missing_translations.append(
                    {"tag_id": tag_id, "tag": tag.tag, "missing_languages": list(missing_languages)}
                )

        return missing_translations

    def detect_abnormal_usage_counts(self, max_threshold: int = 1000000) -> list[dict[str, Any]]:
        """使用回数が異常に大きい or 負数のタグを検出

        Args:
            max_threshold (int): 使用回数の上限閾値

        Returns:
            List[Dict[str, Any]]: 異常な使用回数を持つタグのリスト
        """
        abnormal = []
        for tag_id in self.tag_repository.get_all_tag_ids():
            for format_id in self.tag_repository.get_tag_format_ids():
                count = self.tag_repository.get_usage_count(tag_id, format_id)
                if count is not None:
                    if count < 0 or count > max_threshold:
                        tag = self.tag_repository.get_tag_by_id(tag_id)
                        format_name = self.tag_repository.get_tag_formats()[format_id - 1]
                        abnormal.append(
                            {
                                "tag_id": tag_id,
                                "tag": tag.tag if tag else None,
                                "format_id": format_id,
                                "format_name": format_name,
                                "count": count,
                                "reason": f"使用回数が範囲外です (0~{max_threshold})",
                            }
                        )
        return abnormal

    def optimize_indexes(self) -> None:
        """インデックスの再構築や最適化を行う

        Note:
            SQLite固有の低レベル操作のため、現状は警告メッセージのみ表示。
            将来的にはTagRepository側でVACUUM/ANALYZE/REINDEXをサポートする可能性あり。
        """
        print("インデックスの最適化はSQLiteの低レベル操作のため、直接実行する必要があります")

    def detect_invalid_tag_id(self) -> int | None:
        """invalid_tagのタグIDを取得

        Returns:
            Optional[int]: invalid_tagのタグID
        """
        invalid_tag_id = self.tag_repository.get_tag_id_by_name("invalid tag")
        if invalid_tag_id is None:
            invalid_tag_id = self.tag_repository.get_tag_id_by_name("invalid_tag")

        return invalid_tag_id

    def detect_invalid_preferred_tags(self, invalid_tag_id: int) -> list[tuple]:
        """invalid tagのタグIDをpreferred_tagに記録したレコードを検出

        Args:
            invalid_tag_id (int): invalid tagのタグID

        Returns:
            List[tuple[int, str]]: invalid tagをpreferred_tagに設定しているレコードのリスト
        """
        invalid_preferred_tags = []

        # 全てのタグステータスをチェック
        all_statuses = self.tag_repository.list_tag_statuses()
        for status in all_statuses:
            if status.preferred_tag_id == invalid_tag_id:
                tag = self.tag_repository.get_tag_by_id(status.tag_id)
                if tag:
                    invalid_preferred_tags.append((status.tag_id, tag.tag))

        return invalid_preferred_tags

    # --- 自動修正機能 ---

    def fix_inconsistent_alias_status(self, status_id: tuple) -> None:
        """エイリアス整合性の問題を修正

        Args:
            status_id (tuple): (tag_id, format_id) のタプル
        """
        tag_id, format_id = status_id
        status = self.tag_repository.get_tag_status(tag_id, format_id)
        if not status:
            return

        if not status.alias and status.preferred_tag_id != status.tag_id:
            # alias=Falseの場合、preferred_tag_idをtag_idに設定
            self.tag_repository.update_tag_status(
                tag_id=tag_id,
                format_id=format_id,
                alias=False,
                preferred_tag_id=tag_id,
                type_id=status.type_id,
            )
        elif status.alias and status.preferred_tag_id == status.tag_id:
            # alias=Trueの場合、preferred_tag_idを別のタグに設定する必要がある
            # Note: この場合は自動修正せず、手動での対応を推奨
            print(f"Warning: tag_id={tag_id}のエイリアス設定には手動での確認が必要です")

    def fix_duplicate_status(self, tag_id: int, format_id: int) -> None:
        """重複したタグステータスを修正

        最も新しいステータスを残し、他を削除

        Args:
            tag_id (int): タグID
            format_id (int): フォーマットID
        """
        statuses = self.tag_repository.list_tag_statuses(tag_id)
        format_statuses = [s for s in statuses if s.format_id == format_id]

        if len(format_statuses) <= 1:
            return

        # 最新のステータスを残して他を削除
        format_statuses[0]  # 本来はタイムスタンプなどで判断
        for status in format_statuses[1:]:
            self.tag_repository.delete_tag_status(status.tag_id, status.format_id)


# 使用例
if __name__ == "__main__":
    db_tool = DatabaseMaintenanceTool("tags_v3.db")

    # 重複レコードの検出
    duplicates_status = db_tool.detect_duplicates_in_tag_status()
    if duplicates_status:
        print(f"重複レコードが検出されました: {duplicates_status}")
        for duplicate in duplicates_status:
            print(f"重複レコード: {duplicate}")

    # 使用回数の異常値検出
    abnormal_counts = db_tool.detect_abnormal_usage_counts()
    if abnormal_counts:
        print(f"異常な使用回数が検出されました: {abnormal_counts}")
        for count in abnormal_counts:
            print(f"異常値: {count}")

    # エイリアス整合性チェック
    inconsistent_aliases = db_tool.detect_inconsistent_alias_status()
    if inconsistent_aliases:
        print(f"エイリアス整合性の問題が検出されました: {inconsistent_aliases}")
        for alias in inconsistent_aliases:
            print(f"整合性エラー: {alias}")

    # 翻訳カバレッジチェック
    required_langs = {"en", "ja"}  # 必須言語を指定
    missing_translations = db_tool.detect_missing_translations(required_langs)
    if missing_translations:
        print(f"翻訳が不足しているタグが検出されました: {missing_translations}")
        for missing in missing_translations:
            print(f"翻訳不足: {missing}")

    # 外部キーの不整合の検出
    missing_keys = db_tool.detect_foreign_key_issues()
    if missing_keys:
        print(f"外部キーの不整合が検出されました: {missing_keys}")

    # 孤立レコードの検出
    orphan_records = db_tool.detect_orphan_records()
    if any(orphan_records.values()):
        print(f"孤立レコードが検出されました: {orphan_records}")

    # invalid tag の検出
    invalid_tag = db_tool.detect_invalid_tag_id()

    # invalid tag をpreferred_tagに設定しているレコードの検出
    if invalid_tag:
        invalid_preferred_tags = db_tool.detect_invalid_preferred_tags(invalid_tag)
        print(f"invalid tagをpreferred_tagに設定しているレコード: {invalid_preferred_tags}")
