from typing import Any

import polars as pl
from sqlalchemy import func
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.repository import TagRepository
from genai_tag_db_tools.db.schema import (
    Tag,
    TagFormat,
    TagStatus,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
)


class TagStatistics:
    """タグDBの統計情報をまとめて取得する。"""

    def __init__(self, session: Session | None = None):
        if session is not None:

            def session_factory():
                return session
        else:
            session_factory = None

        self.repo = TagRepository(session_factory=session_factory)

    def get_general_stats(self) -> dict[str, Any]:
        """全体サマリを返す。"""
        with self.repo.session_factory() as session:
            total_tags = session.query(Tag.tag_id).count()
            alias_tags = (
                session.query(TagStatus.tag_id)
                .filter(TagStatus.alias == True)  # noqa: E712
                .distinct()
                .count()
            )
            non_alias_tags = total_tags - alias_tags

        return {
            "total_tags": total_tags,
            "alias_tags": alias_tags,
            "non_alias_tags": non_alias_tags,
        }

    def get_usage_stats(self) -> pl.DataFrame:
        """使用回数をformat別に返す。"""
        with self.repo.session_factory() as session:
            rows = (
                session.query(TagUsageCounts.tag_id, TagFormat.format_name, TagUsageCounts.count)
                .join(TagFormat, TagUsageCounts.format_id == TagFormat.format_id)
                .join(
                    TagStatus,
                    (TagUsageCounts.tag_id == TagStatus.tag_id)
                    & (TagUsageCounts.format_id == TagStatus.format_id),
                )
                .filter(TagStatus.alias == False, TagStatus.deprecated == False)  # noqa: E712
                .all()
            )

        if not rows:
            return pl.DataFrame([])

        return pl.DataFrame(
            [
                {
                    "tag_id": tag_id,
                    "format_name": format_name,
                    "usage_count": count,
                }
                for tag_id, format_name, count in rows
            ]
        )

    def get_type_distribution(self) -> pl.DataFrame:
        """format別のtype分布を返す。"""
        with self.repo.session_factory() as session:
            rows = (
                session.query(
                    TagFormat.format_name,
                    TagTypeName.type_name,
                    func.count(TagStatus.tag_id).label("tag_count"),
                )
                .select_from(TagStatus)
                .join(TagFormat, TagStatus.format_id == TagFormat.format_id)
                .join(
                    TagTypeFormatMapping,
                    (TagStatus.format_id == TagTypeFormatMapping.format_id)
                    & (TagStatus.type_id == TagTypeFormatMapping.type_id),
                )
                .join(TagTypeName, TagTypeFormatMapping.type_name_id == TagTypeName.type_name_id)
                .filter(TagStatus.alias == False, TagStatus.deprecated == False)  # noqa: E712
                .group_by(TagFormat.format_name, TagTypeName.type_name)
                .all()
            )

        return pl.DataFrame(
            [
                {"format_name": format_name, "type_name": type_name, "tag_count": tag_count}
                for format_name, type_name, tag_count in rows
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
                {"tag_id": t_id, "total_translations": len(translations), "languages": list(lang_set)}
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
