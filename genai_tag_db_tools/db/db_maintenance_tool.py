from pathlib import Path
import sqlite3


class DatabaseMaintenanceTool:
    def __init__(self, db_path):
        db_path = Path(__file__).resolve().parent.parent / "data" / db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

    def detect_duplicates_in_tag_status(self):
        """TAG_STATUSテーブルの重複レコードを検出し、詳細情報を返す
        NULLのpreferred_tag_idは異常ではないため、そのままJOINします。
        Returns:
            list[dict[str, Any]]: 重複レコードのリスト（関連するタグ、フォーマット、タイプ、およびpreferred_tag情報を含む）
        """
        query = """
        SELECT ts.tag_id, t.tag, ts.format_id, f.format_name, ts.type_id, ttn.type_name, ts.alias, ts.preferred_tag_id, pt.tag AS preferred_tag, COUNT(*) as count
        FROM TAG_STATUS ts
        LEFT JOIN TAGS t ON ts.tag_id = t.tag_id
        LEFT JOIN TAG_FORMATS f ON ts.format_id = f.format_id
        LEFT JOIN TAG_TYPE_FORMAT_MAPPING ttfm ON ts.type_id = ttfm.type_id AND ts.format_id = ttfm.format_id
        LEFT JOIN TAG_TYPE_NAME ttn ON ttfm.type_name_id = ttn.type_name_id
        LEFT JOIN TAGS pt ON ts.preferred_tag_id = pt.tag_id
        GROUP BY ts.tag_id, ts.format_id, ts.type_id
        HAVING count > 1
        """
        duplicate_records = self.cursor.execute(query).fetchall()
        return [
            {
                "tag": row[1],
                "format": row[3],
                "type": row[5],
                "alias": bool(row[6]),
                "preferred_tag": row[8],
            }
            for row in duplicate_records
        ]

    def detect_usage_counts_for_tags(self):
        """TAG_USAGE_COUNTSの使用回数を検出し、各タグの使用頻度を返す
        Returns:
            list[dict[str, Any]]: タグとその使用回数のリスト
        """
        query = """
        SELECT t.tag, f.format_name, tc.count, COUNT(*) as use_count
        FROM TAG_USAGE_COUNTS tc
        LEFT JOIN TAGS t ON tc.tag_id = t.tag_id
        LEFT JOIN TAG_FORMATS f ON tc.format_id = f.format_id
        GROUP BY tc.tag_id, tc.format_id
        HAVING use_count > 1
        """
        usage_counts = self.cursor.execute(query).fetchall()
        return [
            {"tag": row[0], "format_name": row[1], "use_count": row[2]}
            for row in usage_counts
        ]

    def detect_foreign_key_issues(self):
        # 外部キーの整合性をチェック
        query = """
        SELECT TS.tag_id, T.source_tag FROM TAG_STATUS AS TS
        LEFT JOIN TAGS AS T ON TS.tag_id = T.tag_id
        WHERE T.tag_id IS NULL
        """
        missing_tags = self.cursor.execute(query).fetchall()
        return missing_tags

    def detect_orphan_records(self):
        # 孤立したレコードを検出
        query = """
        SELECT tag_id FROM TAG_TRANSLATIONS
        WHERE tag_id NOT IN (SELECT tag_id FROM TAGS)
        """
        orphan_records = self.cursor.execute(query).fetchall()
        return orphan_records

    def optimize_indexes(self):
        # インデックスの再構築や最適化を行う
        self.cursor.execute("REINDEX")
        self.conn.commit()
        print("インデックスの再構築を行いました")

    def detect_invalid_tag_id(self):
        """invalid_tagのタグIDを取得
        Returns:
            int: invalid_tagのタグIDのリスト
        """
        query = """
        SELECT tag_id FROM TAGS WHERE tag = 'invalid tag' OR source_tag = 'invalid_tag'
        """
        invalid_tags = self.cursor.execute(query).fetchone()
        return invalid_tags[0]

    def detect_invalid_preferred_tags(self, invalid_tag_id):
        """invalid tagのタグIDをpreferred_tagに記録したレコードを検出
        Args:
            invalid_tag_id (int): invalid tagのタグID
        Returns:
            list[tuple[int, str]]: invalid tagをpreferred_tagに設定しているレコードのリスト
        """
        query = """
        SELECT ts.tag_id, t.tag
        FROM TAG_STATUS ts
        LEFT JOIN TAGS t ON ts.tag_id = t.tag_id
        WHERE ts.preferred_tag_id = ?
        """
        invalid_preferred_tags = self.cursor.execute(
            query, (invalid_tag_id,)
        ).fetchall()
        return invalid_preferred_tags

    def close(self):
        self.conn.close()


# 使用例
if __name__ == "__main__":
    db_tool = DatabaseMaintenanceTool("tags_v3.db")

    duplicates_status = db_tool.detect_duplicates_in_tag_status()
    if duplicates_status:
        print(f"重複レコードが検出されました: {duplicates_status}")
        for duplicate in duplicates_status:
            print(f"重複レコード: {duplicate}")

    duplicates_counts = db_tool.detect_usage_counts_for_tags()
    if duplicates_counts:
        print(f"重複レコードが検出されました: {duplicates_counts}")
        for duplicate in duplicates_counts:
            print(f"重複レコード: {duplicate}")

    # 外部キーの不整合の検出と修正
    missing_keys = db_tool.detect_foreign_key_issues()
    if missing_keys:
        print(f"外部キーの不整合が検出されました: {missing_keys}")
        # 必要に応じて修正
        # db_tool.fix_foreign_key_issues(missing_keys)

    # 孤立レコードの検出と修正
    orphan_records = db_tool.detect_orphan_records()
    if orphan_records:
        print(f"孤立レコードが検出されました: {orphan_records}")
        # 必要に応じて修正
        # db_tool.fix_orphan_records(orphan_records)

    # invalid tag の検出
    invalid_tag = db_tool.detect_invalid_tag_id()

    # invalid tag をpreferred_tagに設定しているレコードの検出
    invalid_preferred_tags = db_tool.detect_invalid_preferred_tags(invalid_tag)
    print(f"invalid tagをpreferred_tagに設定しているレコード: {invalid_preferred_tags}")

    db_tool.optimize_indexes()
    db_tool.close()
