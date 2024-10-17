import polars as pl
import sqlite3
import time
import logging
from CSVToDatabaseProcessor import CSVToDatabaseProcessor

class DanbooruJaTag:
    def __init__(self, df: pl.DataFrame):
        self.conn = sqlite3.connect('tags_v4.db')
        self.df = df
        self.total_rows = len(self.df)
        self.records_per_percent = 1500  # 1%の増加に必要なレコード数
        self.logger = logging.getLogger(__name__)
        self.existing_tags = self.get_existing_tags()

    def get_existing_tags(self):
        """tags_v4.dbの TAGSからsource_tagとtag_idを取得"""
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

    def insert_translation(self, tag_id: int, translation: str):
        """TAG_TRANSLATIONSにレコードを追加（重複を無視し、ログに記録）
        Args:
            tag_id (int): タグのID
            translation (str): 翻訳文字列
        """
        query = "INSERT OR IGNORE INTO TAG_TRANSLATIONS (tag_id, language, translation) VALUES (?, ?, ?)"
        cursor = self.conn.cursor()
        cursor.execute(query, (tag_id, 'japanese', translation))

        # 重複をチェックし、ログに記録
        if cursor.rowcount == 0:
            self.logger.info(f"重複検出: tag_id={tag_id}, language=japanese, translation='{translation}'")
        else:
            self.logger.debug(f"翻訳追加: tag_id={tag_id}, language=japanese, translation='{translation}'")

        self.conn.commit()

    def insert_tag_status(self, tag_id: int, type_name: str):
        """TAG_STATUSにレコードを追加または更新
        タイプ分類はdanbooru-ja-tag-pairのほうが正確そうなので優先される
        Args:
            tag_id (int): タグのID
            type_name (str): タグのタイプ名
        """
        query = """
        INSERT INTO TAG_STATUS (tag_id, format_id, type_id)
        VALUES (?, ?, ?)
        ON CONFLICT(tag_id, format_id) DO UPDATE SET
        type_id = excluded.type_id
        """
        type_id_map = {
            'general': 0,
            'artist': 1,
            'copyright': 3,
            'character': 4,
            'meta': 5,
        }
        try:
            type_id = type_id_map[type_name]
            cursor = self.conn.cursor()
            cursor.execute(query, (tag_id, 1, type_id))  # format_id is 1 for Danbooru
            if cursor.rowcount == 0:
                self.logger.info(f"Tag status already exists for tag_id {tag_id}, format_id 1. Updated type_id to {type_id}.")
            else:
                self.logger.debug(f"Inserted new tag status for tag_id {tag_id}, format_id 1, type_id {type_id}.")
            self.conn.commit()
        except KeyError:
            self.logger.error(f"Unknown type '{type_name}' for tag_id {tag_id}")
        except Exception as e:
            self.logger.error(f"Error inserting/updating tag status for tag_id {tag_id}: {e}")
            self.conn.rollback()

    def process_tags(self):
        try:
            start_time = time.time()
            last_progress = 0
            for index, row in enumerate(self.df.iter_rows(named=True), 1):
                title = row['title']
                existing_tag = self.existing_tags.filter(pl.col('source_tag') == title)

                if existing_tag.is_empty():
                    # 新しいタグを追加
                    tag_id = self.insert_new_tag(title)
                    # 新しく追加したタグを existing_tags に追加
                    self.existing_tags = self.existing_tags.vstack(pl.DataFrame({'tag_id': [tag_id], 'source_tag': [title]}))
                else:
                    tag_id = existing_tag['tag_id'][0]

                # 翻訳を追加
                for translation in row['other_names']:
                    self.insert_translation(tag_id, translation)

                # タグステータスを追加
                self.insert_tag_status(tag_id, row['type'])

                # 進捗状況の表示
                current_progress = (index // self.records_per_percent)
                if current_progress > last_progress or index == self.total_rows:
                    progress = (index / self.total_rows) * 100
                    elapsed_time = time.time() - start_time
                    estimated_total_time = elapsed_time / (index / self.total_rows)
                    remaining_time = estimated_total_time - elapsed_time
                    print(f"進捗: {progress:.2f}% ({index}/{self.total_rows}) "
                          f"経過時間: {elapsed_time:.2f}秒 "
                          f"残り時間: {remaining_time:.2f}秒")
                    last_progress = current_progress

            self.conn.commit()
            self.logger.info("Tag processing completed successfully.")
        except Exception as e:
            self.conn.rollback()
            self.logger.error(f"Error during tag processing: {e}")
        finally:
            self.conn.close()

if __name__ == '__main__':
    # メイン処理
    danbooru_ja_tag = pl.read_parquet('hf://datasets/p1atdev/danbooru-ja-tag-pair-20241015/data/train-00000-of-00001.parquet')
    djt = DanbooruJaTag(danbooru_ja_tag)
    djt.process_tags()
