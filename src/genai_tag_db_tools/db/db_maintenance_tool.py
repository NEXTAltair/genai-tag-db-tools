from pathlib import Path
from typing import Any

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.db.runtime import init_engine, set_database_path


class DatabaseMaintenanceTool:
    """タグDBの保守チェックをまとめたユーティリティ。"""

    def __init__(self, db_path: str):
        """指定DBを対象にツールを初期化する。"""
        path = Path(db_path)
        set_database_path(path)
        init_engine(path)
        self.tag_repository = TagRepository()

    def detect_duplicates_in_tag_status(self) -> list[dict[str, Any]]:
        """TAG_STATUSの重複を検出して詳細を返す。"""
        all_statuses = self.tag_repository.list_tag_statuses()

        status_groups: dict[tuple[int, int], list] = {}
        for status in all_statuses:
            key = (status.tag_id, status.format_id)
            status_groups.setdefault(key, []).append(status)

        duplicates: list[dict[str, Any]] = []
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
            format_name = self.tag_repository.get_format_name(format_id)

            duplicates.append(
                {
                    "tag": tag.tag,
                    "format": format_name,
                    "type": None,
                    "alias": bool(status.alias),
                    "preferred_tag": preferred_tag.tag if preferred_tag else None,
                }
            )

        return duplicates

    def detect_usage_counts_for_tags(self) -> list[dict[str, Any]]:
        """TAG_USAGE_COUNTSの使用回数を取得して返す。"""
        tag_ids = self.tag_repository.get_all_tag_ids()
        format_ids = self.tag_repository.get_tag_format_ids()

        usage_counts: list[dict[str, Any]] = []
        for tag_id in tag_ids:
            tag = self.tag_repository.get_tag_by_id(tag_id)
            if not tag:
                continue

            for format_id in format_ids:
                count = self.tag_repository.get_usage_count(tag_id, format_id)
                if count:
                    format_name = self.tag_repository.get_format_name(format_id)
                    usage_counts.append(
                        {
                            "tag": tag.tag,
                            "format_name": format_name,
                            "use_count": count,
                        }
                    )

        return usage_counts

    def detect_foreign_key_issues(self) -> list[tuple[int, str | None]]:
        """外部キーの整合性をチェックする。"""
        all_statuses = self.tag_repository.list_tag_statuses()

        missing_tags = []
        for status in all_statuses:
            tag = self.tag_repository.get_tag_by_id(status.tag_id)
            if not tag:
                missing_tags.append((status.tag_id, None))
        return missing_tags

    def detect_orphan_records(self) -> dict[str, list[tuple[int]]]:
        """孤立レコードを検出する（簡易版）。"""
        all_tag_ids = set(self.tag_repository.get_all_tag_ids())
        orphans: dict[str, list[tuple[int]]] = {
            "translations": [],
            "status": [],
            "usage_counts": [],
        }

        for tag_id in all_tag_ids:
            translations = self.tag_repository.get_translations(tag_id)
            for trans in translations:
                if trans.tag_id not in all_tag_ids:
                    orphans["translations"].append((trans.tag_id,))

        all_statuses = self.tag_repository.list_tag_statuses()
        for status in all_statuses:
            if status.tag_id not in all_tag_ids:
                orphans["status"].append((status.tag_id,))

        return orphans

    def detect_inconsistent_alias_status(self) -> list[dict[str, Any]]:
        """エイリアス整合性が崩れているTagStatusを検出する。"""
        inconsistencies: list[dict[str, Any]] = []
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
        """翻訳の多言語カバレッジをチェックする。"""
        if required_languages is None:
            required_languages = set(self.tag_repository.get_tag_languages())

        missing_translations: list[dict[str, Any]] = []
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
        """使用回数が異常なタグを検出する。"""
        abnormal: list[dict[str, Any]] = []
        for tag_id in self.tag_repository.get_all_tag_ids():
            for format_id in self.tag_repository.get_tag_format_ids():
                count = self.tag_repository.get_usage_count(tag_id, format_id)
                if count is not None and (count < 0 or count > max_threshold):
                    tag = self.tag_repository.get_tag_by_id(tag_id)
                    format_name = self.tag_repository.get_format_name(format_id)
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
        """インデックスの最適化（未実装）。"""
        print("インデックス最適化: まだ未実装です。")

    def detect_invalid_tag_id(self) -> int | None:
        """invalid_tagのタグIDを取得する。"""
        invalid_tag_id = self.tag_repository.get_tag_id_by_name("invalid tag")
        if invalid_tag_id is None:
            invalid_tag_id = self.tag_repository.get_tag_id_by_name("invalid_tag")
        return invalid_tag_id

    def detect_invalid_preferred_tags(self, invalid_tag_id: int) -> list[tuple[int, str]]:
        """invalid tagをpreferred_tagに設定したレコードを検出する。"""
        invalid_preferred_tags: list[tuple[int, str]] = []
        all_statuses = self.tag_repository.list_tag_statuses()
        for status in all_statuses:
            if status.preferred_tag_id == invalid_tag_id:
                tag = self.tag_repository.get_tag_by_id(status.tag_id)
                if tag:
                    invalid_preferred_tags.append((status.tag_id, tag.tag))
        return invalid_preferred_tags

    # --- 自動修正 ---
    def fix_inconsistent_alias_status(self, status_id: tuple[int, int]) -> None:
        """エイリアス整合性の問題を修正する。"""
        tag_id, format_id = status_id
        status = self.tag_repository.get_tag_status(tag_id, format_id)
        if not status:
            return

        if not status.alias and status.preferred_tag_id != status.tag_id:
            self.tag_repository.update_tag_status(
                tag_id=tag_id,
                format_id=format_id,
                alias=False,
                preferred_tag_id=tag_id,
                type_id=status.type_id,
            )
        elif status.alias and status.preferred_tag_id == status.tag_id:
            print(f"Warning: tag_id={tag_id} のエイリアス設定は手動確認が必要です")

    def fix_duplicate_status(self, tag_id: int, format_id: int) -> None:
        """重複したタグステータスを修正する。"""
        statuses = self.tag_repository.list_tag_statuses(tag_id)
        format_statuses = [s for s in statuses if s.format_id == format_id]

        if len(format_statuses) <= 1:
            return

        for status in format_statuses[1:]:
            self.tag_repository.delete_tag_status(status.tag_id, status.format_id)
