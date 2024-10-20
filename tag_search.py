from typing import Optional
import sqlite3
from pathlib import Path
import pandas as pd
from CSVToDatabaseProcessor import CSVToDatabaseProcessor
from cleanup_str import TagCleaner

db_path = Path(__file__).parent / "tags_v3.db"
conn = sqlite3.connect(db_path)

class TagSearcher:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def execute_query(self, query: str, params: tuple = None) -> pd.DataFrame:
        """SQLクエリを実行し、結果をDataFrameとして返します。

        Args:
            query (str): SQLクエリ。
            params (tuple, optional): クエリのパラメータ。デフォルトは None。

        Returns:
            pandas.DataFrame: クエリの実行結果。
        """
        return pd.read_sql_query(query, conn, params=params)

    def execute_insert(self, query: str, params: tuple = None):
        """
        SQL INSERT クエリを実行します。

        Args:
            query (str): SQL INSERT クエリ。
            params (tuple, optional): クエリのパラメータ。デフォルトは None。
        """
        with conn:  # トランザクションを使用
            cursor = conn.cursor()
            cursor.execute(query, params)

    def find_tag_id(self, keyword: str) -> Optional[int]:
        """TAGSテーブルからタグを完全一致で検索

        Args:
            keyword (str): 検索キーワード
        Returns:
            tag_id (Optional[int]): タグID
        Raises:
            ValueError: 複数または0件のタグが見つかった場合
        """
        query = "SELECT tag_id FROM TAGS WHERE tag = ?"
        df = self.execute_query(query, params=(keyword,))

        if df.empty:
            return None
        elif len(df) > 1:
            print(f"タグ '{keyword}' に対して複数のIDが見つかりました。\n {df}")
        else:
            return int(df['tag_id'].iloc[0])  # 最初の要素の値を取得

    def search_tags(self, keyword, match_mode='partial', format_name='All'):
        """
        タグを検索する関数です。

        Parameters:
            keyword (str): 検索キーワード
            match_mode (str, optional): キーワードのマッチングモード。'partial'（部分一致）または 'exact'（完全一致）。デフォルトは 'partial'。
            format_name (str, optional): タグのフォーマット。'All'（すべてのフォーマット）または特定のフォーマット名。デフォルトは 'All'。

        Returns:
            pandas.DataFrame: 検索結果のタグデータを含むデータフレーム
        """
        base_query = """
        SELECT
            T.tag_id,
            T.tag,
            T.source_tag,
            TT.language,
            TT.translation,
            TS.alias,
            PT.tag AS preferred_tag,
            TF.format_name,
            TUC.count AS usage_count,
            TTN.type_name
        FROM TAGS AS T
        LEFT JOIN TAG_TRANSLATIONS AS TT ON T.tag_id = TT.tag_id
        LEFT JOIN TAG_STATUS AS TS ON T.tag_id = TS.tag_id
        LEFT JOIN TAG_FORMATS AS TF ON TS.format_id = TF.format_id
        LEFT JOIN TAG_USAGE_COUNTS AS TUC ON T.tag_id = TUC.tag_id AND TS.format_id = TUC.format_id
        LEFT JOIN TAGS AS PT ON TS.preferred_tag_id = PT.tag_id
        LEFT JOIN TAG_TYPE_FORMAT_MAPPING AS TTFM ON TS.format_id = TTFM.format_id AND TS.type_id = TTFM.type_id
        LEFT JOIN TAG_TYPE_NAME AS TTN ON TTFM.type_name_id = TTN.type_name_id
        WHERE (T.tag {match_operator} ? OR TT.translation {match_operator} ?)
        """.replace("{match_operator}", "=" if match_mode == 'exact' else "LIKE")

        params = (keyword, keyword) if match_mode == 'exact' else (f'%{keyword}%', f'%{keyword}%')

        if format_name != 'All':
            base_query += " AND TF.format_name = ?"
            params += (format_name,)

        df = self.execute_query(base_query, params=params)

        # usage_count NaN値を0に設定
        df['usage_count'] = df['usage_count'].fillna(0).astype(int)

        # 列の順序を整理
        column_order = [
            'tag_id', 'tag', 'source_tag', 'language', 'translation',
            'alias', 'preferred_tag', 'format_name', 'usage_count', 'type_name'
        ]
        df = df[column_order]

        return df

    def get_tag_details(self, tag_id):
        query = """
        WITH RECURSIVE
        preferred_chain(tag_id, preferred_tag_id, level) AS (
            SELECT tag_id, preferred_tag_id, 0
            FROM TAG_STATUS
            WHERE tag_id = ?
            UNION ALL
            SELECT ts.tag_id, ts.preferred_tag_id, pc.level + 1
            FROM TAG_STATUS ts
            JOIN preferred_chain pc ON ts.tag_id = pc.preferred_tag_id
            WHERE ts.tag_id != ts.preferred_tag_id AND pc.level < 10
        )
        SELECT
            t.*,
            GROUP_CONCAT(DISTINCT tt.language || ':' || tt.translation) AS translations,
            ts.alias,
            pt.tag AS preferred_tag,
            pc.level AS alias_level,
            GROUP_CONCAT(DISTINCT tf.format_name) AS formats,
            GROUP_CONCAT(DISTINCT ttn.type_name) AS types,
            SUM(tuc.count) AS total_usage_count,
            GROUP_CONCAT(DISTINCT tf.format_name || ':' || tuc.count) AS usage_counts_by_format
        FROM TAGS t
        LEFT JOIN TAG_TRANSLATIONS tt ON t.tag_id = tt.tag_id
        LEFT JOIN TAG_STATUS ts ON t.tag_id = ts.tag_id
        LEFT JOIN TAG_FORMATS tf ON ts.format_id = tf.format_id
        LEFT JOIN TAG_USAGE_COUNTS tuc ON t.tag_id = tuc.tag_id AND ts.format_id = tuc.format_id
        LEFT JOIN TAG_TYPE_FORMAT_MAPPING ttfm ON ts.format_id = ttfm.format_id AND ts.type_id = ttfm.type_id
        LEFT JOIN TAG_TYPE_NAME ttn ON ttfm.type_name_id = ttn.type_name_id
        LEFT JOIN preferred_chain pc ON t.tag_id = pc.tag_id
        LEFT JOIN TAGS pt ON pc.preferred_tag_id = pt.tag_id
        WHERE t.tag_id = ?
        GROUP BY t.tag_id
        """
        return self.execute_query(query, params=(tag_id, tag_id))

    def get_tag_status(self, tag_id: int, format_id: int) -> Optional[dict]:
        query = """
        SELECT ts.*, t.tag, t.source_tag
        FROM TAG_STATUS ts
        JOIN TAGS t ON ts.tag_id = t.tag_id
        WHERE ts.tag_id = ? AND ts.format_id = ?
        """
        df = pd.read_sql_query(query, conn, params=(tag_id, format_id))
        return df.to_dict('records')[0] if not df.empty else None

    def update_tag_status(self, tag_id: int, format_id: int, type_id: int, alias: bool, preferred_tag_id: Optional[int]) -> int:
        """
        タグの状態を更新または新規作成します。

        Args:
            tag_id (int):
            formt_id (int);
            type_id (int):
            alias (bool):
            preferred_tag_id (Optional[int]):

        Returns:
            int: 更新または作成されたタグのID
        """

        if alias and preferred_tag_id is None: #TODO :後で考える
            raise ValueError("エイリアスタグには推奨タグの指定が必要です。")
        elif not alias:
            preferred_tag_id = tag_id

        # タグステータスの更新または挿入用のDataFrameを作成
        status_data = pd.DataFrame({
            'tag_id': [tag_id],
            'format_id': [format_id],
            'type_id': [type_id],
            'alias': [int(alias)],
            'preferred_tag_id': [preferred_tag_id]
        })

        try:
            # to_sqlメソッドを使用してUPSERT操作を実行
            status_data.to_sql('TAG_STATUS', conn, if_exists='append', index=False,
                            method='multi',
                            dtype={
                                'tag_id': 'INTEGER',
                                'format_id': 'INTEGER',
                                'type_id': 'INTEGER',
                                'alias': 'INTEGER',
                                'preferred_tag_id': 'INTEGER'
                            })
            print(f"タグステータスが正常に更新されました: {tag_id}, {format_id}")
            return tag_id
        except sqlite3.IntegrityError:
            # 既存のレコードが存在する場合は更新
            with conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE TAG_STATUS
                    SET type_id = ?, alias = ?, preferred_tag_id = ?
                    WHERE tag_id = ? AND format_id = ?
                """, (type_id, int(alias), preferred_tag_id, tag_id, format_id))
            print(f"タグのステータスが更新された: {tag_id}, {format_id}")
            return tag_id
        except Exception as e:
            print(f"タグのステータス更新エラー: {e}")
            raise

    def create_tag(self, tag: str, source_tag: str) -> int:
        """
        タグを検索し、存在しない場合は新規作成します。

        Args:
            tag (str): 検索または作成するタグ

        Returns:
            int: タグのID
        """
        new_tag_df = pd.DataFrame({'tag': [tag],
                                    'source_tag': [source_tag]
                                    })
        try:
            new_tag_df.to_sql('TAGS', conn, if_exists='append', index=False)
            tag_id = self.find_tag_id(tag)  # 新しく作成されたタグのIDを取得
            print(f"新規タグが作成されました: {tag}")
        except Exception as e:
            print(f"新規タグ作成中にエラーが発生しました: {e}")
            raise
        return tag_id

    def update_tag_usage_count(self, tag_id: int, format_id: int, use_count: int):
        current_count = self._get_current_usage_count(tag_id, format_id)
        if current_count:
            new_count = current_count
        else:
            new_count = use_count
        df = pd.DataFrame({
            'tag_id': [tag_id],
            'format_id': [format_id],
            'count': [new_count]
        })
        try:
            df.to_sql('TAG_USAGE_COUNTS', conn, if_exists='append', index=False)
        except sqlite3.IntegrityError:
            with conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE TAG_USAGE_COUNTS
                    SET count = ?
                    WHERE tag_id = ? AND format_id = ?
                """, (new_count, tag_id, format_id))
        except Exception as e:
            print(f'タグカウントにエラーが発生しました: {e}')

    def update_tag_translation(self, tag_id: int, language: str, translation: str):
        df = pd.DataFrame({
            'tag_id': [tag_id],
            'language': [language],
            'translation': [translation]
        })
        df.to_sql('TAG_TRANSLATIONS', conn, if_exists='append', index=False)

    def convert_prompt(self, prompt: str, format_name: str):
        """タグをフォーマット推奨の形式に変換して表示する

        Args:
            prompt (str): 検索するタグ (カンマ区切りも可)
            format_name (str): 変換先のフォーマット名
        """
        try:
            converted_tags = []
            format_id = self.get_format_id(format_name)
            clean_prompt = TagCleaner.clean_tags(prompt)
            for tag in clean_prompt.split(","):
                tag = tag.strip().lower() # FIXME: 小文字にすると顔文字に対応できないがテキストエンコーダーは大文字小文字区別するの？

                try:
                    tag_id = self.find_tag_id(tag)
                except ValueError:
                    converted_tags.append(tag)  # 元のタグを追加
                    continue

                if tag_id is not None:
                    preferred_tag = self.find_preferred_tag(tag_id, format_id)
                    if preferred_tag and preferred_tag != 'invalid tag': # FIXME: preferred_tagにinvalid tag があるのは問題なのであとでなおす
                        #FIXME: \(disambiguation\) を含むタグと original, skeb commission, pixiv commission, hashtag-only commentaryはDBから除去が必要
                        if tag != preferred_tag:
                            print(f"タグ '{tag}' は '{preferred_tag}' に変換されました")
                        converted_tags.append(preferred_tag)
                    else:
                        converted_tags.append(tag)  # 元のタグを追加
                else:
                    converted_tags.append(tag)  # tag_id が None の場合も元のタグを追加

            unique_tags = list(set(converted_tags))

            return ", ".join(unique_tags)
        except Exception as e:
            print(f"エラーが発生しました: {str(e)}")
            return None

    def get_all_tag_ids(self):
        """すべてのタグIDを取得する関数です。
        Returns:
            list: すべてのタグIDのリスト。
        """
        query = "SELECT tag_id FROM TAGS"
        tag_ids = self.execute_query(query)
        return tag_ids['tag_id'].tolist()

    def get_tag_formats(self):
        """
        データベースからタグのフォーマットを取得する関数です。

        Returns:
            list: タグのフォーマットのリスト。'All' を含みます。
        """
        query = "SELECT DISTINCT format_name FROM TAG_FORMATS"
        formats = self.execute_query(query)
        return ['All'] + formats['format_name'].tolist()

    def get_tag_languages(self):
        """
        データベースからタグの言語を取得する関数です。

        Returns:
            list: タグの言語のリスト。
        """
        query = "SELECT DISTINCT language FROM TAG_TRANSLATIONS"
        langs = self.execute_query(query)
        return ['All'] + langs['language'].tolist()

    def get_tag_types(self, format_name: str= None):
        """フォーマットごとに設定されたタグのタイプを取得する関数

        Args:
            format_name (str): danbooru, e621, etc. または空文字列

        Returns:
            list: 指定されたフォーマットに対応するタグタイプのリスト。
                フォーマットが指定されていない場合は空のリスト。
        """
        if not format_name:
            return []

        format_id = self.get_format_id(format_name)

        if format_id is None:
            return []

        query = f"""
        SELECT DISTINCT ttn.type_name
        FROM TAG_TYPE_FORMAT_MAPPING AS ttfm
        JOIN TAG_TYPE_NAME AS ttn ON ttfm.type_name_id = ttn.type_name_id
        WHERE ttfm.format_id = {format_id}
        """
        types = self.execute_query(query)

        return types['type_name'].tolist()

    def get_format_id(self, format_name: str) -> int:
        """フォーマット名からフォーマットIDを取得します。

        Args:
            format_name (str): フォーマット名。

        Returns:
            int: フォーマットID。見つからない場合は -1 を返します。
        """
        query = "SELECT format_id FROM TAG_FORMATS WHERE format_name = ?"
        df = self.execute_query(query, params=(format_name,))
        if not df.empty:
            return int(df['format_id'].iloc[0])
        else:
            return -1

    def get_type_id(self, type_name: str) -> int:
        """タイプ名からタイプIDを取得します。"""
        query = "SELECT type_name_id FROM TAG_TYPE_NAME WHERE type_name = ?"
        df = self.execute_query(query, params=(type_name,))
        if not df.empty:
            return int(df['type_name_id'].iloc[0])
        else:
            return -1

    def find_preferred_tag(self, tag_id: int, format_id: Optional[int] = None) -> Optional[str]:
        """
        タグIDとオプションのフォーマットIDに基づいて、最適な推奨タグを検索します。

        Args:
            tag_id (int): タグID。
            format_id (Optional[int]): フォーマットID。指定しない場合は全フォーマットで検索。

        Returns:
            Optional[str]: 推奨タグ。見つからない場合はNoneを返します。
        """
        df = self._query_preferred_tags(tag_id, format_id)

        if df.empty:
            return None  # 推奨タグが見つからない場合

        if len(df) == 1:
            return df['preferred_tag'].iloc[0]

        # 複数の結果がある場合、Danbooru（ID: 1）のフォーマットを優先
        return self._select_preferred_tag(df)

    def _select_preferred_tag(self, df: pd.DataFrame) -> str:
        """
        与えられたデータフレームから、優先すべき推奨タグを選択します。

        Args:
            df (pd.DataFrame): 推奨タグの検索結果。

        Returns:
            str: 優先する推奨タグ。
        """
        danbooru_format_id = 1
        danbooru_result = df[df['format_id'] == danbooru_format_id]

        if not danbooru_result.empty:
            return danbooru_result['preferred_tag'].iloc[0]

        # Danbooruのフォーマットがない場合、最初の結果を返す
        return df['preferred_tag'].iloc[0]

    def _query_preferred_tags(self, tag_id: int, format_id: Optional[int] = None) -> pd.DataFrame:
        """
        指定されたタグIDとオプションのフォーマットIDに基づいて、推奨タグを検索します。

        Args:
            tag_id (int): タグID。
            format_id (Optional[int]): フォーマットID。指定しない場合は全フォーマットで検索。

        Returns:
            pd.DataFrame: 推奨タグの検索結果。
        """
        base_query = """
        SELECT T2.tag AS preferred_tag, TF.format_name, TF.format_id
        FROM TAG_STATUS AS T1
        JOIN TAGS AS T2 ON T1.preferred_tag_id = T2.tag_id
        JOIN TAG_FORMATS AS TF ON T1.format_id = TF.format_id
        WHERE T1.tag_id = ?
        """

        if format_id is not None:
            query = base_query + " AND T1.format_id = ?"
            return self.execute_query(query, params=(tag_id, format_id))
        else:
            return self.execute_query(base_query, params=(tag_id,))

    def _get_current_usage_count(self, tag_id: int, format_id: int) -> int:
        query = "SELECT count FROM TAG_USAGE_COUNTS WHERE tag_id = ? AND format_id = ?"
        df = pd.read_sql_query(query, conn, params=(tag_id, format_id))
        return int(df['count'].iloc[0] if not df.empty else 0)

    def register_or_update_tag(self, tag_info: dict) -> int:
        """
        タグ情報をデータベースに登録または更新します。
        引数に normalized_tag が存在する場合はそれを使用し、
        存在しない場合は source_tag から生成します。

        Args:
            tag_info (dict): 登録するタグの情報を含む辞書

        Returns:
            int: 登録または更新されたタグのID

        Raises:
            Exception: データベース操作中にエラーが発生した場合
        """
        source_tag = tag_info['source_tag']
        normalized_tag = tag_info.get('normalized_tag')
        if normalized_tag is None:
            normalized_tag = CSVToDatabaseProcessor.normalize_tag(source_tag)

        format_name = tag_info['format_name']
        type_name = tag_info['type_name']
        alias = tag_info.get('alias', False)
        count = tag_info.get('use_count', 0)
        language = tag_info.get('language', '')
        translation = tag_info.get('translation', '')

        existing_tag_id = self.find_tag_id(normalized_tag)
        format_id = self.get_format_id(format_name)
        type_id = self.get_type_id(type_name)

        if existing_tag_id is None:
            # 新しいタグを挿入
            tag_id = self.create_tag(normalized_tag, source_tag)
        else:
            tag_id = existing_tag_id

        preferred_tag_id = self.find_preferred_tag(tag_id, format_id)

        # TAG_STATUSの更新または挿入
        self.update_tag_status(tag_id, format_id, type_id, alias, preferred_tag_id)

        # TAG_USAGE_COUNTSの更新
        self.update_tag_usage_count(tag_id, format_id, count)

        # TAG_TRANSLATIONSの更新または挿入
        if language and translation:
            self.update_tag_translation(tag_id, language, translation)

        return tag_id

    def _update_existing_tag(self, tag_id: int, source_tag: str, format_id: int, type_id: int, use_count: int, language: str, translation: str) -> int:
        """既存のタグ情報を更新します。"""
        # TAGSテーブルの更新
        tags_df = pd.DataFrame({'tag_id': [tag_id], 'source_tag': [source_tag]})
        tags_df.to_sql('TAGS', conn, if_exists='replace', index=False)

        # TAG_STATUSの更新または挿入
        status_df = pd.DataFrame({'tag_id': [tag_id], 'format_id': [format_id], 'type_id': [type_id], 'alias': [0], 'preferred_tag_id': [tag_id]})
        status_df.to_sql('TAG_STATUS', conn, if_exists='replace', index=False)

        # TAG_USAGE_COUNTSの更新
        current_count_df = pd.read_sql_query(f"SELECT count FROM TAG_USAGE_COUNTS WHERE tag_id = {tag_id} AND format_id = {format_id}", conn)
        current_count = current_count_df['count'].iloc[0] if not current_count_df.empty else 0
        usage_df = pd.DataFrame({'tag_id': [tag_id], 'format_id': [format_id], 'count': [current_count + use_count]})
        usage_df.to_sql('TAG_USAGE_COUNTS', conn, if_exists='replace', index=False)

        # TAG_TRANSLATIONSの更新または挿入
        if language and translation:
            translations_df = pd.DataFrame({'tag_id': [tag_id], 'language': [language], 'translation': [translation]})
            translations_df.to_sql('TAG_TRANSLATIONS', conn, if_exists='replace', index=False)

        return tag_id

def initialize_tag_searcher() -> TagSearcher:
    db_path = Path("tags_v3.db")
    return TagSearcher(db_path)

#if __name__ == '__main__':
    # word = "1boy"
    # match_mode = "partial"
    # search_and_display(word, match_mode, "All")
    # prompt = "1boy, 1girl, 2boys, 2girls, 3boys, 3girls, 4boys, 4girls, 5boys"
    # format_name = "e621"
    # tagsearcher = initialize_tag_searcher()
    # cleanprompt = tagsearcher.prompt_convert(prompt, format_name)
    # print(prompt)
    # print(cleanprompt)
    # types = tagsearcher.get_tag_types('e621')
    # print(types)
    # langs = tagsearcher.get_tag_languages()
    # print(langs)
