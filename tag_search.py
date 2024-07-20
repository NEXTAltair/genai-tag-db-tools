import sqlite3
import pandas as pd
import ipywidgets as widgets
from IPython.display import display, clear_output

conn = sqlite3.connect('tags_v3.db')

def get_tag_details(tag_id):
    """
    指定されたタグIDに基づいてタグの詳細を取得します。

    Args:
        tag_id (int): 詳細を取得するタグのID。

    Returns:
        pandas.DataFrame: タグの詳細を含むDataFrame。

    """
    query = """
    SELECT 
        t.*, 
        tt.language, 
        tt.translation, 
        ts.alias, 
        pt.tag AS preferred_tag,  -- preferred_tag_id をタグ名に変換
        ts.format_id, 
        ts.type_id,
        tf.format_name, 
        tf.description AS format_description,
        tuc.count AS usage_count,
        ttfm.description AS type_description,
        ttn.type_name
    FROM TAGS t
    LEFT JOIN TAG_TRANSLATIONS tt ON t.tag_id = tt.tag_id
    LEFT JOIN TAG_STATUS ts ON t.tag_id = ts.tag_id
    LEFT JOIN TAG_FORMATS tf ON ts.format_id = tf.format_id
    LEFT JOIN TAG_USAGE_COUNTS tuc ON t.tag_id = tuc.tag_id AND ts.format_id = tuc.format_id
    LEFT JOIN TAG_TYPE_FORMAT_MAPPING ttfm ON ts.format_id = ttfm.format_id AND ts.type_id = ttfm.type_id
    LEFT JOIN TAG_TYPE_NAME ttn ON ttfm.type_name_id = ttn.type_name_id
    LEFT JOIN TAGS pt ON ts.preferred_tag_id = pt.tag_id  -- preferred_tag_id をタグ名に変換するための結合
    WHERE t.tag_id = ?
    """
    return pd.read_sql_query(query, conn, params=(tag_id,))

def get_tag_formats():
    """
    データベースからタグのフォーマットを取得する関数です。

    Returns:
        list: タグのフォーマットのリスト。'全て' を含みます。
    """
    query = "SELECT DISTINCT format_name FROM TAG_FORMATS"
    formats = pd.read_sql_query(query, conn)
    return ['全て'] + formats['format_name'].tolist()

def get_format_id_by_name(format_name: str) -> int:
    """フォーマット名からフォーマットIDを取得します。

    Args:
        format_name (str): フォーマット名。

    Returns:
        int: フォーマットID。見つからない場合は -1 を返します。
    """
    query = "SELECT format_id FROM TAG_FORMATS WHERE format_name = ?"
    df = pd.read_sql_query(query, conn, params=(format_name,))
    if not df.empty:
        return df['format_id'].iloc[0]
    else:
        return -1

def get_preferred_tag(tag_id: int, format_name: str) -> str:
    """指定されたタグIDとフォーマット名に基づいて、推奨タグを取得します。

    Args:
        tag_id (int): タグID。
        format_name (str): フォーマット名。

    Returns:
        str: 推奨タグ。見つからない場合は None を返します。
    """
    # format_id を取得
    format_id = get_format_id_by_name(format_name)
    if format_id == -1:
        return None  # フォーマットIDが見つからない場合は None を返す

    query = f"""
    SELECT 
        T2.tag AS preferred_tag 
    FROM 
        TAG_STATUS AS T1
    JOIN 
        TAGS AS T2 ON T1.preferred_tag_id = T2.tag_id
    WHERE 
        T1.tag_id = {tag_id} AND T1.format_id = {format_id}
    """
    df = pd.read_sql_query(query, conn)
    if not df.empty:
        return df['preferred_tag'].iloc[0]
    else:
        return None

def search_tag_id(keyword: str) -> int:
    """TAGSテーブルからタグを完全一致で検索

    Args:
        keyword (str): 検索キーワード
    Returns:
        tag_id (int): タグID
    Raises:
        ValueError: 複数または0件のタグが見つかった場合
    """
    query = """
    SELECT tag_id
    FROM TAGS
    WHERE tag = ?
    """
    df = pd.read_sql_query(query, conn, params=(keyword,))

    if df.empty:
        return None
    elif len(df) > 1:
        raise ValueError(f"タグ '{keyword}' に対して複数のIDが見つかりました。")
    else:
        return df['tag_id'].iloc[0]  # 最初の要素の値を取得

