from pathlib import Path

# グローバル変数として db_path を定義
db_path = Path("genai_tag_db_tools/data/tags_v3.db")

# このデータベースで扱えるデータラベル
AVAILABLE_COLUMNS = [
    "source_tag",
    "tag",
    "type_id",
    "count",
    "language",
    "translation",
    "deprecated_tags",
    "created_at",
    "updated_at",
]
