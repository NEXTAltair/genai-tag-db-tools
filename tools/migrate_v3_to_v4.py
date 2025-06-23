import logging
import sqlite3
from datetime import datetime
from pathlib import Path


def migrate_data(src_db: Path, dst_db: Path):
    """V3からV4へデータを移行"""
    logging.info(f"Migrating data from {src_db} to {dst_db}")
    src_conn = sqlite3.connect(src_db)
    dst_conn = sqlite3.connect(dst_db)

    try:
        # マスターデータを持つテーブルは既存データを確認
        merge_master_data(src_conn, dst_conn, "TAG_FORMATS")
        merge_master_data(src_conn, dst_conn, "TAG_TYPE_NAME")
        merge_master_data(src_conn, dst_conn, "TAG_TYPE_FORMAT_MAPPING")

        # その他のテーブルは単純コピー
        migrate_table(src_conn, dst_conn, "TAGS")
        migrate_tag_status(src_conn, dst_conn)  # TAG_STATUSは特別処理
        migrate_table(src_conn, dst_conn, "TAG_TRANSLATIONS")
        migrate_table(src_conn, dst_conn, "TAG_USAGE_COUNTS")

        # 移行が完了したらコミット
        dst_conn.commit()
        logging.info("Migration completed successfully")

        # データ件数の確認
        verify_migration(src_conn, dst_conn)

    except Exception as e:
        dst_conn.rollback()
        logging.error(f"Migration failed: {e!s}")
        raise
    finally:
        src_conn.close()
        dst_conn.close()


def fix_tag_status_data(rows):
    """TAG_STATUSのデータを制約に合うように修正"""
    fixed_rows = []
    issues = []

    for row in rows:
        tag_id, format_id, type_id, alias, preferred_tag_id = row[:5]  # 最初の5カラムを取得

        # エイリアスフラグがNULLの場合はFalseとして扱う
        alias = bool(alias) if alias is not None else False

        # preferred_tag_idがNULLの場合は自分自身のIDを設定
        if preferred_tag_id is None:
            preferred_tag_id = tag_id

        # 制約条件に基づいてデータを修正
        if not alias and preferred_tag_id != tag_id:
            # エイリアスでないのに preferred_tag_id が異なる場合
            issues.append(f"Non-alias tag {tag_id} had different preferred_tag {preferred_tag_id}")
            preferred_tag_id = tag_id
        elif alias and preferred_tag_id == tag_id:
            # エイリアスなのに preferred_tag_id が同じ場合
            issues.append(f"Alias tag {tag_id} had same preferred_tag")
            alias = False

        # 修正したデータを追加
        fixed_row = list(row)
        fixed_row[3] = int(alias)  # SQLiteのboolean型は0/1
        fixed_row[4] = preferred_tag_id
        fixed_rows.append(tuple(fixed_row))

    # 問題があった場合はログに出力
    if issues:
        logging.warning(f"Fixed {len(issues)} issues in TAG_STATUS data:")
        for issue in issues:
            logging.warning(f"  - {issue}")

    return fixed_rows


def migrate_tag_status(src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection):
    """TAG_STATUSテーブルの特別な移行処理"""
    logging.info("Migrating TAG_STATUS table with data validation")

    src_cursor = src_conn.cursor()
    dst_cursor = dst_conn.cursor()

    # カラム情報の取得
    src_cursor.execute("PRAGMA table_info(TAG_STATUS)")
    src_columns = [col[1] for col in src_cursor.fetchall()]

    dst_cursor.execute("PRAGMA table_info(TAG_STATUS)")
    dst_columns = [col[1] for col in dst_cursor.fetchall()]

    # 共通するカラムのみを使用
    common_columns = [col for col in src_columns if col in dst_columns]

    # データを取得
    select_cols = ", ".join(common_columns)
    src_cursor.execute(f"SELECT {select_cols} FROM TAG_STATUS")
    rows = src_cursor.fetchall()

    if not rows:
        logging.warning("No data found in source TAG_STATUS table")
        return

    # データの修正
    fixed_rows = fix_tag_status_data(rows)

    # 既存データをクリア
    dst_cursor.execute("DELETE FROM TAG_STATUS")

    # 修正したデータを挿入
    placeholders = ",".join(["?" for _ in common_columns])
    insert_sql = f"INSERT INTO TAG_STATUS ({select_cols}) VALUES ({placeholders})"

    try:
        dst_cursor.executemany(insert_sql, fixed_rows)
        logging.info(f"Migrated {len(fixed_rows)} rows for TAG_STATUS")
    except sqlite3.Error as e:
        logging.error(f"Error migrating TAG_STATUS: {e!s}")
        raise


