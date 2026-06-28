from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from pydantic import BaseModel, Field, model_validator

from genai_tag_db_tools.db.schema import Tag, TagStatus, TagTranslation


class TagRef(BaseModel):
    """タグのスコープ付き内部参照。base DB / user DB を横断して一意にタグを指す。

    Args:
        scope: タグが属するDB種別。"base" = base DB、"user" = user DB。
        tag_id: 対象DBにおけるタグID。

    Note:
        内部専用モデル。外部 API (TagRecordPublic 等) には露出しない。
        user tag の tag_id は USER_TAG_ID_OFFSET (1_000_000_000) 以上が保証される。
    """

    scope: Literal["base", "user"]
    tag_id: int
    model_config = {"frozen": True}


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


class CliErrorResult(BaseModel):
    """CLI失敗時の構造化エラー行。"""

    ok: bool = Field(default=False, description="Always false for error lines")
    code: str = Field(..., description="Standard error code")
    message: str = Field(..., description="Human-readable error message")
    retryable: bool = Field(..., description="Whether retrying the same command may succeed")
    user_action_required: bool = Field(..., description="Whether the user must change input or setup")
    hint: str | None = Field(default=None, description="Optional remediation hint")
    details: dict[str, object] | None = Field(default=None, description="Optional structured details")


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
    partial: bool = Field(default=True, description="Use partial matching")
    format_names: list[str] | None = Field(default=None, description="Format name filters")
    type_names: list[str] | None = Field(default=None, description="Type name filters")
    resolve_preferred: bool = Field(default=True, description="Resolve to preferred tags")
    include_aliases: bool = Field(default=True, description="Include alias tags")
    include_deprecated: bool = Field(default=False, description="Include deprecated tags")
    min_usage: int | None = Field(default=None, description="Minimum usage count")
    max_usage: int | None = Field(default=None, description="Maximum usage count")
    limit: int | None = Field(default=None, ge=1, description="Maximum number of items to return")
    offset: int = Field(default=0, ge=0, description="Number of items to skip")


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
    """検索結果の1行（外部向け / tag_id 含む）。

    Args:
        tag: 表示用の正規タグ。
        source_tag: ソースタグ（あれば）。
        tag_id: タグID。
        format_name: フォーマット名。
        type_name: タイプ名。
        alias: エイリアスかどうか。
    """

    tag: str = Field(..., description="表示用の正規タグ")
    source_tag: str | None = Field(default=None, description="ソースタグ")
    tag_id: int = Field(..., description="タグID")
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
    scope: Literal["base", "user"] = Field(default="base", description="登録先DB種別")


class TagRegisterResult(BaseModel):
    """登録結果。

    Args:
        created: 新規作成かどうか。
        tag_id: 登録されたタグID。
    """

    created: bool = Field(..., description="新規作成かどうか")
    tag_id: int = Field(..., description="登録されたタグID")


ProposalValue = str | int | float | bool | None


class RefinementReason(BaseModel):
    """手動 refinement 推奨理由。

    Args:
        code: UI/テストが依存する安定コード。
        message: 人間向けの日本語メッセージ。
    """

    code: Literal[
        "empty_normalized_tag",
        "normalization_changes_tag",
        "broad_single_word",
        "deprecated_tag",
        "unknown_type",
        "type_correction_candidate",
        "status_type_conflict",
        "training_unsuitable",
        "site_info_token",
        "wrong_language_translation",
        "missing_translation",
        "overlong_translation",
        "description_like_translation",
        "translation_mismatch",
        "low_quality_translation",
        "alias_tag",
        "non_preferred_tag",
        "typo_alias_candidate",
        "ambiguous_alias_candidates",
        "missing_preferred_tag",
        "translation_match_tag",
        "missing_format_status",
        "external_id_tag",
    ] = Field(..., description="Stable reason code")
    message: str = Field(..., description="Human-readable Japanese message")
    field: str | None = Field(default=None, description="Target field identifier, such as translation.ja")
    evidence: list[dict[str, ProposalValue]] = Field(
        default_factory=list,
        description="Supporting evidence for the advisory reason",
    )


class RefinementSuggestion(BaseModel):
    """refinement の候補または確認アクション。

    Args:
        kind: 候補の種別。correction_candidate は自動補正候補、
            review_only は人による確認のみ。
        tag: 候補タグ。review_only では None。
    """

    kind: Literal["correction_candidate", "review_only"] = Field(..., description="Suggestion kind")
    tag: str | None = Field(default=None, description="Suggested normalized tag")


