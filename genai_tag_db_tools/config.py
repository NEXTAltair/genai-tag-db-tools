from pathlib import Path

# グローバル変数として db_path を定義
db_path = Path("genai_tag_db_tools/data/tags_v3.db")

# このデータベースで扱えるデータラベルとそのデータ型
AVAILABLE_COLUMNS = {
    "source_tag": "Utf8",
    "tag": "Utf8",
    "type": "Utf8",
    "type_id": "Int32",
    "count": "Int32",
    "language": "Utf8",
    "translation": "List",
    "deprecated_tags": "List",
    "created_at": "Utf8",
    "updated_at": "Utf8",
}
