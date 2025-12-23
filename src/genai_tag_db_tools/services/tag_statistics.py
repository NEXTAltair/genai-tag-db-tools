from typing import Any

import polars as pl
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.repository import TagRepository, get_default_repository


class TagStatistics:
    """タグDBの統計情報をまとめて取得する。"""

    def __init__(
        self,
        session: Session | None = None,
        repository: TagRepository | None = None,
    ):
        if repository is not None:
            self.repo = repository
            return
        if session is not None:

            def session_factory():
                return session

            self.repo = TagRepository(session_factory=session_factory)
            return
        self.repo = get_default_repository()

    def get_general_stats(self) -> dict[str, Any]:
        """全体サマリを返す。"""
        tags = self.repo.list_tags()
        total_tags = len(tags)
        statuses = self.repo.list_tag_statuses()
        alias_tag_ids = {status.tag_id for status in statuses if status.alias}
        alias_tags = len(alias_tag_ids)
        non_alias_tags = total_tags - alias_tags

        return {
            "total_tags": total_tags,
            "alias_tags": alias_tags,
            "non_alias_tags": non_alias_tags,
        }

    def get_usage_stats(self) -> pl.DataFrame:
        """使用回数をformat別に返す。"""
        usage_rows = self.repo.list_usage_counts()
        if not usage_rows:
            return pl.DataFrame([])

        format_map = self.repo.get_format_map()
        status_map = {(status.tag_id, status.format_id): status for status in self.repo.list_tag_statuses()}
        filtered_rows = []
        for usage in usage_rows:
            status = status_map.get((usage.tag_id, usage.format_id))
            if status is None:
                continue
            if status.alias or status.deprecated:
                continue
            format_name = format_map.get(usage.format_id, f"format:{usage.format_id}")
            filtered_rows.append(
                {
                    "tag_id": usage.tag_id,
                    "format_name": format_name,
                    "usage_count": usage.count,
                }
            )

        return pl.DataFrame(filtered_rows)

    def get_type_distribution(self) -> pl.DataFrame:
        """format別のtype分布を返す。"""
        format_map = self.repo.get_format_map()
        type_map = self.repo.get_type_mapping_map()
        counts: dict[tuple[str, str], int] = {}
        for status in self.repo.list_tag_statuses():
            if status.alias or status.deprecated:
                continue
            format_name = format_map.get(status.format_id, f"format:{status.format_id}")
            type_name = type_map.get((status.format_id, status.type_id), f"type:{status.type_id}")
            key = (format_name, type_name)
            counts[key] = counts.get(key, 0) + 1

        return pl.DataFrame(
            [
                {"format_name": format_name, "type_name": type_name, "tag_count": tag_count}
                for (format_name, type_name), tag_count in counts.items()
            ]
        )

    def get_translation_stats(self) -> pl.DataFrame:
        """タグごとの翻訳状況を返す。"""
        all_tag_ids = self.repo.get_all_tag_ids()
        rows = []
        for t_id in all_tag_ids:
            translations = self.repo.get_translations(t_id)
            lang_set = {tr.language for tr in translations}
            rows.append(
                {
                    "tag_id": t_id,
                    "total_translations": len(translations),
                    "languages": sorted(lang_set),
                }
            )
        return pl.DataFrame(rows)


if __name__ == "__main__":
    stats = TagStatistics()

    general = stats.get_general_stats()
    print("総合統計")
    for k, v in general.items():
        print(f"  {k}: {v}")
    print()

    usage_df = stats.get_usage_stats()
    print("[利用統計データフレーム]")
    print(usage_df)
    print()

    type_dist_df = stats.get_type_distribution()
    print("[型分布データフレーム]")
    print(type_dist_df)
    print()

    trans_df = stats.get_translation_stats()
    print("[翻訳統計データフレーム]")
    print(trans_df)
