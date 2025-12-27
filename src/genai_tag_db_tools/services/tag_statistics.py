import polars as pl
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, get_default_reader
from genai_tag_db_tools.models import GeneralStatsResult


class TagStatistics:
    """タグDBの統計情報をまとめて取得する"""

    def __init__(
        self,
        session: Session | None = None,
        reader: MergedTagReader | TagReader | None = None,
    ):
        if reader is not None:
            self.reader = reader
            return
        if session is not None:

            def session_factory():
                return session

            self.reader = TagReader(session_factory=session_factory)
            return
        self.reader = get_default_reader()

    def get_general_stats(self) -> GeneralStatsResult:
        """全体サマリを返す"""
        tags = self.reader.list_tags()
        total_tags = len(tags)
        statuses = self.reader.list_tag_statuses()
        alias_tag_ids = {status.tag_id for status in statuses if status.alias}
        alias_tags = len(alias_tag_ids)
        non_alias_tags = total_tags - alias_tags
        format_counts = self.get_format_counts()

        return GeneralStatsResult(
            total_tags=total_tags,
            alias_tags=alias_tags,
            non_alias_tags=non_alias_tags,
            format_counts=format_counts,
        )

    def get_usage_stats(self) -> pl.DataFrame:
        """使用回数をformat 別に返す"""
        usage_rows = self.reader.list_usage_counts()
        if not usage_rows:
            return pl.DataFrame([])

        format_map = self.reader.get_format_map()
        status_map = {
            (status.tag_id, status.format_id): status for status in self.reader.list_tag_statuses()
        }
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
        """format 別のtype 別の使用回数を返す"""
        format_map = self.reader.get_format_map()
        type_map = self.reader.get_type_mapping_map()
        counts: dict[tuple[str, str], int] = {}
        for status in self.reader.list_tag_statuses():
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

    def get_format_counts(self) -> dict[str, int]:
        """format 別の使用回数を返す"""
        format_map = self.reader.get_format_map()
        counts: dict[str, int] = {}
        for status in self.reader.list_tag_statuses():
            if status.alias or status.deprecated:
                continue
            format_name = format_map.get(status.format_id, f"format:{status.format_id}")
            counts[format_name] = counts.get(format_name, 0) + 1
        return counts

    def get_translation_stats(self) -> pl.DataFrame:
        """タグごとの翻訳状況を返す"""
        from collections import defaultdict

        from genai_tag_db_tools.db.schema import TagTranslation

        all_translations = self.reader.list_translations()

        by_tag: dict[int, list[TagTranslation]] = defaultdict(list)
        for tr in all_translations:
            by_tag[tr.tag_id].append(tr)

        rows = []
        for t_id, translations in by_tag.items():
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
    print("[型別分布データフレーム]")
    print(type_dist_df)
    print()

    trans_df = stats.get_translation_stats()
    print("[翻訳統計データフレーム]")
    print(trans_df)
