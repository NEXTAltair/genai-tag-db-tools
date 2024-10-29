import polars as pl
import sqlite3
import logging
from genai_tag_db_tools.core.processor import CSVToDatabaseProcessor

class DanbooruJaTagBatch:
    def __init__(self, df: pl.DataFrame):
        self.conn = sqlite3.connect('tags_v3.db')
        self.df = df
        self.logger = logging.getLogger(__name__)
        self.existing_tags = self.get_existing_tags()

    def get_existing_tags(self):
        """TAGSテーブルから既存のタグを取得し辞書化"""
        query = "SELECT tag_id, source_tag FROM TAGS"
        existing_tags = pl.read_database(query, self.conn)
        return {row['source_tag']: row['tag_id'] for row in existing_tags.iter_rows(named=True)}

    def insert_new_tags(self, new_tags):
        """新しいタグを一括挿入"""
        normalized_tags = [(tag, CSVToDatabaseProcessor.normalize_tag(tag)) for tag in new_tags]
        query = "INSERT INTO TAGS (source_tag, tag) VALUES (?, ?)"
        cursor = self.conn.cursor()
        cursor.executemany(query, normalized_tags)
        self.conn.commit()

        # 新しく挿入したタグIDを取得
        return self.get_existing_tags()

    def insert_translations(self, translations):
        """翻訳を一括挿入"""
        query = "INSERT OR IGNORE INTO TAG_TRANSLATIONS (tag_id, language, translation) VALUES (?, 'japanese', ?)"
        cursor = self.conn.cursor()
        cursor.executemany(query, translations)
        self.conn.commit()

    def insert_tag_statuses(self, statuses):
        """タグステータスを一括挿入または更新"""
        query = """
        INSERT INTO TAG_STATUS (tag_id, format_id, type_id)
        VALUES (?, 1, ?)
        ON CONFLICT(tag_id, format_id) DO UPDATE SET type_id = excluded.type_id
        """
        cursor = self.conn.cursor()
        cursor.executemany(query, statuses)
        self.conn.commit()

    def process_tags(self):
        # 新規タグと既存タグを区別
        new_tags = [row['title'] for row in self.df.iter_rows(named=True) if row['title'] not in self.existing_tags]
        if new_tags:
            self.existing_tags.update(self.insert_new_tags(new_tags))

        # 翻訳とタグステータスを準備
        translations = []
        statuses = []
        type_id_map = {
            'general': 0,
            'artist': 1,
            'copyright': 3,
            'character': 4,
            'meta': 5,
        }

        for row in self.df.iter_rows(named=True):
            tag_id = self.existing_tags[row['title']]
            translations.extend((tag_id, name) for name in row['other_names'])

            type_id = type_id_map.get(row['type'])
            if type_id is not None:
                statuses.append((tag_id, type_id))

        # 一括挿入
        self.insert_translations(translations)
        self.insert_tag_statuses(statuses)

        self.logger.info("Tag processing completed successfully.")

    def close(self):
        self.conn.close()

if __name__ == '__main__':
    df = pl.read_parquet('hf://datasets/p1atdev/danbooru-ja-tag-pair-20241015/data/train-00000-of-00001.parquet')
    djt = DanbooruJaTagBatch(df)
    djt.process_tags()
    djt.close()
