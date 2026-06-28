# genai_tag_db_tools.db.schema
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Store aware datetimes as naive UTC and read them back as UTC-aware."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class Tag(Base):
    __tablename__ = "TAGS"

    tag_id: Mapped[int] = mapped_column(primary_key=True)
    source_tag: Mapped[str] = mapped_column()
    tag: Mapped[str] = mapped_column()
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    formats_status: Mapped[list[TagStatus]] = relationship(
        "TagStatus",
        back_populates="tag",
        foreign_keys="TagStatus.tag_id",
        cascade="all, delete-orphan",
    )
    preferred_by: Mapped[list[TagStatus]] = relationship(
        "TagStatus",
        back_populates="preferred_tag",
        foreign_keys="TagStatus.preferred_tag_id",
        cascade="all, delete-orphan",
    )
    translations: Mapped[list[TagTranslation]] = relationship(
        "TagTranslation",
        back_populates="tag",
        cascade="all, delete-orphan",
    )
    usage_counts: Mapped[list[TagUsageCounts]] = relationship(
        "TagUsageCounts",
        back_populates="tag",
        cascade="all, delete-orphan",
    )

    __table_args__ = (UniqueConstraint("tag", name="uix_tag"),)


class TagFormat(Base):
    __tablename__ = "TAG_FORMATS"

    format_id: Mapped[int] = mapped_column(primary_key=True)
    format_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None] = mapped_column(nullable=True)

    tags_status: Mapped[list[TagStatus]] = relationship("TagStatus", back_populates="format")


class TagTypeName(Base):
    __tablename__ = "TAG_TYPE_NAME"

    type_name_id: Mapped[int] = mapped_column(primary_key=True)
    type_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None] = mapped_column(nullable=True)


class TagTypeFormatMapping(Base):
    __tablename__ = "TAG_TYPE_FORMAT_MAPPING"

    format_id: Mapped[int] = mapped_column(ForeignKey("TAG_FORMATS.format_id"), primary_key=True)
    type_id: Mapped[int] = mapped_column(primary_key=True)
    type_name_id: Mapped[int] = mapped_column(ForeignKey("TAG_TYPE_NAME.type_name_id"))
    description: Mapped[str | None] = mapped_column(nullable=True)

    type_name: Mapped[TagTypeName] = relationship("TagTypeName")
    statuses: Mapped[list[TagStatus]] = relationship(
        "TagStatus",
        back_populates="type_mapping",
        viewonly=True,
    )


class TagStatus(Base):
    __tablename__ = "TAG_STATUS"

    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"), primary_key=True)
    format_id: Mapped[int] = mapped_column(ForeignKey("TAG_FORMATS.format_id"), primary_key=True)
    type_id: Mapped[int] = mapped_column()
    alias: Mapped[bool] = mapped_column(Boolean, nullable=False)
    preferred_tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"))
    deprecated: Mapped[bool] = mapped_column(Boolean, server_default="0", nullable=False)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    tag: Mapped[Tag] = relationship(
        "Tag",
        foreign_keys="TagStatus.tag_id",
        back_populates="formats_status",
    )
    format: Mapped[TagFormat] = relationship(
        "TagFormat",
        foreign_keys="TagStatus.format_id",
        back_populates="tags_status",
    )
    preferred_tag: Mapped[Tag] = relationship(
        "Tag",
        foreign_keys="TagStatus.preferred_tag_id",
        back_populates="preferred_by",
    )
    type_mapping: Mapped[TagTypeFormatMapping] = relationship(
        "TagTypeFormatMapping",
        primaryjoin=(
            "and_(TagStatus.format_id == TagTypeFormatMapping.format_id, "
            "TagStatus.type_id == TagTypeFormatMapping.type_id)"
        ),
        viewonly=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["format_id", "type_id"],
            ["TAG_TYPE_FORMAT_MAPPING.format_id", "TAG_TYPE_FORMAT_MAPPING.type_id"],
        ),
        CheckConstraint(
            "(alias = false AND preferred_tag_id = tag_id) OR "
            "(alias = true AND preferred_tag_id != tag_id)",
            name="ck_preferred_tag_consistency",
        ),
    )


