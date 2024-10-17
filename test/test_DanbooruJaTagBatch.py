import sqlite3
import polars as pl

# データベースに接続
conn = sqlite3.connect('tags_v3.db')

# TAGSテーブルを読み込み
tags_db = pl.read_database("SELECT * FROM TAGS", conn)

# TAG_TRANSLATIONSテーブルを読み込み
translations_db = pl.read_database("SELECT * FROM TAG_TRANSLATIONS", conn)

# TAG_STATUSテーブルを読み込み
status_db = pl.read_database("SELECT * FROM TAG_STATUS", conn)

# 接続を閉じる
conn.close()

# 元のDataFrameを読み込み
df = pl.read_parquet('hf://datasets/p1atdev/danbooru-ja-tag-pair-20241015/data/train-00000-of-00001.parquet')

# 1. TAGSテーブルの検証
titles_df = df['title'].unique().to_list()
titles_db = tags_db['source_tag'].unique().to_list()
missing_titles = set(titles_df) - set(titles_db)

if missing_titles:
    print(f"❌ 以下のタイトルがTAGSテーブルに存在しません: {missing_titles}")
else:
    print("✅ すべてのタイトルがTAGSテーブルに存在します。")

# タイトルからtag_idへのマッピングをDataFrameで作成
title_tag_id_df = tags_db.rename({'source_tag': 'title'})

# 2. 翻訳の検証
# 'other_names'を展開して、翻訳ごとに一行にする
df_translations = df.explode('other_names').select(['title', 'other_names'])

# タイトルをtag_idにマッピング（joinを使用）
df_translations = df_translations.join(title_tag_id_df.select(['title', 'tag_id']), on='title', how='left')

# 期待される翻訳のDataFrameを作成
expected_translations = df_translations.select(['tag_id', 'other_names']).rename({'other_names': 'translation'})

# データベースから翻訳をフィルタリング（言語が日本語のもの）
translations_db_jp = translations_db.filter(pl.col('language') == 'japanese').select(['tag_id', 'translation'])

# 欠けている翻訳を見つける
missing_translations = expected_translations.join(translations_db_jp, on=['tag_id', 'translation'], how='anti')

if len(missing_translations) > 0:
    print("❌ TAG_TRANSLATIONSテーブルに以下の翻訳が存在しません:")
    print(missing_translations)
else:
    print("✅ すべての翻訳がTAG_TRANSLATIONSテーブルに正しく登録されています。")

# 3. タグステータスの検証
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
expected_statuses = df.select(['title', 'type']).unique()

# タイトルをtag_idにマッピング（joinを使用）
expected_statuses = expected_statuses.join(title_tag_id_df.select(['title', 'tag_id']), on='title', how='left')

# タイプをtype_idにマッピング（joinを使用）
expected_statuses = expected_statuses.join(type_id_df, on='type', how='left')

# format_id列を追加し、データ型をi64に統一
expected_statuses = expected_statuses.with_columns(
    pl.lit(1, dtype=pl.Int64).alias('format_id')
)

# 必要な列を選択
expected_statuses = expected_statuses.select(['tag_id', 'format_id', 'type_id'])

# データベースから実際のタグステータスを取得し、format_idのデータ型をi64に統一
actual_statuses = status_db.with_columns(
    pl.col('format_id').cast(pl.Int64)
).select(['tag_id', 'format_id', 'type_id'])

# 欠けているまたは不正なタグステータスを見つける
missing_statuses = expected_statuses.join(actual_statuses, on=['tag_id', 'format_id', 'type_id'], how='anti')

if len(missing_statuses) > 0:
    print("❌ TAG_STATUSテーブルに以下のタグステータスが存在しません、または不正です:")
    print(missing_statuses)
else:
    print("✅ すべてのタグステータスがTAG_STATUSテーブルに正しく登録されています。")