def search_tags(keyword, match_mode='partial', format='全て'):
    """
    タグを検索する関数です。

    Parameters:
        keyword (str): 検索キーワード
        match_mode (str, optional): キーワードのマッチングモード。'partial'（部分一致）または 'exact'（完全一致）。デフォルトは 'partial'。
        format (str, optional): タグのフォーマット。'全て'（すべてのフォーマット）または特定のフォーマット名。デフォルトは '全て'。

    Returns:
        pandas.DataFrame: 検索結果のタグデータを含むデータフレーム
    """
    if match_mode == 'exact':
        base_query = """
        SELECT DISTINCT T.* 
        FROM TAGS AS T
        JOIN TAG_TRANSLATIONS AS TT ON T.tag_id = TT.tag_id
        JOIN TAG_STATUS AS TS ON T.tag_id = TS.tag_id
        JOIN TAG_FORMATS AS TF ON TS.format_id = TF.format_id
        WHERE (T.tag = ? OR TT.translation = ?)
        """
    else:
        base_query = """
        SELECT DISTINCT T.*
        FROM TAGS AS T
        JOIN TAG_TRANSLATIONS AS TT ON T.tag_id = TT.tag_id
        JOIN TAG_STATUS AS TS ON T.tag_id = TS.tag_id
        JOIN TAG_FORMATS AS TF ON TS.format_id = TF.format_id
        WHERE (T.tag LIKE ? OR TT.translation LIKE ?)
        """
    
    if format != '全て':
        base_query += " AND TF.format_name = ?"
        params = (keyword, keyword, format) if match_mode == 'exact' else (f'%{keyword}%', f'%{keyword}%', format)
    else:
        params = (keyword, keyword) if match_mode == 'exact' else (f'%{keyword}%', f'%{keyword}%')
    
    return pd.read_sql_query(base_query, conn, params=params)

def prompt_convert(keyword: str, format_name: str):
    """タグをフォーマット推奨の形式に変換して表示する

    Args:
        keyword (str): 検索するタグ (カンマ区切りも可)
        format_name (str): 変換先のフォーマット名
    """
    try:
        converted_tags = []
        for tag in keyword.split(","):
            tag = tag.strip().lower()

            try:
                tag_id = search_tag_id(tag)
            except ValueError:
                converted_tags.append(tag)  # 元のタグを追加
                continue

            if tag_id is not None:
                preferred_tag = get_preferred_tag(tag_id, format_name)
                if preferred_tag:
                    print(f"タグ '{tag}' は '{preferred_tag}' に変換されました")
                    converted_tags.append(preferred_tag)  # preferred_tag を追加
                else:
                    converted_tags.append(tag)  # 元のタグを追加
            else:
                converted_tags.append(tag)  # tag_id が None の場合も元のタグを追加

        return ", ".join(converted_tags)  # 変換されたタグをカンマ区切りで返す
    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")
        return None

def search_and_display(keyword, match_mode, format, columns=None):
    keyword = keyword.strip().lower()
    print("search_and_display関数が呼び出されました")
    clear_output(wait=True)
    try:
        print(f"キーワード '{keyword}' で検索中... モード: {match_mode}, フォーマット: {format}")
        search_results = search_tags(keyword, match_mode, format)

        if search_results.empty:
            print(f"'{keyword}' に関する結果は見つかりませんでした")
            return

        all_details = []
        processed_tag_ids = set()
        for index, row in search_results.iterrows():
            tag_id = row['tag_id']
            if tag_id in processed_tag_ids:
                continue
            processed_tag_ids.add(tag_id)

            print(f"タグID {tag_id} の詳細情報を取得中...")
            details = get_tag_details(tag_id)

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

def create_widgets():
    search_input = widgets.Text(description="タグ検索:")
    search_button = widgets.Button(description="検索")
    match_mode_radio = widgets.RadioButtons(
        options=['部分一致', '完全一致'],
        description='検索モード:',
        disabled=False
    )
    
    # フォーマット選択用のドロップダウンを追加
    format_dropdown = widgets.Dropdown(
        options=get_tag_formats(),
        value='全て',
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
        search_and_display(search_input.value, match_mode, format_dropdown.value, columns=selected_columns)
    
    search_button.on_click(on_button_clicked)
    
    vbox = widgets.VBox([search_input, match_mode_radio, format_dropdown, column_box, search_button])
    return vbox

def create_cleaning_widgets():
    """カンマ区切りのタグを受け取って指定フォーマット形式へ変換するウィジェットを作成する
    """
    input_prompt = widgets.Text(description="Prompt:")
    convert_button = widgets.Button(description="変換")
    format_dropdown = widgets.Dropdown(
        options=get_tag_formats(),
        value='全て',
        description='フォーマット:',
        disabled=False
    )

    def on_button_clicked(b):
        converted_tags = prompt_convert(input_prompt.value, format_dropdown.value)
        print(converted_tags)

    convert_button.on_click(on_button_clicked)

    vbox = widgets.VBox([input_prompt, format_dropdown, convert_button])
    return vbox

if __name__ == '__main__':
    # word = "1boy"
    # match_mode = "partial"
    # search_and_display(word, match_mode, "全て")
    prompt = "[W_, aza_shinobu, Die Wergelder, score_9,score_8_up,score_7_up,very aesthetic,close-up,1man,jeans,jeans down,1girl, pretty, shy,tank top,skirt,strap slip,one breast out,medium breasts,perfect breasts,puffy nipples,kneeling,deepthroat,irrumatio,balls deep,drool,girl bedroom,detailed face,intricate details,naturalism,hyperdetailed,hyperrealistic,,<lora:g0th1cPXL:0.7>,g0thicPXL,<lora:HKStyle:0.8>,HKStyle,<lora:Expressive_H:0.8>,Expressiveh"
    format_name = "e621"
    cleanprompt = prompt_convert(prompt, format_name)
    print(prompt)
    print(cleanprompt)