class TagTranslation(Base):
    __tablename__ = "TAG_TRANSLATIONS"

    translation_id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"))
    language: Mapped[str | None] = mapped_column(nullable=True)
    translation: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    tag: Mapped[Tag] = relationship("Tag", back_populates="translations")

    __table_args__ = (UniqueConstraint("tag_id", "language", "translation", name="uix_tag_lang_trans"),)


class TagUsageCounts(Base):
    __tablename__ = "TAG_USAGE_COUNTS"

    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"), primary_key=True)
    format_id: Mapped[int] = mapped_column(ForeignKey("TAG_FORMATS.format_id"), primary_key=True)
    count: Mapped[int] = mapped_column()
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    tag: Mapped[Tag] = relationship("Tag", back_populates="usage_counts")

    __table_args__ = (UniqueConstraint("tag_id", "format_id", name="uix_tag_format"),)


class DatabaseMetadata(Base):
    __tablename__ = "DATABASE_METADATA"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column()


# --- Overlay schema (user DB 専用) ---
# Base とは別の DeclarativeBase を使い、user DB にのみ作成する。


class UserOverlayBase(DeclarativeBase):
    pass


# user 独自タグの tag_id オフセット。base DB との ID 空間衝突を防ぐ。
USER_TAG_ID_OFFSET = 1_000_000_000


class UserTag(UserOverlayBase):
    """user DB 独自タグ。base DB に存在しないユーザー定義タグを格納する。

    tag_id は USER_TAG_ID_OFFSET (1_000_000_000) 以上で採番し、
    base DB の tag_id との衝突を防ぐ。
    """

    __tablename__ = "USER_TAGS"

    tag_id: Mapped[int] = mapped_column(primary_key=True)
    source_tag: Mapped[str] = mapped_column()
    tag: Mapped[str] = mapped_column()
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    __table_args__ = (
        UniqueConstraint("tag", name="uix_user_tag"),
        CheckConstraint("tag_id >= 1000000000", name="ck_user_tag_id_offset"),
    )


class UserTagStatusPatch(UserOverlayBase):
    """base / user タグへの差分パッチ。

    target_scope + target_tag_id でパッチ対象タグを特定し、
    preferred_scope + preferred_tag_id でエイリアス先を cross-DB で指定する。

    複合 PK (target_scope, target_tag_id, format_id) により
    「同一タグ × フォーマットに付けられるパッチは1行のみ」を保証する。
    """

    __tablename__ = "USER_TAG_STATUS_PATCH"

    target_scope: Mapped[str] = mapped_column(primary_key=True)
    target_tag_id: Mapped[int] = mapped_column(primary_key=True)
    format_id: Mapped[int] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column()
    alias: Mapped[bool] = mapped_column(Boolean, nullable=False)
    preferred_scope: Mapped[str] = mapped_column()
    preferred_tag_id: Mapped[int] = mapped_column()
    deprecated: Mapped[bool] = mapped_column(Boolean, server_default="0", nullable=False)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "target_scope IN ('base', 'user')",
            name="ck_patch_target_scope",
        ),
        CheckConstraint(
            "preferred_scope IN ('base', 'user')",
            name="ck_patch_preferred_scope",
        ),
        CheckConstraint(
            "(alias = 0 AND preferred_scope = target_scope AND preferred_tag_id = target_tag_id)"
            " OR "
            "(alias = 1 AND NOT (preferred_scope = target_scope AND preferred_tag_id = target_tag_id))",
            name="ck_patch_preferred_consistency",
        ),
        Index("ix_patch_target", "target_scope", "target_tag_id"),
        Index("ix_patch_preferred", "preferred_scope", "preferred_tag_id"),
    )


