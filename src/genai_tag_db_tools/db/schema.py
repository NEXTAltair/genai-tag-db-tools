# genai_tag_db_tools.db.schema
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


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
