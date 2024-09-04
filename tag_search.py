from typing import Optional
import sqlite3
from pathlib import Path
import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output

from CSVToDatabaseProcessor import CSVToDatabaseProcessor

db_path = Path(__file__).parent / "tags_v3.db"
conn = sqlite3.connect(db_path)

class TagSearcher:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def execute_sql_query(self, query: str, params: tuple = None) -> pd.DataFrame:
        """SQLクエリを実行し、結果をDataFrameとして返します。

        Args:
            query (str): SQLクエリ。
            params (tuple, optional): クエリのパラメータ。デフォルトは None。

        Returns:
            pandas.DataFrame: クエリの実行結果。
        """
        return pd.read_sql_query(query, conn, params=params)

    def execute_insert_query(self, query: str, params: tuple = None):
        """
        SQL INSERT クエリを実行します。

        Args:
            query (str): SQL INSERT クエリ。
            params (tuple, optional): クエリのパラメータ。デフォルトは None。
        """
        with conn:  # トランザクションを使用
            cursor = conn.cursor()
            cursor.execute(query, params)

    def search_tag_id(self, keyword: str) -> Optional[int]:
        """TAGSテーブルからタグを完全一致で検索

        Args:
            keyword (str): 検索キーワード
        Returns:
            tag_id (Optional[int]): タグID
        Raises:
            ValueError: 複数または0件のタグが見つかった場合
        """
        query = "SELECT tag_id FROM TAGS WHERE tag = ?"
        df = self.execute_sql_query(query, params=(keyword,))

        if df.empty:
            return None
        elif len(df) > 1:
            print(f"タグ '{keyword}' に対して複数のIDが見つかりました。\n {df}")
        else:
            return int(df['tag_id'].iloc[0])  # 最初の要素の値を取得

    def _get_format_id_by_name(self, format_name: str) -> int:
        """フォーマット名からフォーマットIDを取得します。

        Args:
            format_name (str): フォーマット名。

        Returns:
            int: フォーマットID。見つからない場合は -1 を返します。
        """
        query = "SELECT format_id FROM TAG_FORMATS WHERE format_name = ?"
        df = self.execute_sql_query(query, params=(format_name,))
        if not df.empty:
            return int(df['format_id'].iloc[0])
        else:
            return -1

    def _get_type_id_by_name(self, type_name: str) -> int:
        """タイプ名からタイプIDを取得します。"""
        query = "SELECT type_name_id FROM TAG_TYPE_NAME WHERE type_name = ?"
        df = self.execute_sql_query(query, params=(type_name,))
        if not df.empty:
            return df['type_name_id'].iloc[0]
        else:
            return -1

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
            return self.execute_sql_query(query, params=(tag_id, format_id))
        else:
            return self.execute_sql_query(base_query, params=(tag_id,))

    def get_preferred_tag(self, tag_id: int, format_name: str) -> Optional[str]:
        """
        指定されたタグIDとフォーマット名に基づいて、推奨タグを取得します。
        指定フォーマットで見つからない場合、全フォーマットで検索します。

        Args:
            tag_id (int): タグID。
            format_name (str): フォーマット名。

        Returns:
            Optional[str]: 推奨タグ。見つからない場合はNoneを返します。
        """
        format_id = self._get_format_id_by_name(format_name)

        # 指定フォーマットで検索
        if format_id != -1:
            df = self._query_preferred_tags(tag_id, format_id)
            if not df.empty:
                return df['preferred_tag'].iloc[0]

        # 全フォーマットで検索
        df = self._query_preferred_tags(tag_id)

        if df.empty:
            return None  # 推奨タグが見つからない場合

        # 結果の処理
        if len(df) == 1:
            return df['preferred_tag'].iloc[0]
        else:
            # 複数の結果がある場合の処理
            print(f"タグID {tag_id} に対して複数の推奨タグが見つかりました:")
            for _, row in df.iterrows():
                print(f"フォーマット: {row['format_name']}, 推奨タグ: {row['preferred_tag']}")

            # Danbooruのフォーマット（ID: 1）を優先
            danbooru_result = df[df['format_id'] == 1]
            if not danbooru_result.empty:
                return danbooru_result['preferred_tag'].iloc[0]

            # Danbooruのフォーマットがない場合、最初の結果を返す
            return df['preferred_tag'].iloc[0]

    def prompt_convert(self, keyword: str, format_name: str):
        """タグをフォーマット推奨の形式に変換して表示する

        Args:
            keyword (str): 検索するタグ (カンマ区切りも可)
            format_name (str): 変換先のフォーマット名
        """
        try:
            converted_tags = []
            for tag in keyword.split(","):
                tag = tag.strip().lower()
                tag = CSVToDatabaseProcessor.normalize_tag(tag)

                try:
                    tag_id = self.search_tag_id(tag)
                except ValueError:
                    converted_tags.append(tag)  # 元のタグを追加
                    continue

                if tag_id is not None:
                    preferred_tag = self.get_preferred_tag(tag_id, format_name)
                    if preferred_tag and preferred_tag != 'invalid tag': # TODO: preferred_tagにinvalid tag があるのは問題なのであとでなおす
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
        return self.execute_sql_query(query, params=(tag_id, tag_id))

    def get_all_tag_ids(self):
        """すべてのタグIDを取得する関数です。
        Returns:
            list: すべてのタグIDのリスト。
        """
        query = "SELECT tag_id FROM TAGS"
        tag_ids = self.execute_sql_query(query)
        return tag_ids['tag_id'].tolist()

    def get_tag_formats(self):
        """
        データベースからタグのフォーマットを取得する関数です。

        Returns:
            list: タグのフォーマットのリスト。'All' を含みます。
        """
        query = "SELECT DISTINCT format_name FROM TAG_FORMATS"
        formats = self.execute_sql_query(query)
        return ['All'] + formats['format_name'].tolist()

    def get_tag_langs(self):
        """
        データベースからタグの言語を取得する関数です。

        Returns:
            list: タグの言語のリスト。
        """
        query = "SELECT DISTINCT language FROM TAG_TRANSLATIONS"
        langs = self.execute_sql_query(query)
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

        format_id = self._get_format_id_by_name(format_name)

        if format_id is None:
            return []

        query = f"""
        SELECT DISTINCT ttn.type_name
        FROM TAG_TYPE_FORMAT_MAPPING AS ttfm
        JOIN TAG_TYPE_NAME AS ttn ON ttfm.type_name_id = ttn.type_name_id
        WHERE ttfm.format_id = {format_id}
        """
        types = self.execute_sql_query(query)

        return types['type_name'].tolist()

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

        df = self.execute_sql_query(base_query, params=params)

        # usage_count NaN値を0に設定
        df['usage_count'] = df['usage_count'].fillna(0).astype(int)

        # 列の順序を整理
        column_order = [
            'tag_id', 'tag', 'source_tag', 'language', 'translation',
            'alias', 'preferred_tag', 'format_name', 'usage_count', 'type_name'
        ]
        df = df[column_order]

        return df

    def search_and_display(self, keyword, match_mode, format_name, columns=None):
        keyword = keyword.strip().lower()
        print("search_and_display関数が呼び出されました")
        clear_output(wait=True)
        try:
            print(f"キーワード '{keyword}' で検索中... モード: {match_mode}, フォーマット: {format_name}")
            search_results = self.search_tags(keyword, match_mode, format_name)

            if search_results.empty:
                print(f"'{keyword}' に関する結果は見つかりませんでした")
                return

            all_details = []
            processed_tag_ids = set()
            for _, row in search_results.iterrows():
                tag_id = row['tag_id']
                if tag_id in processed_tag_ids:
                    continue
                processed_tag_ids.add(tag_id)

                print(f"タグID {tag_id} の詳細情報を取得中...")
                details = self.get_tag_details(tag_id)

                detail_dict = {}
                if not details.empty:
                    for col in details.columns:
                        value = details[col].iloc[0]
                        detail_dict[col] = str(value) if value is not None else "NULL"
                else:
                    detail_dict = {col: "NULL" for col in details.columns}

                all_details.append(detail_dict)

            df = pd.DataFrame(all_details)

            if columns:
                df = df[columns]
                print(f"選択されたカラム: {', '.join(columns)}")

            display(df)

        except Exception as e:
            print(f"エラーが発生しました: {str(e)}")
        print("search_and_display関数が完了しました")

    def register_tag_in_db(self, tag_info: dict) -> int:
        """
        検証済みのタグ情報をデータベースに登録します。

        Args:
            tag_info (dict): register_tag_widget関数から返された検証済みタグ情報

        Returns:
            int: 登録されたタグのID


        """
        normalized_tag = tag_info['normalized_tag']
        source_tag = tag_info['source_tag']
        format_name = tag_info['format_name']
        type_name = tag_info['type_name']
        use_count = tag_info.get('use_count', 0)
        language = tag_info.get('language', '')
        translation = tag_info.get('translation', '')

        format_id = self._get_format_id_by_name(format_name)
        type_id = self._get_type_id_by_name(type_name)

        if source_tag == normalized_tag:
            source_tag = normalized_tag

        # タグの存在確認
        existing_tag = self.search_tag_id(normalized_tag)

        if existing_tag is not None:
            tag_id = existing_tag
        else:
            # 新しいタグの挿入
            new_tag_df = pd.DataFrame([{'tag': normalized_tag, 'source_tag': source_tag}])
            new_tag_df.to_sql('TAGS', conn, if_exists='append', index=False)
            tag_id = self.search_tag_id(normalized_tag)

            # TAG_STATUSの挿入
            status_df = pd.DataFrame([{'tag_id': tag_id, 'format_id': format_id, 'type_id': type_id, 'alias': 0, 'preferred_tag_id': tag_id}])
            status_df.to_sql('TAG_STATUS', conn, if_exists='append', index=False)
            # TAG_USAGE_COUNTSの挿入
            usage_df = pd.DataFrame([{'tag_id': tag_id, 'format_id': format_id, 'count': use_count}])
            usage_df.to_sql('TAG_USAGE_COUNTS', conn, if_exists='append', index=False)
            # TAG_TRANSLATIONSの挿入
            translations_df = pd.DataFrame([{'tag_id': tag_id, 'language': language, 'translation': translation}])
            translations_df.to_sql('TAG_TRANSLATIONS', conn, if_exists='append', index=False)

        return tag_id

