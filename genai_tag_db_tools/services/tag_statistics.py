# genai_tag_db_tools.services.tag_statistics

import polars as pl
from typing import Any, Optional
from typing import Callable
from sqlalchemy.orm import Session

from genai_tag_db_tools.data.tag_repository import TagRepository


class TagStatistics:
    """
    DBに登録されたタグ情報の統計を取得するクラス。

      1) 総タグ数
      2) エイリアスになっているタグ数 (alias=True)
      3) エイリアスではないタグ数 (alias=False)
      4) タグごとの使用回数集計 (format別)
      5) タイプ別のタグ数 (format別)
      6) タグが持つ翻訳の総数・言語別翻訳状況
    """

    def __init__(self, session: Optional[Session] = None):
        # セッションからセッションファクトリを作成
        if session is not None:
            session_factory = lambda: session
        else:
            session_factory = None

        self.repo = TagRepository(session_factory=session_factory)

    def get_general_stats(self) -> dict[str, Any]:
        """
        全体的なサマリを辞書形式で返す。
        1) 総タグ数
        2) alias=True のタグ総数
        3) alias=False のタグ総数

        Returns:
            dict[str, Any]: 例
                {
                    "total_tags": 1234,
                    "alias_tags": 100,
                    "non_alias_tags": 1134
                }
        """
        # 1) 総タグ数
        all_tag_ids = self.repo.get_all_tag_ids()
        total_tags = len(all_tag_ids)

        # 2) alias=True のタグ数
        #    注意: search_tag_ids_by_alias(alias=True) はフォーマット単位で取得するので
        #    ここでは「少なくともどれかのフォーマットでエイリアス扱いになっているタグ」
        #    を数えるため、全フォーマット対象(None)で検索後、setで重複を排除
        alias_ids_any_format = set(self.repo.search_tag_ids_by_alias(alias=True, format_id=None))
        alias_tags = len(alias_ids_any_format)

        # 3) alias=False のタグ数
        #    「少なくともどこかで alias=False」なのか、「全フォーマットで alias=False」なのか、
        #    仕様次第です。ここでは「全タグ - (alias=Trueのタグ)」として簡単に計算。
        non_alias_tags = total_tags - alias_tags

        return {
            "total_tags": total_tags,
            "alias_tags": alias_tags,
            "non_alias_tags": non_alias_tags,
        }

    def get_usage_stats(self) -> pl.DataFrame:
        """
        タグの使用回数を、フォーマットごとにまとめた Polars DataFrame を返す。

        例: カラム
            - tag_id
            - format_name
            - usage_count
        """
        all_tag_ids = self.repo.get_all_tag_ids()
        all_formats = self.repo.get_tag_formats()  # ["danbooru", "e621", ...] 等
        rows = []

        for fmt_name in all_formats:
            fmt_id = self.repo.get_format_id(fmt_name)
            for t_id in all_tag_ids:
                usage = self.repo.get_usage_count(t_id, fmt_id)
                if usage is not None:
                    rows.append({
                        "tag_id": t_id,
                        "format_name": fmt_name,
                        "usage_count": usage,
                    })
                else:
                    # usage_count レコードが無い場合は 0 として扱うなら以下のように:
                    rows.append({
                        "tag_id": t_id,
                        "format_name": fmt_name,
                        "usage_count": 0,
                    })

        if not rows:
            return pl.DataFrame([])

        return pl.DataFrame(rows)

    def get_type_distribution(self) -> pl.DataFrame:
        """
        タイプごと (format_id, type_name) のタグ数を集計して返す。

        カラム:
          - format_name
          - type_name
          - tag_count (そのフォーマット、そのタイプのタグ数)
        """
        # フォーマットと対応するID一覧
        fmt_list = self.repo.get_tag_formats()  # ["danbooru", "e621", ...]
        rows = []

        for fmt_name in fmt_list:
            fmt_id = self.repo.get_format_id(fmt_name)
            # このフォーマットに紐づく全 type_name を取得
            type_names = self.repo.get_tag_types(fmt_id)

            for t_name in type_names:
                # その type_name に属する tag_id リスト
                tag_ids = self.repo.search_tag_ids_by_type_name(t_name, format_id=fmt_id)
                rows.append({
                    "format_name": fmt_name,
                    "type_name": t_name,
                    "tag_count": len(tag_ids)
                })

        return pl.DataFrame(rows)

    def get_translation_stats(self) -> pl.DataFrame:
        """
        タグごとの翻訳状況をまとめて返す。

        カラム例:
          - tag_id
          - total_translations
          - languages (登録されている言語一覧)
        """
        all_tag_ids = self.repo.get_all_tag_ids()
        rows = []
        for t_id in all_tag_ids:
            translations = self.repo.get_translations(t_id)
            lang_set = {tr.language for tr in translations}
            rows.append({
                "tag_id": t_id,
                "total_translations": len(translations),
                "languages": list(lang_set)
            })
        return pl.DataFrame(rows)


def main():
    stats = TagStatistics()

    # 1) 全体サマリ
    general = stats.get_general_stats()
    print("総合統計")
    for k, v in general.items():
        print(f"  {k}: {v}")
    print()

    # 2) 使用回数 (formatごと)
    usage_df = stats.get_usage_stats()
    print("[利用統計データフレーム]")
    print(usage_df)
    print()

    # 3) タイプ分布 (formatごと)
    type_dist_df = stats.get_type_distribution()
    print("[型配布データフレーム]")
    print(type_dist_df)
    print()

    # 4) 翻訳統計
    trans_df = stats.get_translation_stats()
    print("[翻訳統計データフレーム]")
    print(trans_df)


if __name__ == "__main__":
    main()
