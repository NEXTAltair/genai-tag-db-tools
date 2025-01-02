import logging
import traceback
from typing import Optional
import sqlite3
from pathlib import Path
import polars as pl

from genai_tag_db_tools.config import db_path
from genai_tag_db_tools.services.processor import CSVToDatabaseProcessor


class TagSearcher:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)

    # def execute_query(self, query: str) -> pl.DataFrame:
    #     """SQLクエリを実行し、結果をDataFrameとして返します。

    #     Args:
    #         query (str): SQLクエリ。
    #         params (tuple, optional): クエリのパラメータ。デフォルトは None。

    #     Returns:
    #         polars.DataFrame: クエリの実行結果。
    #     """
    #     return pl.read_database(query, self.conn)

    # def execute_insert(self, query: str, params: tuple = None):
    #     """
    #     SQL INSERT クエリを実行します。

    #     Args:
    #         query (str): SQL INSERT クエリ。
    #         params (tuple, optional): クエリのパラメータ。デフォルトは None。
    #     """
    #     with self.conn:  # トランザクションを使用
    #         cursor = self.conn.cursor()
    #         cursor.execute(query, params)

    # def find_tag_id(self, keyword: str) -> Optional[int]:
    #     """TAGSテーブルからタグを完全一致で検索

    #     Args:
    #         keyword (str): 検索キーワード
    #     Returns:
    #         tag_id (Optional[int]): タグID
    #     Raises:
    #         ValueError: 複数または0件のタグが見つかった場合
    #     """
    #     query = "SELECT tag_id FROM TAGS WHERE tag = ?"
    #     df = self.execute_query(query, keyword)

    #     if df.empty:
    #         return None
    #     elif len(df) > 1:
    #         print(f"タグ '{keyword}' に対して複数のIDが見つかりました。\n {df}")
    #     else:
    #         return int(df["tag_id"].iloc[0])  # 最初の要素の値を取得

    # def search_tags(self, keyword, match_mode="partial", format_name="All"):
    #     """
    #     全てのタグ情報を結合して検索する

    #     Parameters:
    #         keyword (str): 検索キーワード
    #         match_mode (str, optional): キーワードのマッチングモード。'partial'（部分一致）または 'exact'（完全一致）。デフォルトは 'partial'。
    #         format_name (str, optional): タグのフォーマット。'All'（すべてのフォーマット）または特定のフォーマット名。デフォルトは 'All'。

    #     Returns:
    #         polars.DataFrame: 検索結果のタグデータを含むデータフレーム
    #     """
    #     base_query = """
    #     SELECT
    #         T.tag_id,
    #         T.tag,
    #         T.source_tag,
    #         TT.language,
    #         TT.translation,
    #         TS.alias,
    #         PT.tag AS preferred_tag,
    #         TF.format_name,
    #         TUC.count AS usage_count,
    #         TTN.type_name
    #     FROM TAGS AS T
    #     LEFT JOIN TAG_TRANSLATIONS AS TT ON T.tag_id = TT.tag_id
    #     LEFT JOIN TAG_STATUS AS TS ON T.tag_id = TS.tag_id
    #     LEFT JOIN TAG_FORMATS AS TF ON TS.format_id = TF.format_id
    #     LEFT JOIN TAG_USAGE_COUNTS AS TUC ON T.tag_id = TUC.tag_id AND TS.format_id = TUC.format_id
    #     LEFT JOIN TAGS AS PT ON TS.preferred_tag_id = PT.tag_id
    #     LEFT JOIN TAG_TYPE_FORMAT_MAPPING AS TTFM ON TS.format_id = TTFM.format_id AND TS.type_id = TTFM.type_id
    #     LEFT JOIN TAG_TYPE_NAME AS TTN ON TTFM.type_name_id = TTN.type_name_id
    #     WHERE (T.tag {match_operator} ? OR TT.translation {match_operator} ?)
    #     """.replace("{match_operator}", "=" if match_mode == "exact" else "LIKE")

    #     params = (
    #         (keyword, keyword)
    #         if match_mode == "exact"
    #         else (f"%{keyword}%", f"%{keyword}%")
    #     )

    #     if format_name != "All":
    #         base_query += " AND TF.format_name = ?"
    #         params += (format_name,)

    #     df = self.execute_query(base_query, params=params)

    #     # usage_count NaN値を0に設定
    #     df["usage_count"] = df["usage_count"].fillna(0).astype(int)

    #     # 列の順序を整理
    #     column_order = [
    #         "tag_id",
    #         "tag",
    #         "source_tag",
    #         "language",
    #         "translation",
    #         "alias",
    #         "preferred_tag",
    #         "format_name",
    #         "usage_count",
    #         "type_name",
    #     ]
    #     df = df[column_order]

    #     return df

    # def get_tag_status(self, tag_id: int, format_id: int) -> Optional[dict]:
    #     query = """
    #     SELECT ts.*, t.tag, t.source_tag
    #     FROM TAG_STATUS ts
    #     JOIN TAGS t ON ts.tag_id = t.tag_id
    #     WHERE ts.tag_id = ? AND ts.format_id = ?
    #     """
    #     df = pl.read_sql_query(query, self.conn, params=(tag_id, format_id))
    #     return df.to_dict("records")[0] if not df.empty else None

    # def update_tag_status(
    #     self,
    #     tag_id: int,
    #     format_id: int,
    #     type_id: int,
    #     alias: bool,
    #     preferred_tag_id: Optional[int],
    # ) -> int:
    #     """
    #     タグの状態を更新または新規作成します。

    #     Args:
    #         tag_id (int):
    #         formt_id (int);
    #         type_id (int):
    #         alias (bool):
    #         preferred_tag_id (Optional[int]):

    #     Returns:
    #         int: 更新または作成されたタグのID
    #     """

    #     if alias and preferred_tag_id is None:  # TODO :後で考える
    #         raise ValueError("エイリアスタグには推奨タグの指定が必要です。")
    #     elif not alias:
    #         preferred_tag_id = tag_id

    #     # タグステータスの更新または挿入用のDataFrameを作成
    #     status_data = pl.DataFrame(
    #         {
    #             "tag_id": [tag_id],
    #             "format_id": [format_id],
    #             "type_id": [type_id],
    #             "alias": [int(alias)],
    #             "preferred_tag_id": [preferred_tag_id],
    #         }
    #     )

    #     try:
    #         # to_sqlメソッドを使用してUPSERT操作を実行
    #         status_data.to_sql(
    #             "TAG_STATUS",
    #             self.conn,
    #             if_exists="append",
    #             index=False,
    #             method="multi",
    #             dtype={
    #                 "tag_id": "INTEGER",
    #                 "format_id": "INTEGER",
    #                 "type_id": "INTEGER",
    #                 "alias": "INTEGER",
    #                 "preferred_tag_id": "INTEGER",
    #             },
    #         )
    #         print(f"タグステータスが正常に更新されました: {tag_id}, {format_id}")
    #         return tag_id
    #     except sqlite3.IntegrityError:
    #         # 既存のレコードが存在する場合は更新
    #         with self.conn:
    #             cursor = self.conn.cursor()
    #             cursor.execute(
    #                 """
    #                 UPDATE TAG_STATUS
    #                 SET type_id = ?, alias = ?, preferred_tag_id = ?
    #                 WHERE tag_id = ? AND format_id = ?
    #             """,
    #                 (type_id, int(alias), preferred_tag_id, tag_id, format_id),
    #             )
    #         print(f"タグのステータスが更新された: {tag_id}, {format_id}")
    #         return tag_id
    #     except Exception as e:
    #         print(f"タグのステータス更新エラー: {e}")
    #         raise

    # def create_tag(self, tag: str, source_tag: str) -> int:
    #     """
    #     タグを検索し、存在しない場合は新規作成します。

    #     Args:
    #         tag (str): 検索または作成するタグ

    #     Returns:
    #         int: タグのID
    #     """
    #     new_tag_df = pl.DataFrame({"tag": [tag], "source_tag": [source_tag]})
    #     try:
    #         new_tag_df.to_sql("TAGS", self.conn, if_exists="append", index=False)
    #         tag_id = self.find_tag_id(tag)  # 新しく作成されたタグのIDを取得
    #         print(f"新規タグが作成されました: {tag}")
    #     except Exception as e:
    #         print(f"新規タグ作成中にエラーが発生しました: {e}")
    #         raise
    #     return tag_id

    # def update_tag_usage_count(self, tag_id: int, format_id: int, use_count: int):
    #     current_count = self._get_current_usage_count(tag_id, format_id)
    #     if current_count:
    #         new_count = current_count
    #     else:
    #         new_count = use_count
    #     df = pl.DataFrame(
    #         {"tag_id": [tag_id], "format_id": [format_id], "count": [new_count]}
    #     )
    #     try:
    #         df.to_sql("TAG_USAGE_COUNTS", self.conn, if_exists="append", index=False)
    #     except sqlite3.IntegrityError:
    #         with self.conn:
    #             cursor = self.conn.cursor()
    #             cursor.execute(
    #                 """
    #                 UPDATE TAG_USAGE_COUNTS
    #                 SET count = ?
    #                 WHERE tag_id = ? AND format_id = ?
    #             """,
    #                 (new_count, tag_id, format_id),
    #             )
    #     except Exception as e:
    #         print(f"タグカウントにエラーが発生しました: {e}")

    # def update_tag_translation(self, tag_id: int, language: str, translation: str):
    #     df = pl.DataFrame(
    #         {"tag_id": [tag_id], "language": [language], "translation": [translation]}
    #     )
    #     df.to_sql("TAG_TRANSLATIONS", self.conn, if_exists="append", index=False)

    def convert_tag(self, search_tag: str, target_format_name: str):
        """タグをフォーマット推奨の形式に変換して表示する
        # TODO: サービス層に移動する

        Args:
            search_tag (str): 検索するタグ
            target_format_name (str): 変換先のフォーマット名
        """
        format_id = self.get_format_id(target_format_name)

        tag_id = self.find_tag_id(search_tag)

        if tag_id is not None:
            preferred_tag = self.find_preferred_tag(tag_id, format_id)
            if preferred_tag and preferred_tag != "invalid tag":
                # FIXME: preferred_tagにinvalid tag があるのは問題なのであとでなおす
                # FIXME: \(disambiguation\) を含むタグと original, skeb commission, pixiv commission, hashtag-only commentaryはDBから除去が必要
                if tag != preferred_tag:
                    print(f"タグ '{tag}' は '{preferred_tag}' に変換されました")
            else:
                return search_tag
        else:
            return search_tag
        return preferred_tag

    # def get_all_tag_ids(self):
    #     """すべてのタグIDを取得する関数です。
    #     Returns:
    #         list: すべてのタグIDのリスト。
    #     """
    #     query = "SELECT tag_id FROM TAGS"
    #     tag_ids = self.execute_query(query)
    #     return tag_ids["tag_id"].tolist()

    def get_tag_formats(self):
        """
        データベースからタグのフォーマットを取得する関数です。
        # TODO: 名前の取得はサービス層に移動する

        Returns:
            list: タグのフォーマットのリスト。'All' を含みます。
        """
        query = "SELECT DISTINCT format_name FROM TAG_FORMATS"
        formats = self.execute_query(query)
        add_all = pl.DataFrame({"format_name": ["All"]})
        formats = pl.concat([formats, add_all])
        return formats

    # def get_tag_languages(self):
    #     """
    #     データベースからタグの言語を取得する関数です。

    #     Returns:
    #         list: タグの言語のリスト。
    #     """
    #     query = "SELECT DISTINCT language FROM TAG_TRANSLATIONS"
    #     registered_languages = self.execute_query(query)
    #     add_all = pl.DataFrame({"language": ["All"]})
    #     langs = pl.concat([registered_languages, add_all])
    #     return langs

    # def get_tag_types(self, format_name: str = None):
    #     """フォーマットごとに設定されたタグのタイプを取得する関数

    #     Args:
    #         format_name (str): danbooru, e621, etc. または空文字列

    #     Returns:
    #         list: 指定されたフォーマットに対応するタグタイプのリスト。
    #             フォーマットが指定されていない場合は空のリスト。
    #     """
    #     if not format_name:
    #         return []

    #     format_id = self.get_format_id(format_name)

    #     if format_id is None:
    #         return []

    #     query = f"""
    #     SELECT DISTINCT ttn.type_name
    #     FROM TAG_TYPE_FORMAT_MAPPING AS ttfm
    #     JOIN TAG_TYPE_NAME AS ttn ON ttfm.type_name_id = ttn.type_name_id
    #     WHERE ttfm.format_id = {format_id}
    #     """
    #     types = self.execute_query(query)

    #     return types["type_name"].tolist()

    # def get_format_id(self, format_name: str) -> int:
    #     """フォーマット名からフォーマットIDを取得します。

    #     Args:
    #         format_name (str): フォーマット名。

    #     Returns:
    #         int: フォーマットID。

    #     Raises:
    #         KeyError: フォーマット名が見つからない場合。
    #     """
    #     query = f"SELECT format_id FROM TAG_FORMATS WHERE format_name = '{format_name}'"
    #     try:
    #         df = self.execute_query(query)
    #         return int(df["format_id"][0])
    #     except KeyError:
    #         message = f"サイト '{format_name}' が見つかりませんでした。"
    #         self.logger.error(message + "\n" + traceback.format_exc())

    # def get_type_id(self, type_name: str) -> Optional[int]:
    #     """タイプ名からタイプIDを取得します。"""
    #     query = (
    #         f"SELECT type_name_id FROM TAG_TYPE_NAME WHERE type_name = '{type_name}'"
    #     )
    #     try:
    #         df = self.execute_query(query)
    #         return int(df["format_id"][0])
    #     except KeyError:
    #         message = f"タイプ名 '{type_name}' が見つかりませんでした。"
    #         self.logger.error(message + "\n" + traceback.format_exc())

    # def find_preferred_tag(
    #     self, tag_id: int, format_id: Optional[int] = None
    # ) -> Optional[str]:
    #     """
    #     タグIDとオプションのフォーマットIDに基づいて、最適な推奨タグを検索します。

    #     Args:
    #         tag_id (int): タグID。
    #         format_id (Optional[int]): フォーマットID。指定しない場合は全フォーマットで検索。

    #     Returns:
    #         Optional[str]: 推奨タグ。見つからない場合はNoneを返します。
    #     """
    #     df = self._query_preferred_tags(tag_id, format_id)

    #     if df.empty:
    #         return None  # 推奨タグが見つからない場合

    #     if len(df) == 1:
    #         return df["preferred_tag"].iloc[0]

    #     # 複数の結果がある場合、Danbooru（ID: 1）のフォーマットを優先
    #     return self._select_preferred_tag(df)

    # def _select_preferred_tag(self, df: pl.DataFrame) -> str:
    #     """
    #     与えられたデータフレームから、優先すべき推奨タグを選択します。

    #     Args:
    #         df (pl.DataFrame): 推奨タグの検索結果。

    #     Returns:
    #         str: 優先する推奨タグ。
    #     """
    #     danbooru_format_id = 1
    #     danbooru_result = df[df["format_id"] == danbooru_format_id]

    #     if not danbooru_result.empty:
    #         return danbooru_result["preferred_tag"].iloc[0]

    #     # Danbooruのフォーマットがない場合、最初の結果を返す
    #     return df["preferred_tag"].iloc[0]

    # def _query_preferred_tags(
    #     self, tag_id: int, format_id: Optional[int] = None
    # ) -> pl.DataFrame:
    #     """
    #     指定されたタグIDとオプションのフォーマットIDに基づいて、推奨タグを検索します。

    #     Args:
    #         tag_id (int): タグID。
    #         format_id (Optional[int]): フォーマットID。指定しない場合は全フォーマットで検索。

    #     Returns:
    #         pl.DataFrame: 推奨タグの検索結果。
    #     """
    #     base_query = """
    #     SELECT T2.tag AS preferred_tag, TF.format_name, TF.format_id
    #     FROM TAG_STATUS AS T1
    #     JOIN TAGS AS T2 ON T1.preferred_tag_id = T2.tag_id
    #     JOIN TAG_FORMATS AS TF ON T1.format_id = TF.format_id
    #     WHERE T1.tag_id = ?
    #     """

    #     if format_id is not None:
    #         query = base_query + " AND T1.format_id = ?"
    #         return self.execute_query(query, params=(tag_id, format_id))
    #     else:
    #         return self.execute_query(base_query, params=(tag_id,))

    # def _get_current_usage_count(self, tag_id: int, format_id: int) -> int:
    #     query = "SELECT count FROM TAG_USAGE_COUNTS WHERE tag_id = ? AND format_id = ?"
    #     df = pl.read_sql_query(query, self.conn, params=(tag_id, format_id))
    #     return int(df["count"].iloc[0] if not df.empty else 0)

def initialize_tag_searcher() -> TagSearcher:
    return TagSearcher()


if __name__ == "__main__":
    word = "1boy"
    match_mode = "partial"
    prompt = "1boy, 1girl, 2boys, 2girls, 3boys, 3girls, 4boys, 4girls, 5boys"
    format_name = "e621"
    tagsearcher = initialize_tag_searcher()
    tags = []
    for tag in prompt.split(", "):
        tag = tagsearcher.convert_tag(prompt, format_name)
        tags.append(tag)
    cleanprompt = ", ".join(tags)
    print(prompt)
    print(cleanprompt)
    types = tagsearcher.get_tag_types("e621")
    print(types)
    langs = tagsearcher.get_tag_languages()
    print(langs)
