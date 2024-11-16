from pathlib import Path
import polars as pl

# グローバル変数として db_path を定義
db_path = Path("genai_tag_db_tools/data/tags_v3.db")

# このデータベースで扱えるデータラベルとそのデータ型
AVAILABLE_COLUMNS = {
    "source_tag": pl.Utf8,
    "tag": pl.Utf8,
    "type": pl.Utf8,
    "type_id": pl.UInt32,
    "count": pl.UInt32,
    "language": pl.Utf8,
    "translation": pl.List(pl.Utf8),
    "deprecated_tags": pl.List(pl.Utf8),
    "created_at": pl.Datetime,
    "updated_at": pl.Datetime,
}
