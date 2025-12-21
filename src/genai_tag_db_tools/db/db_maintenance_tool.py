from typing import Any

from genai_tag_db_tools.db.repository import TagRepository


class DatabaseMaintenanceTool:
    """タグDBの保守チェックをまとめたユーティリティ。

    対象:
    - 重複レコード
    - 使用回数の異常値
    - 外部キー整合性
    - 孤立レコード
    - エイリアス整合性
    - 翻訳カバレッジ
    - invalid tag の検出

    すべて TagRepository 経由で実行し、DBへ直接アクセスしない。
    """

    def __init__(self, db_path: str):
        """Args:
            db_path (str): DBファイルのパス（将来拡張用）
        """
        self.tag_repository = TagRepository()

    def detect_duplicates_in_tag_status(self) -> list[dict[str, Any]]:
        """TAG_STATUSの重複を検出して詳細を返す。"""
        all_statuses = self.tag_repository.list_tag_statuses()

        # tag_idとformat_idの組み合わせでグループ化
        status_groups: dict[tuple[int, int], list] = {}
        for status in all_statuses:
            key = (status.tag_id, status.format_id)
            status_groups.setdefault(key, []).append(status)

        duplicates = []
        for (tag_id, format_id), statuses in status_groups.items():
            if len(statuses) <= 1:
                continue

            tag = self.tag_repository.get_tag_by_id(tag_id)
            if not tag:
                continue

            status = statuses[0]
            preferred_tag = (
                self.tag_repository.get_tag_by_id(status.preferred_tag_id)
                if status.preferred_tag_id
                else None
            )

            duplicates.append(
                {
                    "tag": tag.tag,
                    "format": self.tag_repository.get_tag_formats()[format_id - 1],
                    "type": None,  # type_id -> type_name は未実装
                    "alias": bool(status.alias),
                    "preferred_tag": preferred_tag.tag if preferred_tag else None,
                }
            )

        return duplicates

    def detect_usage_counts_for_tags(self) -> list[dict[str, Any]]:
        """TAG_USAGE_COUNTSの使用回数を取得して返す。"""
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
                    format_name = self.tag_repository.get_tag_formats()[format_id - 1]
                    usage_counts.append(
                        {
                            "tag": tag.tag,
                            "format_name": format_name,
                            "use_count": count,
                        }
                    )

        return usage_counts

    def detect_foreign_key_issues(self) -> list[tuple[int, str | None]]:
        """外部キーの整合性をチェック。"""
        all_statuses = self.tag_repository.list_tag_statuses()

        missing_tags = []
        for status in all_statuses:
            tag = self.tag_repository.get_tag_by_id(status.tag_id)
            if not tag:
                missing_tags.append((status.tag_id, None))  # source_tagは未取得

        return missing_tags

    def detect_orphan_records(self) -> dict[str, list[tuple[int]]]:
        """孤立レコードを検出する（拡張版）。

        対象:
        - TAG_TRANSLATIONS
        - TAG_STATUS
        - TAG_USAGE_COUNTS
        """
        all_tag_ids = set(self.tag_repository.get_all_tag_ids())
        orphans: dict[str, list[tuple[int]]] = {
            "translations": [],
            "status": [],
            "usage_counts": [],
        }

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

        # TAG_USAGE_COUNTSの孤立レコード（未実装）
        # Note: TagRepositoryに全件取得メソッドが必要
        return orphans

    def detect_inconsistent_alias_status(self) -> list[dict[str, Any]]:
        """エイリアス整合性が崩れているTagStatusを検出。"""
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
        """翻訳の多言語カバレッジをチェックする。

        Args:
            required_languages: 対象言語。未指定なら登録済み全言語。
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
                    {
                        "tag_id": tag_id,
                        "tag": tag.tag,
                        "missing_languages": list(missing_languages),
                    }
                )

        return missing_translations

    def detect_abnormal_usage_counts(self, max_threshold: int = 1_000_000) -> list[dict[str, Any]]:
        """使用回数が異常（負数/閾値超過）のタグを検出。"""
        abnormal = []
        for tag_id in self.tag_repository.get_all_tag_ids():
            for format_id in self.tag_repository.get_tag_format_ids():
                count = self.tag_repository.get_usage_count(tag_id, format_id)
                if count is not None and (count < 0 or count > max_threshold):
                    tag = self.tag_repository.get_tag_by_id(tag_id)
                    format_name = self.tag_repository.get_tag_formats()[format_id - 1]
                    abnormal.append(
                        {
                            "tag_id": tag_id,
                            "tag": tag.tag if tag else None,
                            "format_id": format_id,
                            "format_name": format_name,
                            "count": count,
                            "reason": f"使用回数が範囲外 (0~{max_threshold})",
                        }
                    )
        return abnormal

    def optimize_indexes(self) -> None:
        """インデックスの最適化（将来実装）。"""
        print("インデックス最適化はSQLiteの低レベル操作が必要です。")

    def detect_invalid_tag_id(self) -> int | None:
        """invalid_tagのタグIDを取得。"""
        invalid_tag_id = self.tag_repository.get_tag_id_by_name("invalid tag")
        if invalid_tag_id is None:
            invalid_tag_id = self.tag_repository.get_tag_id_by_name("invalid_tag")
        return invalid_tag_id

    def detect_invalid_preferred_tags(self, invalid_tag_id: int) -> list[tuple[int, str]]:
        """invalid tagをpreferred_tagに設定したレコードを検出。"""
        invalid_preferred_tags = []
        all_statuses = self.tag_repository.list_tag_statuses()
        for status in all_statuses:
            if status.preferred_tag_id == invalid_tag_id:
                tag = self.tag_repository.get_tag_by_id(status.tag_id)
                if tag:
                    invalid_preferred_tags.append((status.tag_id, tag.tag))
        return invalid_preferred_tags

    # --- 自動修正 ---
    def fix_inconsistent_alias_status(self, status_id: tuple[int, int]) -> None:
        """エイリアス整合性の問題を修正。"""
        tag_id, format_id = status_id
        status = self.tag_repository.get_tag_status(tag_id, format_id)
        if not status:
            return

        if not status.alias and status.preferred_tag_id != status.tag_id:
            # alias=Falseの場合、preferred_tag_idをtag_idに合わせる
            self.tag_repository.update_tag_status(
                tag_id=tag_id,
                format_id=format_id,
                alias=False,
                preferred_tag_id=tag_id,
                type_id=status.type_id,
            )
        elif status.alias and status.preferred_tag_id == status.tag_id:
            # alias=Trueの場合、preferred_tag_idを別タグにする必要がある
            # Note: 自動修正せず手動対応を推奨
            print(f"Warning: tag_id={tag_id}のエイリアス設定は手動確認が必要です")

    def fix_duplicate_status(self, tag_id: int, format_id: int) -> None:
        """重複したタグステータスを修正。

        最も新しいステータスを残して他を削除。
        """
        statuses = self.tag_repository.list_tag_statuses(tag_id)
        format_statuses = [s for s in statuses if s.format_id == format_id]

        if len(format_statuses) <= 1:
            return

        # 最新のステータスを残して他を削除（暫定的に先頭を残す）
        for status in format_statuses[1:]:
            self.tag_repository.delete_tag_status(status.tag_id, status.format_id)


if __name__ == "__main__":
    db_tool = DatabaseMaintenanceTool("tags_v3.db")

    # 重複レコードの検出
    duplicates_status = db_tool.detect_duplicates_in_tag_status()
    if duplicates_status:
        print(f"重複レコードが検出されました: {duplicates_status}")
        for duplicate in duplicates_status:
            print(f"重複コード: {duplicate}")

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
    required_langs = {"en", "ja"}
    missing_translations = db_tool.detect_missing_translations(required_langs)
    if missing_translations:
        print(f"翻訳が不足しているタグが検出されました: {missing_translations}")
        for missing in missing_translations:
            print(f"翻訳不足: {missing}")

    # 外部キーの不整合検出
    missing_keys = db_tool.detect_foreign_key_issues()
    if missing_keys:
        print(f"外部キーの不整合が検出されました: {missing_keys}")

    # 孤立レコードの検出
    orphan_records = db_tool.detect_orphan_records()
    if any(orphan_records.values()):
        print(f"孤立レコードが検出されました: {orphan_records}")

    # invalid tag の検出
    invalid_tag = db_tool.detect_invalid_tag_id()
    if invalid_tag:
        invalid_preferred_tags = db_tool.detect_invalid_preferred_tags(invalid_tag)
        print(
            "invalid tagをpreferred_tagに設定したレコード:"
            f" {invalid_preferred_tags}"
        )
