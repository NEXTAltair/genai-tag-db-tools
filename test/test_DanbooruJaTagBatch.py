import pytest
import sqlite3
import polars as pl

@pytest.fixture(scope="module")
def db_connection():
    """
    データベース接続を確立し、モジュールスコープのフィクスチャとして提供します。
    """
    conn = sqlite3.connect('tags_v3.db')
    yield conn
    conn.close()

@pytest.fixture(scope="module")
def tags_db(db_connection):
    """
    TAGSテーブルの内容を読み込んで提供します。
    """
    return pl.read_database("SELECT * FROM TAGS", db_connection)

@pytest.fixture(scope="module")
def translations_db(db_connection):
    """
    TAG_TRANSLATIONSテーブルの内容を読み込んで提供します。
    """
    return pl.read_database("SELECT * FROM TAG_TRANSLATIONS", db_connection)

@pytest.fixture(scope="module")
def status_db(db_connection):
    """
    TAG_STATUSテーブルの内容を読み込んで提供します。
    """
    return pl.read_database("SELECT * FROM TAG_STATUS", db_connection)

@pytest.fixture(scope="module")
def original_df():
    """
    元のParquetファイルからデータを読み込んで提供します。
    """
    return pl.read_parquet('hf://datasets/p1atdev/danbooru-ja-tag-pair-20241015/data/train-00000-of-00001.parquet')


def test_tags_table(tags_db, original_df):
    """
    TAGSテーブルにすべてのタイトルが存在するかを確認するテスト。
    """
    titles_df = original_df['title'].unique().to_list()
    titles_db = tags_db['source_tag'].unique().to_list()
    missing_titles = set(titles_df) - set(titles_db)

    assert len(missing_titles) == 0, f"❌ 以下のタイトルがTAGSテーブルに存在しません: {missing_titles}"


def test_translations_table(translations_db, tags_db, original_df):
    """
    TAG_TRANSLATIONSテーブルにすべての翻訳が存在するかを確認するテスト。
    """
    # 'other_names'を展開して、翻訳ごとに一行にする
    df_translations = original_df.explode('other_names').select(['id', 'title', 'other_names'])

    # タイトルからtag_idへのマッピングをDataFrameで作成
    title_tag_id_df = tags_db.rename({'source_tag': 'title'})

    # タイトルをtag_idにマッピング（joinを使用）
    df_translations = df_translations.join(title_tag_id_df.select(['title', 'tag_id']), on='title', how='left')

    # 期待される翻訳のDataFrameを作成
    expected_translations = df_translations.rename({'other_names': 'translation'}).select(['tag_id', 'translation'])

    # tag_id が null であるものがあればエラーとして表示
    missing_tag_ids = expected_translations.filter(pl.col('tag_id').is_null())
    assert len(missing_tag_ids) == 0, f"❌ 以下のタイトルのtag_idが見つかりません: {missing_tag_ids}"

    # TAGSとTAG_TRANSLATIONSテーブルをJOINしてデータを取得
    joined_db = tags_db.join(translations_db, on='tag_id', how='inner').filter(pl.col('language') == 'japanese').select(['tag_id', 'translation'])

    # 欠けている翻訳を見つける
    missing_translations = expected_translations.join(joined_db, on=['tag_id', 'translation'], how='anti')

    if len(missing_translations) > 0:
        print("⚠️ TAG_TRANSLATIONS か danbooru-ja-tag-pair-20241015 テーブルに以下の翻訳が存在しません:")
        print(missing_translations)
    
    # danbooru-ja-tag-pair-20241015 にある情報が TAG_TRANSLATIONS に登録されていない場合のみエラーとする
    missing_in_tags_db = expected_translations.join(joined_db, on=['tag_id', 'translation'], how='anti')
    assert len(missing_in_tags_db) == 0, f"❌ danbooru-ja-tag-pair-20241015 テーブルに存在するが TAG_TRANSLATIONS テーブルに存在しない翻訳があります: {missing_in_tags_db}"

def test_tag_status_table(status_db, tags_db, original_df):
    """
    TAG_STATUSテーブルにすべてのタグステータスが存在するかを確認するテスト。
    """
    # タイプ名からtype_idへのマッピングをDataFrameで作成
    type_id_map = {
        'general': 0,
        'artist': 1,
        'copyright': 3,
        'character': 4,
        'meta': 5,
    }
    type_id_df = pl.DataFrame({'type': list(type_id_map.keys()), 'type_id': list(type_id_map.values())})

    # 期待されるタグステータスのDataFrameを作成
    expected_statuses = original_df.select(['title', 'type']).unique()

    # タイトルをtag_idにマッピング（joinを使用）
    title_tag_id_df = tags_db.rename({'source_tag': 'title'})
    expected_statuses = expected_statuses.join(title_tag_id_df.select(['title', 'tag_id']), on='title', how='left')

    # タイプをtype_idにマッピング（joinを使用）
    expected_statuses = expected_statuses.join(type_id_df, on='type', how='left')

    # format_id列を追加し、データ型をi64に統一
    expected_statuses = expected_statuses.with_columns(
        pl.lit(1, dtype=pl.Int64).alias('format_id')
    )

    # 必要な列を選択
    expected_statuses = expected_statuses.select(['tag_id', 'format_id', 'type_id']).drop_nulls('tag_id')

    # データベースから実際のタグステータスを取得し、format_idのデータ型をi64に統一
    actual_statuses = status_db.with_columns(
        pl.col('format_id').cast(pl.Int64)
    ).select(['tag_id', 'format_id', 'type_id'])

    # 欠けているまたは不正なタグステータスを見つける
    missing_statuses = expected_statuses.join(actual_statuses, on=['tag_id', 'format_id', 'type_id'], how='anti')

    if len(missing_statuses) > 0:
        print("❌ TAG_STATUSテーブルに以下のタグステータスが存在しません、または不正です:")
        print(missing_statuses)
    assert len(missing_statuses) == 0, f"❌ TAG_STATUSテーブルに以下のタグステータスが存在しません、または不正です: {missing_statuses}"
