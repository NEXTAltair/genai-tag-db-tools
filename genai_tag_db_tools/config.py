from pathlib import Path
import polars as pl
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# グローバル変数として db_path を定義
db_path = Path("genai_tag_db_tools/data/tags_v4.db")

#
engine = create_engine(
    f"sqlite:///{db_path.absolute()}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=True
)

# このデータベースで扱えるデータラベルとそのデータ型
AVAILABLE_COLUMNS = {
    "source_tag": pl.Utf8,
    "tag_id": pl.UInt32,
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

EMPTY_DF = pl.DataFrame(
    {col: pl.Series(col, [], dtype=dtype) for col, dtype in AVAILABLE_COLUMNS.items()}
)

DF_SCHEMA = {
    "TAGS": pl.DataFrame({"tag_id": pl.UInt32, "source_tag": pl.Utf8, "tag": pl.Utf8}),
    "TAG_TRANSLATIONS": pl.DataFrame(
        {
            "translation_id": pl.UInt32,
            "tag_id": pl.UInt32,
            "language": pl.Utf8,
            "translation": pl.Utf8,
            "created_at": pl.Datetime,
            "updated_at": pl.Datetime,
        }
    ),
    "TAG_FORMATS": pl.DataFrame(
        {
            "format_id": pl.UInt32,
            "format_name": pl.Utf8,
            "description": pl.Utf8
        }
    ),
    "TAG_TYPE_NAME": pl.DataFrame(
        {
            "type_name_id": pl.UInt32,
            "type_name": pl.Utf8,
            "description": pl.Utf8
        }
    ),
    "TAG_TYPE_FORMAT_MAPPING": pl.DataFrame(
        {
            "format_id": pl.UInt32,
            "type_id": pl.UInt32,
            "type_name_id": pl.UInt32,
            "description": pl.Utf8,
        }
    ),
    "TAG_USAGE_COUNTS": pl.DataFrame(
        {
            "tag_id": pl.UInt32,
            "format_id": pl.UInt32,
            "count": pl.UInt32,
            "updated_at": pl.Datetime,
        }
    ),
    "TAG_STATUS": pl.DataFrame(
        {
            "tag_id": pl.UInt32,
            "format_id": pl.UInt32,
            "type_id": pl.UInt32,
            "alias": pl.Boolean,
            "preferred_tag_id": pl.UInt32,
            "created_at": pl.Datetime,
            "updated_at": pl.Datetime,
        }
    ),
}
