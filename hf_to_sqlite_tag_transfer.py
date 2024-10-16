import polars as pl
import sqlite3
import logging
from pathlib import Path
from CSVToDatabaseProcessor import CSVToDatabaseProcessor, normalize_tag


class danbooruJaTag:
    def __init__(self, df: pl.DataFrame):
        self.conn = sqlite3.connect('tags_v3.db')
        self.df = df
        self.logger = logging.getLogger(__name__)


    def get_existing_tags(self):
        """tags_v3 TAGSからsource_tagとtag_idを取得"""
        query = "SELECT tag_id, source_tag FROM TAGS"
        return pl.read_database(query, self.conn)

    def insert_new_tag(self, title):
        """TAGSに存在しないタグの場合、新しいレコードを追加
        Args:
            title (str): source_tag と同じもの
                        _ や () のエスケープがされてない状態

        Returns:
            int: tag_id
        """
        query = "INSERT INTO TAGS (source_tag, tag) VALUES (?, ?)"
        normalized_tag = CSVToDatabaseProcessor.normalize_tag(title)
        cursor = self.conn.cursor()
        cursor.execute(query, (title, normalized_tag))
        return cursor.lastrowid

    def insert_translation(self, tag_id, translation):
        """TAG_TRANSLATIONSにレコードを追加"""
        query = "INSERT INTO TAG_TRANSLATIONS (tag_id, language, translation) VALUES (?, ?, ?)"
        cursor = self.conn.cursor()
        cursor.execute(query, (tag_id, 'japanese', translation))

    def insert_tag_status(self, tag_id, type_name):
        """TAG_STATUSにレコードを追加"""
        query = "INSERT INTO TAG_STATUS (tag_id, format_id, type_id) VALUES (?, ?, ?)"
        type_id_map = {
            'general': 0,
            'artist': 1,
            'copyright': 3,
            'character': 4,
            'meta': 5,
        }
        try:
            type_id = type_id_map[{type_name}]
            cursor = self.conn.cursor()
            cursor.execute(query, (tag_id, 1, type_id))  # format_id is 1 for Danbooru
        except Exception as e:
            self.logger.error(f"Error inserting tag status for tag_id {tag_id}: {e}")

    def process_tags(self):
        conn = self.conn
        df = self.df
        existing_tags = self.get_existing_tags()

        for row in df.iter_rows(named=True):
            title = row['title']
            existing_tag = existing_tags.filter(pl.col('source_tag') == title)

            if existing_tag.is_empty():
                # 新しいタグを追加
                tag_id = self.insert_new_tag(title)
            else:
                tag_id = existing_tag['tag_id'][0]

            # 翻訳を追加
            for translation in row['other_names']:
                self.insert_translation(tag_id, translation)

            # タグステータスを追加
            self.insert_tag_status(tag_id, row['type'])

        conn.commit()

if __name__ == '__main__':
    # メイン処理
    danbooru_ja_tag = pl.read_parquet('hf://datasets/p1atdev/danbooru-ja-tag-pair-20241015/data/train-00000-of-00001.parquet')
    danbooruJaTag.process_tags(danbooru_ja_tag)
