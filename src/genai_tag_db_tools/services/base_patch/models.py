"""Models and shared constants for the base DB correction patch pipeline.

The base correction patch is a name-based, builder-friendly JSONL envelope. Only four
keys are required for a patch to be well-formed:

``schema_version``, ``patch_type``, ``target``, ``proposed``.

Everything else (``patch_id``, ``scope``, ``current``, ``approved*``, ``validated*``,
``source_proposal``, ``reason_codes``, ``evidence``, ``note``) is optional. Hand-written
PR patch files may omit all optional keys; PR review and CI validation take the role of
approval / validation in that flow.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

# MVP のスキーマバージョン。これ以外は unsupported_schema_version として拒否する。
SCHEMA_VERSION = 1

# builder apply / export 対象になる patch type。
SUPPORTED_PATCH_TYPES: frozenset[str] = frozenset(
    {
        "alias_addition",
        "preferred_tag_correction",
        "translation_correction",
        "type_correction",
        "status_correction",
        "tag_name_correction",
    }
)

# apply patch としては明示的に拒否する patch type。
REJECTED_PATCH_TYPES: frozenset[str] = frozenset(
    {
        "metadata_correction",
        "training_policy_correction",
        "format_relation_review",
    }
)

# patch_type ごとに矛盾してはいけない target.target_type。
TARGET_TYPE_BY_PATCH_TYPE: dict[str, str] = {
    "alias_addition": "alias",
    "preferred_tag_correction": "alias",
    "translation_correction": "translation",
    "type_correction": "tag_type",
    "status_correction": "tag_status",
    "tag_name_correction": "tag_name",
}

# target.format_name が必須な patch type。format_name=None は「全 format」として扱わない。
FORMAT_DEPENDENT_PATCH_TYPES: frozenset[str] = frozenset(
    {
        "alias_addition",
        "preferred_tag_correction",
        "type_correction",
        "status_correction",
    }
)

# status_correction で許可する target.field。
ALLOWED_STATUS_FIELDS: frozenset[str] = frozenset({"TAG_STATUS.deprecated"})

ValidationStatus = Literal["valid", "invalid", "warning"]


class BaseCorrectionPatch(BaseModel):
    """base DB に渡す correction patch の最小エンベロープ。

    必須キーは ``schema_version`` / ``patch_type`` / ``target`` / ``proposed`` のみ。
    その他はレビュー・監査・生成出力のための任意キー。
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = Field(..., description="Patch schema version (MVP only accepts 1)")
    patch_type: str = Field(..., description="Correction patch type")
    target: dict[str, Any] = Field(..., description="Patch target object")
    proposed: dict[str, Any] = Field(..., description="Proposed values object")

    patch_id: str | None = Field(default=None, description="Stable sha256:<hex> patch id")
    scope: str | None = Field(default=None, description='Optional scope. Tools emit "base".')
    current: dict[str, Any] | None = Field(default=None, description="Observed current values")
    approved: bool | None = Field(default=None, description="Explicit approval flag")
    approved_by: str | None = Field(default=None, description="Approver identifier")
    approved_at: str | None = Field(default=None, description="Approval timestamp (ISO-8601)")
    validated: bool | None = Field(default=None, description="Explicit validation flag")
    validated_at: str | None = Field(default=None, description="Validation timestamp (ISO-8601)")
    source_proposal: dict[str, Any] | None = Field(default=None, description="Originating proposal")
    reason_codes: list[str] = Field(default_factory=list, description="Stable reason codes")
    evidence: dict[str, Any] | None = Field(default=None, description="Supporting evidence")
    note: str | None = Field(default=None, description="Human readable note")

    # patch_id の入力に含めるキー (承認者 / evidence は含めない)。
    _PATCH_ID_KEYS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "scope",
        "patch_type",
        "target",
        "proposed",
    )

    @property
    def target_type(self) -> str | None:
        value = self.target.get("target_type")
        return value if isinstance(value, str) else None

    @property
    def target_tag(self) -> str | None:
        for key in ("tag", "source_tag"):
            value = self.target.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @property
    def format_name(self) -> str | None:
        value = self.target.get("format_name")
        return value if isinstance(value, str) else None

    @property
    def field(self) -> str | None:
        value = self.target.get("field")
        return value if isinstance(value, str) else None

    def patch_id_payload(self) -> dict[str, Any]:
        """patch_id 計算に使う正規化前 payload を返す。"""
        return {
            "schema_version": self.schema_version,
            "scope": self.scope,
            "patch_type": self.patch_type,
            "target": self.target,
            "proposed": self.proposed,
        }


def compute_patch_id(patch: BaseCorrectionPatch) -> str:
    """同じ内容なら同じ値になる安定 patch_id を計算する。

    ``schema_version`` / ``scope`` / ``patch_type`` / ``target`` / ``proposed`` を
    正規化 JSON にして SHA-256 を取る。``approved_by`` / ``approved_at`` / ``evidence``
    は入力に含めない (承認者や根拠が変わっても同じ DB mutation を重複扱いできるように)。
    """
    canonical = json.dumps(
        patch.patch_id_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class PatchValidationIssue(BaseModel):
    """構造化された validation error / warning。"""

    code: str = Field(..., description="Stable error or warning code")
    message: str = Field(..., description="Human-readable message")
    field: str | None = Field(default=None, description="Related field, if any")


class PatchValidationItemResult(BaseModel):
    """1 patch の validation 結果。"""

    line_number: int | None = Field(default=None, description="1-based JSONL line number")
    patch_id: str | None = Field(default=None, description="Patch id (provided or computed)")
    patch_type: str | None = Field(default=None, description="Patch type")
    target_type: str | None = Field(default=None, description="Target type")
    target_tag: str | None = Field(default=None, description="Target tag")
    format_name: str | None = Field(default=None, description="Format name")
    status: ValidationStatus = Field(..., description="valid / invalid / warning")
    errors: list[PatchValidationIssue] = Field(default_factory=list, description="Blocking errors")
    warnings: list[PatchValidationIssue] = Field(default_factory=list, description="Non-blocking warnings")

    @property
    def ok(self) -> bool:
        """invalid でなければ True (warning は apply 可能)。"""
        return self.status != "invalid"


class PatchValidationResult(BaseModel):
    """patch file 全体の validation 結果。"""

    items: list[PatchValidationItemResult] = Field(default_factory=list, description="Per-patch results")

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.items)

    @property
    def valid_count(self) -> int:
        return sum(1 for item in self.items if item.status == "valid")

    @property
    def warning_count(self) -> int:
        return sum(1 for item in self.items if item.status == "warning")

    @property
    def invalid_count(self) -> int:
        return sum(1 for item in self.items if item.status == "invalid")
