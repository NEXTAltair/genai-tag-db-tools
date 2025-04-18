import polars as pl

# 読み込まれたタグのデータ表はここに定義されたデータ型に従って変換される
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
    "TAGS": pl.DataFrame(
        {
            "tag_id": pl.UInt32,
            "source_tag": pl.Utf8,
            "tag": pl.Utf8
        }
    ),
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
        {"type_name_id": pl.UInt32, "type_name": pl.Utf8, "description": pl.Utf8}
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
