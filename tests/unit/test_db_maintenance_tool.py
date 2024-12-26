import sqlite3
import pytest
from genai_tag_db_tools.db.db_maintenance_tool import DatabaseMaintenanceTool


@pytest.fixture
def db_path(tmp_path):
    db_file = tmp_path / "test_tags.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create necessary tables
    cursor.execute("""
    CREATE TABLE TAGS (
        tag_id INTEGER PRIMARY KEY,
        tag TEXT,
        source_tag TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE TAG_TRANSLATIONS (
        translation_id INTEGER PRIMARY KEY,
        tag_id INTEGER,
        language TEXT,
        translation TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE TAG_STATUS (
        tag_id INTEGER,
        format_id INTEGER,
        type_id INTEGER,
        alias INTEGER,
        preferred_tag_id INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE TAG_FORMATS (
        format_id INTEGER PRIMARY KEY,
        format_name TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE TAG_TYPE_NAME (
        type_name_id INTEGER PRIMARY KEY,
        type_name TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE TAG_TYPE_FORMAT_MAPPING (
        type_id INTEGER,
        format_id INTEGER,
        type_name_id INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE TAG_USAGE_COUNTS (
        tag_id INTEGER,
        format_id INTEGER,
        count INTEGER
    )
    """)

    conn.commit()
    conn.close()
    return str(db_file)


def test_detect_orphan_records(db_path):
    tool = DatabaseMaintenanceTool(db_path)

    # Insert orphan translation (tag_id does not exist in TAGS)
    tool.cursor.execute("""
    INSERT INTO TAG_TRANSLATIONS (translation_id, tag_id, language, translation)
    VALUES (1, 999, 'en', 'orphan_translation')
    """)
    tool.conn.commit()

    orphans = tool.detect_orphan_records()
    assert len(orphans) == 1
    assert orphans[0][0] == 999

    tool.close()


def test_detect_foreign_key_issues(db_path):
    tool = DatabaseMaintenanceTool(db_path)

    # Insert into TAG_STATUS with nonexistent tag_id
    tool.cursor.execute("""
    INSERT INTO TAG_STATUS (tag_id, format_id, type_id, alias, preferred_tag_id)
    VALUES (999, 1, 1, 0, NULL)
    """)
    tool.conn.commit()

    missing_keys = tool.detect_foreign_key_issues()
    assert len(missing_keys) == 1
    assert missing_keys[0][0] == 999

    tool.close()


def test_detect_usage_counts_for_tags(db_path):
    tool = DatabaseMaintenanceTool(db_path)

    # Insert duplicate usage counts
    tool.cursor.execute("INSERT INTO TAGS (tag_id, tag) VALUES (1, 'tag1')")
    tool.cursor.execute(
        "INSERT INTO TAG_FORMATS (format_id, format_name) VALUES (1, 'format1')"
    )
    tool.cursor.execute("""
    INSERT INTO TAG_USAGE_COUNTS (tag_id, format_id, count)
    VALUES (1, 1, 10), (1, 1, 10)
    """)
    tool.conn.commit()

    duplicates = tool.detect_usage_counts_for_tags()
    assert len(duplicates) == 1
    assert duplicates[0]["tag"] == "tag1"
    assert duplicates[0]["format_name"] == "format1"
    assert duplicates[0]["use_count"] == 10

    tool.close()


def test_optimize_indexes(db_path):
    tool = DatabaseMaintenanceTool(db_path)
    # Simply call the method to ensure no exceptions
    tool.optimize_indexes()
    tool.close()


def test_detect_invalid_tag_id(db_path):
    tool = DatabaseMaintenanceTool(db_path)
    # Insert invalid preferred_tag_id
    tool.cursor.execute("""
    INSERT INTO TAGS (tag_id, tag, source_tag) VALUES (1, 'invalid tag', 'invalid_tag')
    """)
    tool.conn.commit()

    invalid_tag_id = tool.detect_invalid_tag_id()
    assert invalid_tag_id == 1