def merge_master_data(src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection, table_name: str):
    """マスターデータの統合(既存データを保持しつつ新規データを追加)"""
    logging.info(f"Merging master data for table: {table_name}")

    src_cursor = src_conn.cursor()
    dst_cursor = dst_conn.cursor()

    # カラム情報の取得
    src_cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in src_cursor.fetchall()]

    # 既存データのIDを取得
    if "format_id" in columns:
        id_column = "format_id"
    elif "type_name_id" in columns:
        id_column = "type_name_id"
    else:
        id_column = columns[0]  # 最初のカラムをIDとして扱う

    dst_cursor.execute(f"SELECT {id_column} FROM {table_name}")
    existing_ids = {row[0] for row in dst_cursor.fetchall()}

    # 移行元のデータを取得
    src_cursor.execute(f"SELECT * FROM {table_name}")
    rows = src_cursor.fetchall()

    # 新規データのみを抽出
    new_rows = [row for row in rows if row[0] not in existing_ids]

    if new_rows:
        # データ挿入
        placeholders = ",".join(["?" for _ in columns])
        insert_sql = f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})"
        dst_cursor.executemany(insert_sql, new_rows)
        logging.info(f"Added {len(new_rows)} new rows to {table_name}")
    else:
        logging.info(f"No new data to add for {table_name}")


def migrate_table(src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection, table_name: str):
    """通常テーブルのデータを移行"""
    logging.info(f"Migrating table: {table_name}")

    # カラム情報の取得
    src_cursor = src_conn.cursor()
    src_cursor.execute(f"PRAGMA table_info({table_name})")
    src_columns = [col[1] for col in src_cursor.fetchall()]

    dst_cursor = dst_conn.cursor()
    dst_cursor.execute(f"PRAGMA table_info({table_name})")
    dst_columns = [col[1] for col in dst_cursor.fetchall()]

    # 共通するカラムのみを使用
    common_columns = [col for col in src_columns if col in dst_columns]

    # 既存データをクリア
    dst_cursor.execute(f"DELETE FROM {table_name}")

    # データ取得と挿入
    select_cols = ", ".join(common_columns)
    src_cursor.execute(f"SELECT {select_cols} FROM {table_name}")
    rows = src_cursor.fetchall()

    if not rows:
        logging.warning(f"No data found in source table: {table_name}")
        return

    # データ挿入
    placeholders = ",".join(["?" for _ in common_columns])
    insert_sql = f"INSERT INTO {table_name} ({select_cols}) VALUES ({placeholders})"
    dst_cursor.executemany(insert_sql, rows)
    logging.info(f"Migrated {len(rows)} rows for table: {table_name}")


def verify_migration(src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection):
    """移行結果の検証"""
    src_cursor = src_conn.cursor()
    dst_cursor = dst_conn.cursor()

    # 全テーブルの件数を比較
    src_cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name NOT LIKE 'sqlite_%'
        AND name NOT LIKE '%BACKUP%'
    """)
    tables = [row[0] for row in src_cursor.fetchall()]

    all_matched = True
    for table in tables:
        src_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        src_count = src_cursor.fetchone()[0]

        dst_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        dst_count = dst_cursor.fetchone()[0]

        # マスターテーブルは件数が異なる可能性があるため警告レベルを調整
        if table in ["TAG_FORMATS", "TAG_TYPE_NAME", "TAG_TYPE_FORMAT_MAPPING"]:
            if src_count > dst_count:
                logging.warning(
                    f"Master table {table} has fewer records in destination: "
                    f"source={src_count}, destination={dst_count}"
                )
                all_matched = False
        else:
            if src_count != dst_count:
                logging.error(
                    f"Count mismatch for table {table}: source={src_count}, destination={dst_count}"
                )
                all_matched = False
            else:
                logging.info(f"Table {table}: {src_count} rows migrated successfully")

    if all_matched:
        logging.info("All tables migrated successfully")
    else:
        logging.warning("Some tables have count mismatches, please verify the data")


def main():
    # ロギングの設定
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # データベースのパスを設定
    data_dir = Path(__file__).resolve().parent.parent / "genai_tag_db_tools" / "data"
    src_db = data_dir / "tags_v3.db"
    dst_db = data_dir / "tags_v4.db"

    if not src_db.exists():
        logging.error(f"Source database not found: {src_db}")
        return

    if not dst_db.exists():
        logging.error(f"Destination database not found: {dst_db}")
        logging.info("Please run alembic upgrade first to create the schema")
        return

    # バックアップの作成
    backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_backup = dst_db.with_name(f"tags_v4_{backup_time}.db")
    if dst_db.exists():
        import shutil

        shutil.copy2(dst_db, dst_backup)
        logging.info(f"Created backup at: {dst_backup}")

    # データ移行の実行
    try:
        migrate_data(src_db, dst_db)
    except Exception as e:
        logging.error(f"Migration failed: {e!s}")
        logging.info(f"Backup available at: {dst_backup}")
        raise


if __name__ == "__main__":
    main()
