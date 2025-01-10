# genai_tag_db_tools.services.tag_search
import logging
from typing import Optional

import polars as pl

from genai_tag_db_tools.data.tag_repository import TagRepository
class TagSearcher:
    """タグ検索・変換等を行うビジネスロジッククラス"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # リポジトリはとりあえず自前でインスタンス化
        self.tag_repo = TagRepository()


    def search_tags(
        self,
        keyword: str,
        partial: bool = False,
        format_name: Optional[str] = None,
        type_name: Optional[str] = None,
        language: Optional[str] = None,
        min_usage: Optional[int] = None,
        max_usage: Optional[int] = None,
        alias: Optional[bool] = None,
    ) -> pl.DataFrame:
        """
        検索条件に合致するタグ情報を一括で取得し、PolarsのDataFrameで返す。

        Args:
            keyword (str):
                検索キーワード。Tagテーブル(tag, source_tag)やTagTranslation(translation)でマッチする。
                '*' を含む場合はワイルドカード検索とみなす。
            partial (bool, optional):
                TrueならLIKE検索、Falseなら完全一致検索。
                デフォルト: False (完全一致検索)
            format_name (Optional[str], optional):
                特定フォーマット名で絞り込む場合に指定 (例: "e621")。
                None や "All" のときは絞り込まない。
            type_name (Optional[str], optional):
                特定タイプ名で絞り込む場合に指定。None や "All" なら絞り込まない。
            language (Optional[str], optional):
                翻訳言語で絞り込む場合に指定 (例: "en")。None や "All" なら絞り込まない。
            min_usage (Optional[int], optional):
                使用回数の下限。Noneなら下限なし。
            max_usage (Optional[int], optional):
                使用回数の上限。Noneなら上限なし。
            alias (Optional[bool], optional):
                Trueなら alias=True のタグのみ、Falseなら alias=False のタグのみを検索。
                None の場合は絞り込まない。

        Returns:
            pl.DataFrame:
                検索結果を1行1タグとしてまとめたPolarsのDataFrame。
                以下のようなカラムを持つ例:
                - tag_id (int)
                - tag (str)
                - source_tag (str)
                - usage_count (int)
                - type_name (str)
                - alias (bool)
                - translations (dict[str, str])  # 言語 → 翻訳
                …など

        Raises:
            ValueError: 入力パラメータが不正などの理由で検索不能。
        """

        self.logger.info(
            f"[search_tags] keyword={keyword}, partial={partial}, "
            f"format={format_name}, type={type_name}, lang={language}, "
            f"usage=({min_usage}, {max_usage}), alias={alias}"
        )

        # 1) キーワード検索で対象タグIDを抽出
        tag_ids = set(self.tag_repo.search_tag_ids(keyword, partial=partial))
        if not tag_ids:
            self.logger.debug("キーワード条件でタグが見つかりませんでした.")
            return pl.DataFrame([])  # 空DataFrame

        # 2) フォーマット指定があるなら、そのフォーマットに紐づくタグIDとの交差をとる
        if format_name and format_name.lower() != "all":
            format_tag_ids = set(self.tag_repo.search_tag_ids_by_format_name(format_name))
            tag_ids = tag_ids & format_tag_ids
            if not tag_ids:
                self.logger.debug("フォーマットフィルター後にタグは残りません。")
                return pl.DataFrame([])

        # 3) 使用回数フィルタ (min_usage, max_usage)
        if min_usage is not None or max_usage is not None:
            # format_name から format_id を取得 (0 なら存在しないフォーマット)
            fid = 0
            if format_name and format_name.lower() != "all":
                fid = self.tag_repo.get_format_id(format_name)
                if not fid:
                    return pl.DataFrame([])

            usage_filtered_ids = set(self.tag_repo.search_tag_ids_by_usage_count_range(
                min_count=min_usage,
                max_count=max_usage,
                format_id=(fid if fid != 0 else None),
            ))
            tag_ids = tag_ids & usage_filtered_ids
            if not tag_ids:
                self.logger.debug("使用回数フィルター後にタグは残りません。")
                return pl.DataFrame([])

        # 4) タイプ名フィルタ
        if type_name and type_name.lower() != "all":
            # format_idも絡む場合は get_format_id(format_name) した結果を合わせる
            fid = None
            if format_name and format_name.lower() != "all":
                fid_temp = self.tag_repo.get_format_id(format_name)
                if fid_temp:
                    fid = fid_temp
            type_filtered_ids = set(self.tag_repo.search_tag_ids_by_type_name(type_name, format_id=fid))
            tag_ids = tag_ids & type_filtered_ids
            if not tag_ids:
                self.logger.debug("タイプフィルター後にタグは残りません。")
                return pl.DataFrame([])

        # 5) alias フィルタ
        if alias is not None:
            # True / False
            if format_name and format_name.lower() != "all":
                fid = self.tag_repo.get_format_id(format_name)
                if not fid:
                    return pl.DataFrame([])
            else:
                fid = None
            alias_ids = set(self.tag_repo.search_tag_ids_by_alias(alias=alias, format_id=fid))
            tag_ids = tag_ids & alias_ids
            if not tag_ids:
                self.logger.debug("エイリアスフィルター後にタグは残りません。")
                return pl.DataFrame([])

        # 6) language フィルタ
        #    "翻訳テーブルに language=xxx が存在するタグ" のみ残す
        if language and language.lower() != "all":
            lang_filtered_ids = []
            for t_id in tag_ids:
                translations = self.tag_repo.get_translations(t_id)  # list[TagTranslation]
                if any(tr.language == language for tr in translations):
                    lang_filtered_ids.append(t_id)
            tag_ids = set(lang_filtered_ids)
            if not tag_ids:
                self.logger.debug("言語フィルター後にタグは残りません。")
                return pl.DataFrame([])

        # 7) ここまでで tag_ids が最終絞り込み結果。これらの詳細をまとめて取得
        rows = self._collect_tag_info(tag_ids, format_name=format_name)
        # rows は list[dict]

        # 8) PolarsのDataFrame に変換して返す
        if not rows:
            return pl.DataFrame([])
        return pl.DataFrame(rows)

    def _collect_tag_info(self, tag_ids: set[int], format_name: Optional[str]) -> list[dict]:
        """
        絞り込み済みの tag_id 群について、TagRepository を使って情報を収集し、
        list[dict] にまとめる。呼び出し元で pl.DataFrame 変換する想定。

        Args:
            tag_ids (set[int]): 取得対象のタグID集合
            format_name (Optional[str]): フォーマット名 (None or "All"なら未指定)

        Returns:
            list[dict]:
              [
                {
                  "tag_id": 1,
                  "tag": "foo",
                  "source_tag": "foo_src",
                  "usage_count": 123,
                  "alias": False,
                  "type_name": "Character",
                  "translations": { "en": "EnglishWord", "ja": "日本語" },
                  ...
                },
                ...
              ]
        """
        rows = []
        # フォーマットIDを取得しておく (usage_countやalias, type取得に使う)
        format_id = 0
        if format_name and format_name.lower() != "all":
            format_id = self.tag_repo.get_format_id(format_name)

        for t_id in sorted(tag_ids):
            tag_obj = self.tag_repo.get_tag_by_id(t_id)
            if not tag_obj:
                continue

            # usage_count (フォーマット指定がある場合のみ取得)
            usage_count = 0
            if format_id:
                usage_count = self.tag_repo.get_usage_count(t_id, format_id) or 0

            # alias, type_nameなど (フォーマット指定があれば TagStatus を見る)
            is_alias = False
            resolved_type_name = ""
            if format_id:
                status_obj = self.tag_repo.get_tag_status(t_id, format_id)
                if status_obj:
                    is_alias = status_obj.alias
                    # type_id -> TagTypeFormatMapping -> TagTypeName
                    if status_obj.type_id is not None:
                        resolved_type_name = self.tag_repo.get_type_name_by_format_type_id(format_id, status_obj.type_id) or ""
                        pass

            # 翻訳一覧
            trans_dict = {}
            translations = self.tag_repo.get_translations(t_id)
            for tr in translations:
                trans_dict[tr.language] = tr.translation

            rows.append({
                "tag_id": t_id,
                "tag": tag_obj.tag,
                "source_tag": tag_obj.source_tag,
                "usage_count": usage_count,
                "alias": is_alias,
                "type_name": resolved_type_name,
                "translations": trans_dict,
            })

        return rows

    def convert_tag(self, search_tag: str, format_id: int) -> str:
        # HACK: cleanup_str.py に移動するべきかも
        """
        入力された `search_tag` を指定フォーマットの「推奨タグ」に変換して返す。
        - alias=True の場合などは preferred_tag を取得して置き換え。
        - DBになければそのまま返す。
        - 'invalid tag' はログに残して元タグを返す。

        Args:
            search_tag (str): 変換対象のタグ
            format_id (int): 対象のフォーマットID

        Returns:
            str: 変換後のタグ
        """
        tag_id = self.tag_repo.get_tag_id_by_name(search_tag, partial=False)
        if tag_id is None:
            return search_tag  # DBに無ければそのまま
        preferred_tag_id = self.tag_repo.find_preferred_tag(tag_id, format_id)
        if preferred_tag_id is None:
            return search_tag
        # ここまでで alias=True の場合は preferred_tag_id != tag_id

        preferred_tag_obj = self.tag_repo.get_tag_by_id(preferred_tag_id)
        if not preferred_tag_obj:
            return search_tag  # DB異常

        preferred_tag = preferred_tag_obj.tag
        if preferred_tag == "invalid tag":
            self.logger.warning(
                f"[convert_tag] '{search_tag}' → 優先タグが 'invalid tag' です。オリジナルタグを使用。"
            )
            return search_tag

        if search_tag != preferred_tag:
            self.logger.info(f"タグ '{search_tag}' は '{preferred_tag}' に変換されました")

        return preferred_tag

    def get_tag_types(self, format_name: str) -> list[str]:
        """
        指定フォーマットに紐づくタグタイプ名の一覧を取得する。

        Args:
            format_name (str): フォーマット名

        Returns:
            list[str]: タグタイプ名のリスト
        """
        format_id = self.tag_repo.get_format_id(format_name)
        if format_id is None:
            return []
        return self.tag_repo.get_tag_types(format_id)

    def get_all_types(self) -> list[str]:
        """
        登録されている全てのタグタイプ名の一覧を取得する。

        Returns:
            list[str]: タグタイプ名のリスト
        """
        return self.tag_repo.get_all_types()

    def get_tag_languages(self) -> list[str]:
        """
        DB上に登録されている言語の一覧を返す。

        Returns:
            list[str]: 言語コードのリスト
        """
        return self.tag_repo.get_tag_languages()

    def get_tag_formats(self) -> list[str]:
        """
        利用可能なタグフォーマットの一覧を取得する。

        Returns:
            list[str]: フォーマット名のリスト。
        """
        return self.tag_repo.get_tag_formats()

    def get_format_id(self, format_name: str) -> int:
        """
        フォーマット名からフォーマットIDを取得する。

        Args:
            format_name (str): フォーマット名

        Returns:
            int: フォーマットID
        """
        return self.tag_repo.get_format_id(format_name)

if __name__ == "__main__":
    word = "1boy"
    prompt = "1boy, 1girl, 2boys, 2girls, 3boys, 3girls, 4boys, 4girls, 5boys"
    format_name = "e621"

    tagsearcher = TagSearcher()

    # フォーマット名からIDを取得
    format_id = tagsearcher.tag_repo.get_format_id(format_name)
    # 単一タグを部分一致で変換してみる例
    # (複数ヒットした場合の挙動はリポジトリ側 or さらに上位で検討)
    converted_single = tagsearcher.convert_tag(word, format_id)
    print(f"[single] '{word}' → '{converted_single}'")

    # タグタイプ一覧を取得
    types = tagsearcher.get_tag_types("e621")
    print("e621 のタグタイプ:", types)

    # 言語一覧を取得
    langs = tagsearcher.get_tag_languages()
    print("登録されている言語:", langs)

    # フォーマット一覧を取得
    formats = tagsearcher.get_tag_formats()
