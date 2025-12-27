from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, Field


class DbSourceRef(BaseModel):
    """HF配布SQLiteの参照情報。

    Args:
        repo_id: HFデータセットID（例: NEXTAltair/genai-image-tag-db-CC4）。
        filename: 取得対象のSQLiteファイル名。
        revision: ブランチ/タグ/コミット（未指定なら既定）。
    """

    repo_id: str = Field(..., examples=["NEXTAltair/genai-image-tag-db-CC4"])
    filename: str = Field(..., examples=["genai-image-tag-db-cc4.sqlite"])
    revision: str | None = Field(default=None, description="ブランチ/タグ/コミット(未指定なら既定)")


class DbCacheConfig(BaseModel):
    """DBキャッシュ設定。

    Args:
        cache_dir: ユーザーDB配置ディレクトリ（user_tags.sqlite保存先）
        token: HFアクセストークン（必要な場合のみ）

    Note:
        HF標準キャッシュの場所は HF_HOME 環境変数で制御されます。
        cache_dir はユーザーDBの保存先として使用されます。
    """

    cache_dir: str = Field(..., examples=["/path/to/user_db_dir"], description="ユーザーDB配置ディレクトリ")
    token: str | None = Field(default=None, description="HFアクセストークン")


class EnsureDbRequest(BaseModel):
    """DB準備リクエスト。

    Args:
        source: 取得元のHF参照。
        cache: 保存先/認証設定。
    """

    source: DbSourceRef
    cache: DbCacheConfig


class EnsureDbResult(BaseModel):
    """DB準備結果。

    Args:
        db_path: ローカルSQLiteの実体パス（HFキャッシュ内のsymlink）。
        sha256: 取得ファイルのSHA256。
        revision: 解決されたリビジョン（コミットハッシュ）。
        cached: オフラインモードでキャッシュを使用したか。

    Note:
        `downloaded` フィールドは削除されました。
        HF Hub は新規ダウンロード/キャッシュヒットの区別を提供しないため、
        このフラグを正確に判定できません。
    """

    db_path: str = Field(..., description="ローカルSQLiteの実体パス")
    sha256: str = Field(..., description="取得ファイルのSHA256")
    revision: str | None = Field(default=None, description="解決されたリビジョン")
    cached: bool = Field(default=False, description="キャッシュのみ使用したか")


class TagSearchRequest(BaseModel):
    """タグ検索リクエスト（外部向け）。

    Args:
        query: 検索クエリ。
        format_names: 対象フォーマット名の絞り込み。
        type_names: 対象タイプ名の絞り込み。
        resolve_preferred: 推奨タグへ正規化して返す。
        include_aliases: エイリアスを含める。
        include_deprecated: 非推奨タグを含める。
        limit: 取得件数。
        offset: 取得オフセット。
    """

    query: str = Field(..., description="Search query")
    format_names: list[str] | None = Field(default=None, description="Format name filters")
    type_names: list[str] | None = Field(default=None, description="Type name filters")
    resolve_preferred: bool = Field(default=True, description="Resolve to preferred tags")
    include_aliases: bool = Field(default=True, description="Include alias tags")
    include_deprecated: bool = Field(default=False, description="Include deprecated tags")
    min_usage: int | None = Field(default=None, description="Minimum usage count")
    max_usage: int | None = Field(default=None, description="Maximum usage count")


class TagIdRef(BaseModel):
    """整合性チェック用の内部参照。

    Args:
        tag_id: タグID。
        format_id: フォーマットID。
        type_id: タイプID。
        alias: エイリアスかどうか。
        preferred_tag_id: 推奨タグID。
    """

    tag_id: int = Field(..., description="タグID")
    format_id: int = Field(..., description="フォーマットID")
    type_id: int = Field(..., description="タイプID")
    alias: bool = Field(..., description="エイリアスかどうか")
    preferred_tag_id: int | None = Field(default=None, description="推奨タグID")


