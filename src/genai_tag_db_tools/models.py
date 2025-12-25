from __future__ import annotations

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
        cache_dir: SQLiteの保存先ディレクトリ。
        token: HFアクセストークン（必要な場合のみ）。
    """

    cache_dir: str = Field(..., examples=["/path/to/tag_db_cache"])
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
        db_path: ローカルSQLiteの実体パス。
        downloaded: 今回新規ダウンロードしたか。
        sha256: 取得ファイルのSHA256。
    """

    db_path: str = Field(..., description="ローカルSQLiteの実体パス")
    downloaded: bool = Field(..., description="今回新規ダウンロードしたか")
    sha256: str = Field(..., description="取得ファイルのSHA256")


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

    query: str = Field(..., description="検索クエリ")
    format_names: list[str] | None = Field(default=None, description="対象フォーマット名の絞り込み")
    type_names: list[str] | None = Field(default=None, description="対象タイプ名の絞り込み")
    resolve_preferred: bool = Field(default=True, description="推奨タグへ正規化して返す")
    include_aliases: bool = Field(default=True, description="エイリアスを含める")
    include_deprecated: bool = Field(default=False, description="非推奨タグを含める")
    min_usage: int | None = Field(default=None, description="??????")
    max_usage: int | None = Field(default=None, description="??????")
    limit: int | None = Field(default=None, description="取得件数(Noneで無制限)")
    offset: int = Field(default=0, description="取得オフセット")


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
    translations: dict[str, list[str]] | None = Field(
        default=None, description="言語別の翻訳一覧"
    )
    format_statuses: dict[str, dict[str, object]] | None = Field(
        default=None, description="フォーマット別の状態一覧"
    )


class TagSearchResult(BaseModel):
    """検索結果のコンテナ。

    Args:
        items: 検索結果の一覧。
        total: 総件数（不明ならNone）。
    """

    items: list[TagRecordPublic] = Field(..., description="検索結果の一覧")
    total: int | None = Field(default=None, description="総件数(不明ならNone)")


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