def create_widgets(tagsearcher):
    search_input = widgets.Text(description="タグ検索:")
    search_button = widgets.Button(description="検索")
    match_mode_radio = widgets.RadioButtons(
        options=['部分一致', '完全一致'],
        description='検索モード:',
        disabled=False
    )

    # フォーマット選択用のドロップダウンを追加
    format_dropdown = widgets.Dropdown(
        options=tagsearcher.get_tag_formats(),
        value='All',
        description='フォーマット:',
        disabled=False
    )

    # カラム選択用のCheckboxを作成
    column_options = ['tag_id', 'tag', 'source_tag', 'language', 'translation', 'alias', 'preferred_tag', 'format_name', 'usage_count', 'type_name']
    column_checkboxes = [widgets.Checkbox(value=True, description=col) for col in column_options]
    column_box = widgets.VBox(column_checkboxes, description='表示カラム:')

    def on_button_clicked(b):
        match_mode = 'partial' if match_mode_radio.value == '部分一致' else 'exact'
        selected_columns = [cb.description for cb in column_checkboxes if cb.value]
        tagsearcher.search_and_display(search_input.value, match_mode, format_dropdown.value, columns=selected_columns)

    search_button.on_click(on_button_clicked)

    vbox = widgets.VBox([search_input, match_mode_radio, format_dropdown, column_box, search_button])
    return vbox