class ProposalTarget(BaseModel):
    """DB feedback proposal target expressed without mutating any DB.

    `format_name=None` means the proposal targets global tag data. Format-dependent data
    with an unknown format must use `format_name="unknown"` instead.
    """

    kind: Literal[
        "tag_name",
        "source_tag",
        "alias",
        "tag_type",
        "tag_status",
        "translation",
        "usage",
        "format_relation",
    ] = Field(..., description="Target field or relation kind")
    target_scope: Literal["base", "user"] = Field(..., description="Patch target scope")
    target_tag_id: int | None = Field(
        default=None,
        description="Patch target tag id in target_scope. None means the target tag does not exist yet.",
    )
    format_name: str | None = Field(
        default=None,
        description='Format-specific target name. None means global target; use "unknown" when unknown.',
    )
    language: str | None = Field(default=None, description="Translation language for translation targets")
    preferred_scope: Literal["base", "user"] | None = Field(
        default=None,
        description="Preferred tag scope for alias/preferred relation proposals",
    )
    preferred_tag_id: int | None = Field(
        default=None,
        description="Preferred tag id for alias/preferred relation proposals",
    )

    @model_validator(mode="after")
    def _validate_preferred_ref(self) -> ProposalTarget:
        if (self.preferred_scope is None) != (self.preferred_tag_id is None):
            raise ValueError("preferred_scope and preferred_tag_id must be provided together")
        return self