class UserTagTranslationPatch(UserOverlayBase):
    """base / user タグへの翻訳パッチ。
    TAG_TRANSLATIONS の FK なし版。target_scope + target_tag_id で対象タグを指定する。
    """

    __tablename__ = "USER_TAG_TRANSLATION_PATCH"

    patch_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_scope: Mapped[str] = mapped_column()
    target_tag_id: Mapped[int] = mapped_column()
    language: Mapped[str] = mapped_column()
    translation: Mapped[str] = mapped_column()
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "target_scope", "target_tag_id", "language", "translation", name="uix_trans_patch"
        ),
        CheckConstraint("target_scope IN ('base', 'user')", name="ck_trans_patch_scope"),
        Index("ix_trans_patch_target", "target_scope", "target_tag_id"),
    )


class UserTagUsagePatch(UserOverlayBase):
    """base / user タグへの usage count パッチ。
    TAG_USAGE_COUNTS の FK なし版。
    """

    __tablename__ = "USER_TAG_USAGE_PATCH"

    target_scope: Mapped[str] = mapped_column(primary_key=True)
    target_tag_id: Mapped[int] = mapped_column(primary_key=True)
    format_id: Mapped[int] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column()
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), nullable=True)

    __table_args__ = (
        CheckConstraint("target_scope IN ('base', 'user')", name="ck_usage_patch_scope"),
        Index("ix_usage_patch_target", "target_scope", "target_tag_id"),
    )


class LocalFeedbackApplication(UserOverlayBase):
    """user-local feedback proposal の apply 履歴。

    user DB 専用の audit table。proposal の二重 apply 防止と、あとからの確認に使う。
    """

    __tablename__ = "LOCAL_FEEDBACK_APPLICATIONS"

    application_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proposal_hash: Mapped[str] = mapped_column()
    proposal_kind: Mapped[str] = mapped_column()
    target_kind: Mapped[str] = mapped_column()
    target_scope: Mapped[str | None] = mapped_column(nullable=True)
    target_tag_id: Mapped[int | None] = mapped_column(nullable=True)
    format_name: Mapped[str | None] = mapped_column(nullable=True)
    field: Mapped[str | None] = mapped_column(nullable=True)
    approved_by: Mapped[str] = mapped_column()
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime())
    applied_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column()
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    proposal_json: Mapped[str] = mapped_column()
    before_json: Mapped[str | None] = mapped_column(nullable=True)
    after_json: Mapped[str | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "proposal_kind IN ("
            "'tag_name_correction', 'alias_addition', 'preferred_tag_correction', "
            "'translation_correction', 'usage_correction', 'type_correction', "
            "'status_correction', 'format_relation_review'"
            ")",
            name="ck_local_feedback_proposal_kind",
        ),
        CheckConstraint(
            "target_kind IN ("
            "'tag_name', 'alias', 'preferred_tag', 'tag_type', 'tag_status', "
            "'translation', 'usage', 'format_relation'"
            ")",
            name="ck_local_feedback_target_kind",
        ),
        CheckConstraint(
            "target_scope IS NULL OR target_scope IN ('base', 'user')",
            name="ck_local_feedback_target_scope",
        ),
        CheckConstraint(
            "status IN ('applied', 'dry_run', 'skipped', 'failed')",
            name="ck_local_feedback_status",
        ),
        CheckConstraint(
            "(status != 'dry_run' OR dry_run = 1) AND (status != 'applied' OR dry_run = 0)",
            name="ck_local_feedback_dry_run_status",
        ),
        Index(
            "uix_local_feedback_applied_hash",
            "proposal_hash",
            unique=True,
            sqlite_where=text("dry_run = 0 AND status IN ('applied', 'skipped')"),
        ),
        Index("ix_local_feedback_hash", "proposal_hash"),
        Index("ix_local_feedback_target", "target_scope", "target_tag_id"),
    )