def create_cleaning_widgets(tagsearcher):
    """カンマ区切りのタグを受け取って指定フォーマット形式へ変換するウィジェットを作成する
    """
    input_prompt = widgets.Text(description="Prompt:")
    convert_button = widgets.Button(description="変換")
    format_dropdown = widgets.Dropdown(
        options=tagsearcher.get_tag_formats(),
        value='All',
        description='フォーマット:',
        disabled=False
    )

    def on_button_clicked(b):
        converted_tags = tagsearcher.prompt_convert(input_prompt.value, format_dropdown.value)
        print(converted_tags)

    convert_button.on_click(on_button_clicked)

    vbox = widgets.VBox([input_prompt, format_dropdown, convert_button])
    return vbox

def initialize_tag_searcher() -> TagSearcher:
    db_path = Path("tags_v3.db")
    return TagSearcher(db_path)

def register_tag_widgets(tagsearcher):
    tag_input = widgets.Text(description="タグ:")
    source_tag_input = widgets.Text(description="元タグ:")
    format_dropdown = widgets.Dropdown(
        options=tagsearcher.get_tag_formats(),
        value='All',
        description='フォーマット:',
        disabled=False
    )
    # タイプ選択用のドロップダウンを追加
    type_options = [('', None)] + [(t, t) for t in tagsearcher.get_tag_types(format_dropdown.value)]
    type_dropdown = widgets.Dropdown(
        options=type_options,
        value=None,
        description='タイプ:',
        disabled=False,
        placeholder='タイプを選択'
    )

    # カウント入力用のテキストボックスを追加
    use_count_input = widgets.IntText(
        value=0,
        description='使用回数:',
        disabled=False
    )

    language_combobox = widgets.Combobox(
        options=tagsearcher.get_tag_langs(),
        value='japanese',
        description='言語:',
        ensure_option=True,  # 入力されたテキストをオプションに追加
        disabled=False
    )
    translation_input = widgets.Text(
        value='',
        description='翻訳:',
        disabled=False
    )

    register_button = widgets.Button(description="登録")
    output = widgets.Output()

    def update_type_dropdown(change):
        new_format = change['new']
        new_types = [('', None)] + [(t, t) for t in tagsearcher.get_tag_types(new_format)]
        type_dropdown.options = new_types
        type_dropdown.value = None

    format_dropdown.observe(update_type_dropdown, names='value')

    def on_register_click(b):
        with output:
            clear_output()
            try:
                if not tag_input.value and not source_tag_input.value:
                    raise ValueError("タグまたは元タグは必須です。")
                if ',' in tag_input.value or ',' in source_tag_input.value:
                    raise ValueError("登録するタグは単一のタグである必要があります。")

                if not source_tag_input.value:
                    source_tag_input.value = tag_input.value

                normalized_tag = CSVToDatabaseProcessor.normalize_tag(tag_input.value)

                tag_info = {
                    'normalized_tag': normalized_tag,
                    'source_tag': source_tag_input.value,
                    'format_name': format_dropdown.value,
                    'type_name': type_dropdown.value,
                    'use_count': use_count_input.value,
                    'language': language_combobox.value,
                    'translation': translation_input.value
                }
                tag_id = tagsearcher.register_tag_in_db(tag_info)
                print(f"タグが正常に登録されました。Tag ID: {tag_id}")
            except Exception as e:
                print(f"エラー: {str(e)}")

    register_button.on_click(on_register_click)

    widget_box = widgets.VBox([
        tag_input,
        source_tag_input,
        format_dropdown,
        type_dropdown,
        use_count_input,
        language_combobox,
        translation_input,
        register_button,
        output
    ])

    return widget_box

if __name__ == '__main__':
    # word = "1boy"
    # match_mode = "partial"
    # search_and_display(word, match_mode, "All")
    # prompt = "1boy, 1girl, 2boys, 2girls, 3boys, 3girls, 4boys, 4girls, 5boys"
    # format_name = "e621"
    tagsearcher = initialize_tag_searcher()
    # cleanprompt = tagsearcher.prompt_convert(prompt, format_name)
    # print(prompt)
    # print(cleanprompt)
    # types = tagsearcher.get_tag_types('e621')
    # print(types)
    langs = tagsearcher.get_tag_langs()
    print(langs)