class TagRecordPublic(BaseModel):
    """検索結果の1行（外部向け / IDなし）。

    Args:
        tag: 表示用の正規タグ。
        source_tag: ソースタグ（あれば）。
        format_name: フォーマット名。
        type_name: タイプ名。
        alias: エイリアスかどうか。
    """

    tag: str = Field(..., description="表示用の正規タグ")
    source_tag: str | None = Field(default=None, description="ソースタグ")
    format_name: str | None = Field(default=None, description="フォーマット名")
    type_id: int | None = Field(default=None, description="タイプID")
    type_name: str | None = Field(default=None, description="タイプ名")
    alias: bool | None = Field(default=None, description="エイリアスかどうか")
    deprecated: bool | None = Field(default=None, description="非推奨かどうか")
    usage_count: int | None = Field(default=None, description="????")
    translations: dict[str, list[str]] | None = Field(default=None, description="言語別の翻訳一覧")
    format_statuses: dict[str, dict[str, object]] | None = Field(
        default=None, description="フォーマット別の状態一覧"
    )


class TagSearchResult(BaseModel):
    """検索結果のコンテナ。

    Args:
        items: 検索結果の一覧。
        total: 総件数（不明ならNone）。
    """

    items: list[TagRecordPublic] = Field(..., description="Search result rows")
    total: int | None = Field(default=None, description="Total count if known")


class TagSearchRow(TypedDict):
    """Internal repository row for tag search results.

    Keys:
        tag_id: Tag id.
        tag: Normalized tag string.
        source_tag: Source tag if present.
        usage_count: Usage count for the active format.
        alias: True if alias.
        deprecated: True if deprecated.
        type_id: Type id if known.
        type_name: Type name for the active format.
        translations: Language to translations mapping.
        format_statuses: Per-format status mapping.
    """

    tag_id: int
    tag: str
    source_tag: str | None
    usage_count: int
    alias: bool
    deprecated: bool
    type_id: int | None
    type_name: str
    translations: dict[str, list[str]]
    format_statuses: dict[str, dict[str, object]]


class TagTranslationInput(BaseModel):
    """翻訳エントリ（登録入力）。

    Args:
        language: 言語コード（例: ja, zh-CN）。
        translation: 翻訳文字列。
    """

    language: str = Field(..., description="言語コード(例: ja, zh-CN)")
    translation: str = Field(..., description="翻訳文字列")


class TagRegisterRequest(BaseModel):
    """ユーザー登録用のタグ入力（外部向け）。

    Args:
        tag: 登録する正規タグ。
        source_tag: ソースタグ（あれば）。
        format_name: フォーマット名。
        type_name: タイプ名。
        alias: エイリアスかどうか。
        preferred_tag: 推奨タグ（alias時のみ）。
        translations: 翻訳の追加。
    """

    tag: str = Field(..., description="登録する正規タグ")
    source_tag: str | None = Field(default=None, description="ソースタグ")
    format_name: str = Field(..., description="フォーマット名")
    type_name: str = Field(..., description="タイプ名")
    alias: bool = Field(default=False, description="エイリアスかどうか")
    preferred_tag: str | None = Field(default=None, description="推奨タグ(alias時のみ)")
    translations: list[TagTranslationInput] | None = Field(default=None, description="翻訳の追加")


class TagRegisterResult(BaseModel):
    """登録結果。

    Args:
        created: 新規作成かどうか。
    """

    created: bool = Field(..., description="新規作成かどうか")


class TagStatisticsResult(BaseModel):
    """統計サマリ。

    Args:
        total_tags: 総タグ数。
        total_aliases: エイリアス総数。
        total_formats: フォーマット総数。
        total_types: タイプ総数。
    """

    total_tags: int = Field(..., description="総タグ数")
    total_aliases: int = Field(..., description="エイリアス総数")
    total_formats: int = Field(..., description="フォーマット総数")
    total_types: int = Field(..., description="タイプ総数")


class GeneralStatsResult(BaseModel):
    """全体統計結果。

    Args:
        total_tags: 総タグ数。
        alias_tags: エイリアスタグ数。
        non_alias_tags: 非エイリアスタグ数。
        format_counts: フォーマット別タグ数。
    """

    total_tags: int = Field(..., description="総タグ数")
    alias_tags: int = Field(..., description="エイリアスタグ数")
    non_alias_tags: int = Field(..., description="非エイリアスタグ数")
    format_counts: dict[str, int] = Field(..., description="フォーマット別タグ数")
