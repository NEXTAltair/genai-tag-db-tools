
import sqlite3
from pathlib import Path

def test_data_integrity(db_path: Path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("データ整合性テストを開始します...")

    # テスト1: すべてのTAG_STATUSエントリがTAGSテーブルに対応するエントリを持っているか
    cursor.execute('''
    SELECT COUNT(*) 
    FROM TAG_STATUS ts
    LEFT JOIN TAGS t ON ts.tag_id = t.tag_id
    WHERE t.tag_id IS NULL
    ''')
    orphaned_tag_status = cursor.fetchone()[0]
    print(f"1. TAGSテーブルに対応するエントリがないTAG_STATUSエントリ: {orphaned_tag_status}")

    # テスト2: すべてのエイリアスが有効なpreferred_tag_idを持っているか
    cursor.execute('''
    SELECT COUNT(*) 
    FROM TAG_STATUS ts
    LEFT JOIN TAGS t ON ts.preferred_tag_id = t.tag_id
    WHERE ts.alias = 1 AND t.tag_id IS NULL
    ''')
    invalid_aliases = cursor.fetchone()[0]
    print(f"2. 無効なpreferred_tag_idを持つエイリアス: {invalid_aliases}")

    # テスト3: すべての翻訳が有効なtag_idを持っているか
    cursor.execute('''
    SELECT COUNT(*) 
    FROM TAG_TRANSLATIONS tt
    LEFT JOIN TAGS t ON tt.tag_id = t.tag_id
    WHERE t.tag_id IS NULL
    ''')
    orphaned_translations = cursor.fetchone()[0]
    print(f"3. TAGSテーブルに対応するエントリがない翻訳: {orphaned_translations}")

    # テスト4: すべての使用回数が有効なtag_idを持っているか
    cursor.execute('''
    SELECT COUNT(*) 
    FROM TAG_USAGE_COUNTS tuc
    LEFT JOIN TAGS t ON tuc.tag_id = t.tag_id
    WHERE t.tag_id IS NULL
    ''')
    orphaned_usage_counts = cursor.fetchone()[0]
    print(f"4. TAGSテーブルに対応するエントリがない使用回数: {orphaned_usage_counts}")

    # テスト5: エイリアスでないタグのpreferred_tag_idが自身を指しているか
    cursor.execute('''
    SELECT COUNT(*) 
    FROM TAG_STATUS
    WHERE alias = 0 AND tag_id != preferred_tag_id
    ''')
    inconsistent_non_aliases = cursor.fetchone()[0]
    print(f"5. 自身を指していないpreferred_tag_idを持つ非エイリアスタグ: {inconsistent_non_aliases}")

    # テスト6: 同じ tag_id と format_id に対して、異なる preferred_tag_id が設定されているレコードを検出
    cursor.execute('''
    SELECT tag_id, format_id, COUNT(DISTINCT preferred_tag_id) AS distinct_preferred_tags, GROUP_CONCAT(DISTINCT preferred_tag_id) AS preferred_tag_ids
    FROM TAG_STATUS
    WHERE alias = 1
    GROUP BY tag_id, format_id
    HAVING COUNT(DISTINCT preferred_tag_id) > 1
    ''')
    inconsistent_alias_groups = cursor.fetchall()
    print(f"6. tag_idとformat_idが同一で別のpreferred_tag_idを示す数: {len(inconsistent_alias_groups)}")

    if inconsistent_alias_groups:
        print("\n詳細:")
        for group in inconsistent_alias_groups:
            format_id, type_id, distinct_count, preferred_tag_ids = group
            print(f"format_id: {format_id}, type_id: {type_id}")
            print(f"異なるpreferred_tag_idの数: {distinct_count}")
            print(f"preferred_tag_ids: {preferred_tag_ids}")
            
            # 各preferred_tag_idに対応するタグ情報を取得
            cursor.execute('''
            SELECT t.tag_id, t.source_tag, t.tag
            FROM TAGS t
            WHERE t.tag_id IN ({})
            '''.format(preferred_tag_ids))
            tags = cursor.fetchall()
            print("対応するタグ:")
            for tag in tags:
                print(f"tag_id: {tag[0]}, source_tag: {tag[1]}, normalized_tag: {tag[2]}")
            print()

    conn.close()

    print("データ整合性テストが完了しました。")

def analyze_format_id_0_tags(db_path: Path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("format_id 0 のタグ分析を開始します...")

    # 1. format_id 0 のタグの総数を取得
    cursor.execute('SELECT COUNT(*) FROM TAG_STATUS WHERE format_id = 0')
    total_format_0_tags = cursor.fetchone()[0]
    print(f"format_id 0 のタグの総数: {total_format_0_tags}")

    # 2. format_id 0 のタグの type_id 分布を取得
    cursor.execute('''
    SELECT type_id, COUNT(*) 
    FROM TAG_STATUS 
    WHERE format_id = 0 
    GROUP BY type_id
    ''')
    type_id_distribution = cursor.fetchall()
    print("\nformat_id 0 のタグの type_id 分布:")
    for type_id, count in type_id_distribution:
        print(f"  type_id {type_id}: {count} タグ")

    # 3. 問題のあるグループの詳細な情報を取得
    cursor.execute('''
    SELECT ts.type_id, ts.preferred_tag_id, t.source_tag, t.tag, COUNT(*) as alias_count
    FROM TAG_STATUS ts
    JOIN TAGS t ON ts.preferred_tag_id = t.tag_id
    WHERE ts.format_id = 0 AND ts.alias = 1
    GROUP BY ts.type_id, ts.preferred_tag_id
    HAVING COUNT(DISTINCT ts.preferred_tag_id) > 1
    ORDER BY alias_count DESC
    LIMIT 10
    ''')
    problematic_groups = cursor.fetchall()

    print("\n問題のあるグループのトップ10:")
    for group in problematic_groups:
        type_id, preferred_tag_id, source_tag, tag, alias_count = group
        print(f"  type_id: {type_id}, preferred_tag_id: {preferred_tag_id}")
        print(f"    source_tag: {source_tag}")
        print(f"    tag: {tag}")
        print(f"    エイリアス数: {alias_count}")

    # 4. format_id 0 のタグの使用回数上位10件を取得
    cursor.execute('''
    SELECT t.tag_id, t.source_tag, t.tag, tuc.count
    FROM TAG_USAGE_COUNTS tuc
    JOIN TAGS t ON tuc.tag_id = t.tag_id
    WHERE tuc.format_id = 0
    ORDER BY tuc.count DESC
    LIMIT 10
    ''')
    top_used_tags = cursor.fetchall()

    print("\nformat_id 0 のタグの使用回数上位10件:")
    for tag in top_used_tags:
        tag_id, source_tag, tag, count = tag
        print(f"  tag_id: {tag_id}, source_tag: {source_tag}, tag: {tag}, 使用回数: {count}")

    conn.close()

    print("\n分析が完了しました。")
if __name__ == "__main__":
    db_path = Path(__file__).parent / "tags_v3.db"
    test_data_integrity(db_path)
    analyze_format_id_0_tags(db_path)