class DbFeedbackProposal(BaseModel):
    """A proposed DB feedback action emitted by recommendation logic.

    This is an advisory model only. It is intentionally not an overlay patch row and does
    not apply, validate, or export mutations by itself.
    """

    kind: Literal[
        "tag_name_correction",
        "alias_addition",
        "preferred_tag_correction",
        "translation_correction",
        "usage_correction",
        "type_correction",
        "status_correction",
        "format_relation_review",
    ] = Field(..., description="Proposal action kind")
    target: ProposalTarget = Field(..., description="Overlay-aware proposal target")
    current: dict[str, ProposalValue] | None = Field(
        default=None,
        description="Current observed values, if known",
    )
    proposed: dict[str, ProposalValue] | None = Field(
        default=None,
        description="Proposed values, if known",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Proposal confidence")
    source: str = Field(..., description="Recommendation or detector source")
    reason_codes: list[str] = Field(default_factory=list, description="Stable reason codes")
    evidence: list[dict[str, ProposalValue]] = Field(
        default_factory=list, description="Supporting evidence"
    )
    requires_human_approval: bool = Field(
        default=True,
        description="Whether a human must approve before any future DB mutation",
    )


class RefinementRecommendation(BaseModel):
    """タグを手で直すべきかを表す advisory API 結果。"""

    source_tag: str = Field(..., description="Original input tag")
    normalized_tag: str = Field(..., description="Normalized tag candidate for TAGS.tag / USER_TAGS.tag")
    needs_refinement: bool = Field(..., description="Whether any correction or review is needed")
    score: float = Field(..., ge=0.0, le=1.0, description="Advisory confidence/severity score")
    reasons: list[RefinementReason] = Field(
        default_factory=list, description="Reasons for the recommendation"
    )
    suggestions: list[RefinementSuggestion] = Field(
        default_factory=list,
        description="Structured correction candidates or review-only actions",
    )
    proposals: list[DbFeedbackProposal] = Field(
        default_factory=list,
        description="Future DB feedback proposals derived from the recommendation",
    )


class ApprovedDbFeedback(BaseModel):
    """人間承認済みの DB feedback proposal。"""

    proposal: DbFeedbackProposal = Field(..., description="Approved proposal")
    approved: bool = Field(..., description="Whether this proposal was approved by a human")
    approved_by: str = Field(..., description="Human approver identifier")
    approved_at: datetime = Field(..., description="Approval timestamp")
    approval_note: str | None = Field(default=None, description="Optional approval note")

    @model_validator(mode="after")
    def _validate_approved(self) -> ApprovedDbFeedback:
        if not self.approved:
            raise ValueError("approved feedback must have approved=true")
        return self


class LocalFeedbackApplicationRecord(BaseModel):
    """user-local feedback apply の audit record。"""

    application_id: int
    proposal_hash: str
    proposal_kind: Literal[
        "tag_name_correction",
        "alias_addition",
        "preferred_tag_correction",
        "translation_correction",
        "usage_correction",
        "type_correction",
        "status_correction",
        "format_relation_review",
    ]
    target_kind: Literal[
        "tag_name",
        "alias",
        "preferred_tag",
        "tag_type",
        "tag_status",
        "translation",
        "usage",
        "format_relation",
    ]
    target_scope: Literal["base", "user"] | None = None
    target_tag_id: int | None = None
    format_name: str | None = None
    field: str | None = None
    approved_by: str
    approved_at: datetime
    applied_at: datetime | None = None
    status: Literal["applied", "dry_run", "skipped", "failed"]
    dry_run: bool
    proposal_json: str
    before_json: str | None = None
    after_json: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _validate_dry_run_status(self) -> LocalFeedbackApplicationRecord:
        if self.status == "applied" and self.dry_run:
            raise ValueError("applied application records must have dry_run=false")
        if self.status == "dry_run" and not self.dry_run:
            raise ValueError("dry_run application records must have dry_run=true")
        return self


class LocalFeedbackApplyResult(BaseModel):
    """user-local feedback apply の結果。"""

    ok: bool = Field(..., description="Whether the operation completed without validation/apply error")
    status: Literal["applied", "dry_run", "skipped", "failed"] = Field(..., description="Apply status")
    dry_run: bool = Field(..., description="Whether this was a dry run")
    proposal_hash: str = Field(..., description="Stable hash of the proposal payload")
    proposal_kind: Literal[
        "tag_name_correction",
        "alias_addition",
        "preferred_tag_correction",
        "translation_correction",
        "usage_correction",
        "type_correction",
        "status_correction",
        "format_relation_review",
    ] = Field(..., description="Proposal kind")
    message: str = Field(..., description="Human-readable result message")
    changes: list[dict[str, ProposalValue]] = Field(
        default_factory=list, description="Planned or applied changes"
    )
    application: LocalFeedbackApplicationRecord | None = Field(
        default=None,
        description="Audit record for applied/dry-run/skipped proposals",
    )

    @model_validator(mode="after")
    def _validate_ok_status(self) -> LocalFeedbackApplyResult:
        if self.ok != (self.status != "failed"):
            raise ValueError("ok must be true unless status is failed")
        if self.status == "applied" and self.dry_run:
            raise ValueError("applied results must have dry_run=false")
        if self.status == "dry_run" and not self.dry_run:
            raise ValueError("dry_run results must have dry_run=true")
        if self.application is not None:
            if self.application.proposal_hash != self.proposal_hash:
                raise ValueError("application proposal_hash must match result proposal_hash")
            if self.application.proposal_kind != self.proposal_kind:
                raise ValueError("application proposal_kind must match result proposal_kind")
            if self.application.status != self.status:
                raise ValueError("application status must match result status")
            if self.application.dry_run != self.dry_run:
                raise ValueError("application dry_run must match result dry_run")
        return self


class ConvertTagsRequest(BaseModel):
    """タグ変換リクエスト（CLI/core契約用）。"""

    tags: str = Field(..., description="Comma-separated input tags")
    format_name: str = Field(..., description="Target format name")
    separator: str = Field(default=", ", description="Output tag separator")


class ConvertTagsResult(BaseModel):
    """タグ変換結果（CLI/core契約用）。"""

    input: str = Field(..., description="Original input tag string")
    output: str = Field(..., description="Converted tag string")
    format: str = Field(..., description="Target format name")


class TagTypeUpdate(BaseModel):
    """タグtype更新リクエスト。

    Args:
        tag_id: 更新対象のタグID。
        type_name: 新しいtype名（例: "character", "general", "meta"）。
    """

    tag_id: int = Field(..., description="更新対象のタグID")
    type_name: str = Field(..., description="新しいtype名")


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


class PreloadedData(BaseModel):
    """Preloaded data for tag search result building.

    Args:
        format_name_by_id: Format ID to name mapping.
        type_name_by_key: (format_id, type_id) to type name mapping.
        usage_by_key: (tag_id, format_id) to usage count mapping.
        tags_by_id: Tag ID to Tag object mapping.
        trans_by_tag_id: Tag ID to translations mapping.
        status_by_tag_format: (tag_id, format_id) to status mapping.
        statuses_by_tag_id: Tag ID to status list mapping.
    """

    model_config = {"arbitrary_types_allowed": True}

    format_name_by_id: dict[int, str]
    type_name_by_key: dict[tuple[int, int], str]
    usage_by_key: dict[tuple[int, int], int]
    tags_by_id: dict[int, Tag]
    trans_by_tag_id: dict[int, list[TagTranslation]]
    status_by_tag_format: dict[tuple[int, int], TagStatus]
    statuses_by_tag_id: dict[int, list[TagStatus]]


PreloadedData.model_rebuild()


class AliasRegisterInput(BaseModel):
    """alias一括登録の1エントリ入力。"""

    alias: str = Field(..., description="エイリアスタグ(誤字・別名)")
    preferred: str = Field(..., description="正規タグ(preferred_tag)")
    format_name: str = Field(..., description="フォーマット名")
    type_name: str = Field(default="unknown", description="タイプ名")


class AliasRegisterItemResult(BaseModel):
    """alias登録の1行処理結果。"""

    alias: str = Field(..., description="エイリアスタグ")
    preferred: str = Field(..., description="正規タグ")
    status: str = Field(
        ...,
        description="処理結果: would_create / created / skipped / conflict / missing_preferred",
    )
    alias_tag_id: int | None = Field(default=None, description="aliasのタグID(apply後)")
    preferred_tag_id: int | None = Field(default=None, description="preferredのタグID")


class AliasRegisterResult(BaseModel):
    """alias一括登録の最終サマリ。"""

    ok: bool = Field(..., description="全体成功フラグ")
    dry_run: bool = Field(..., description="dry-runモードか")
    total: int = Field(..., description="入力行数")
    created: int = Field(..., description="新規作成件数")
    skipped: int = Field(..., description="スキップ件数(既存同一)")
    conflicts: int = Field(..., description="衝突件数")
    missing_preferred: int = Field(..., description="preferred未存在件数")
