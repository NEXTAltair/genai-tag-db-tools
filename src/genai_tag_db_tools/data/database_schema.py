# genai_tag_db_tools.data.database_schema
from __future__ import annotations  # 循環参照や古いバージョン対策に入れておくと安全

from datetime import datetime
from logging import getLogger

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    Session,
    declarative_base,
    mapped_column,
    relationship,
)

from genai_tag_db_tools.db.database_setup import SessionLocal as production_SessionLocal
from genai_tag_db_tools.db.database_setup import engine as production_engine

# テスト時にモンキーパッチで上書きされる可能性のある変数
engine = production_engine
SessionLocal = production_SessionLocal

Base = declarative_base()


# --------------------------------------------------------------------------
# TagStatus モデル
# --------------------------------------------------------------------------
class TagStatus(Base):
    __tablename__ = "TAG_STATUS"

    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"), primary_key=True)
    format_id: Mapped[int] = mapped_column(ForeignKey("TAG_FORMATS.format_id"), primary_key=True)
    type_id: Mapped[int | None] = mapped_column(nullable=True)
    alias: Mapped[bool] = mapped_column(Boolean, nullable=False)
    preferred_tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"))

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )

    # リレーション TagStatus → Tag (tag_id)
    tag: Mapped[Tag] = relationship(
        "Tag",
        foreign_keys=[tag_id],
        back_populates="formats_status",
    )

    # リレーション TagStatus → TagFormat
    format: Mapped[TagFormat] = relationship(
        "TagFormat",
        foreign_keys=[format_id],
        back_populates="tags_status",
    )

    # リレーション TagStatus → Tag (preferred_tag_id)
    preferred_tag: Mapped[Tag] = relationship(
        "Tag",
        foreign_keys=[preferred_tag_id],
        back_populates="preferred_by",
    )

    # (format_id, type_id) → TagTypeFormatMapping
    type_mapping: Mapped[TagTypeFormatMapping] = relationship(
        "TagTypeFormatMapping",
        primaryjoin=(
            "and_(TagStatus.format_id == TagTypeFormatMapping.format_id, "
            "TagStatus.type_id == TagTypeFormatMapping.type_id)"
        ),
        viewonly=True,
        # back_populates="statuses",  # TagTypeFormatMapping側に書くなら相互に
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


# --------------------------------------------------------------------------
# TagTranslation モデル
# --------------------------------------------------------------------------
class TagTranslation(Base):
    __tablename__ = "TAG_TRANSLATIONS"

    translation_id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"))
    language: Mapped[str] = mapped_column()
    translation: Mapped[str] = mapped_column()

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )

    tag: Mapped[Tag] = relationship("Tag", back_populates="translations")

    __table_args__ = (UniqueConstraint("tag_id", "language", "translation", name="uix_tag_lang_trans"),)


# --------------------------------------------------------------------------
# TagUsageCounts モデル
# --------------------------------------------------------------------------
class TagUsageCounts(Base):
    __tablename__ = "TAG_USAGE_COUNTS"

    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"), primary_key=True)
    format_id: Mapped[int] = mapped_column(ForeignKey("TAG_FORMATS.format_id"), primary_key=True)
    count: Mapped[int] = mapped_column()

    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), nullable=True)

    tag: Mapped[Tag] = relationship("Tag", back_populates="usage_counts")

    __table_args__ = (
        UniqueConstraint("tag_id", "format_id", name="uix_tag_format"),
        Index("idx_tag_id", "tag_id"),
        Index("idx_format_id", "format_id"),
    )


# --------------------------------------------------------------------------
# Tag モデル
# --------------------------------------------------------------------------
class Tag(Base):
    __tablename__ = "TAGS"

    tag_id: Mapped[int] = mapped_column(primary_key=True)
    tag: Mapped[str] = mapped_column()
    source_tag: Mapped[str] = mapped_column()

    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), nullable=True)

    # 1対多: Tag → TagStatus
    formats_status: Mapped[list[TagStatus]] = relationship(
        "TagStatus",
        back_populates="tag",
        foreign_keys=[TagStatus.tag_id],
        cascade="all, delete-orphan",
    )

    # 1対多: Tag → TagStatus (preferred_tag 参照用)
    preferred_by: Mapped[list[TagStatus]] = relationship(
        "TagStatus",
        back_populates="preferred_tag",
        foreign_keys=[TagStatus.preferred_tag_id],
        cascade="all, delete-orphan",
    )

    # 1対多: Tag → TagTranslation
    translations: Mapped[list[TagTranslation]] = relationship(
        "TagTranslation",
        back_populates="tag",
        cascade="all, delete-orphan",
    )

    # 1対多: Tag → TagUsageCounts
    usage_counts: Mapped[list[TagUsageCounts]] = relationship(
        "TagUsageCounts",
        back_populates="tag",
        cascade="all, delete-orphan",
    )


# --------------------------------------------------------------------------
# TagFormat モデル
# --------------------------------------------------------------------------
class TagFormat(Base):
    __tablename__ = "TAG_FORMATS"

    format_id: Mapped[int] = mapped_column(primary_key=True)
    format_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None] = mapped_column(nullable=True)

    # 1対多: TagFormat → TagStatus
    tags_status: Mapped[list[TagStatus]] = relationship("TagStatus", back_populates="format")


# --------------------------------------------------------------------------
# TagTypeName モデル
# --------------------------------------------------------------------------
class TagTypeName(Base):
    __tablename__ = "TAG_TYPE_NAME"

    type_name_id: Mapped[int] = mapped_column(primary_key=True)
    type_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None] = mapped_column(nullable=True)


# --------------------------------------------------------------------------
# TagTypeFormatMapping モデル
# --------------------------------------------------------------------------
class TagTypeFormatMapping(Base):
    __tablename__ = "TAG_TYPE_FORMAT_MAPPING"

    format_id: Mapped[int] = mapped_column(ForeignKey("TAG_FORMATS.format_id"), primary_key=True)
    type_id: Mapped[int] = mapped_column(primary_key=True)
    type_name_id: Mapped[int] = mapped_column(ForeignKey("TAG_TYPE_NAME.type_name_id"))
    description: Mapped[str | None] = mapped_column(nullable=True)

    # リレーション: (format_id, type_id) → TagTypeName
    type_name: Mapped[TagTypeName] = relationship("TagTypeName")

    statuses: Mapped[list[TagStatus]] = relationship(
        "TagStatus",
        back_populates="type_mapping",
        viewonly=True,
    )


# --------------------------------------------------------------------------
# TagDatabase クラス
# --------------------------------------------------------------------------


class TagDatabase:
    """タグデータベース管理クラス"""

    def __init__(
        self,
        external_session: Session | None = None,
        init_master: bool = True,
    ):
        """
        Args:
            external_session (Optional[Session]): すでに作成された外部セッションを注入する場合
            init_master (bool): マスターデータを初期化するかどうか。デフォルトはTrue
        """
        self.logger = getLogger(__name__)
        self._sessions: set[Session] = set()

        # 1) セッションの設定
        if external_session is not None:
            # 外部からセッションが注入された場合
            self.session = external_session
            # 外部セッションのエンジンを使用
            self.engine = external_session.get_bind()
        else:
            # database_setup.py にある共通の SessionLocal() を利用
            self.engine = engine
            self.session = SessionLocal()
            self._sessions.add(self.session)

        # 3) 必要ならマスターデータ初期化
        if init_master:
            # テーブル作成とマスターデータ初期化は同じセッションで行う
            self.create_tables()
            self.init_master_data()
            self.session.commit()  # マスターデータの変更を確定

    def cleanup(self):
        """
        テストなどで使ったセッションを全てクローズ。
        外部セッションも追加されていればここでクローズされるので、
        テストでは session.is_active == False になるはず。
        """
        for sess in list(self._sessions):
            try:
                # トランザクションをロールバックしてからクローズ
                sess.rollback()
                # セッションからすべてのオブジェクトを削除
                sess.expunge_all()
                # セッションをクローズ
                sess.close()
                # (エンジンやbindはdisposeしない方が無難。必要ならdispose()を呼ぶ)
            except Exception as e:
                self.logger.error(f"セッションのクローズ中にエラー: {e}")
            finally:
                self._sessions.discard(sess)

    def __del__(self):
        self.cleanup()

    def create_tables(self):
        """
        テーブル作成などの初期化。Base.metadata.create_all() を呼び出す。
        """
        Base.metadata.create_all(self.engine)

    def init_master_data(self):
        """マスターデータを初期化"""
        self.init_tagformat()
        self.init_tagtypename()
        self.init_tagtypeformatmapping()

    def init_tagformat(self):
        """
        TagFormatテーブルのマスターデータを初期化する。
        メインのセッションを使用し、トランザクション内で実行する。
        """
        initial_data = [
            TagFormat(format_id=0, format_name="unknown", description=""),
            TagFormat(format_id=1, format_name="danbooru", description=""),
            TagFormat(format_id=2, format_name="e621", description=""),
            TagFormat(format_id=3, format_name="derpibooru", description=""),
        ]
        try:
            for data in initial_data:
                existing = self.session.query(TagFormat).filter_by(format_name=data.format_name).first()
                if not existing:
                    self.session.add(data)
            self.session.commit()
        except Exception as e:
            self.logger.error(f"TagFormatの初期化中にエラー: {e}")
            self.session.rollback()
            raise

    def init_tagtypename(self):
        """
        TagTypeNameテーブルのマスターデータを初期化する。
        メインのセッションを使用し、トランザクション内で実行する。
        """
        initial_data = [
            TagTypeName(type_name_id=0, type_name="unknown", description=""),
            TagTypeName(type_name_id=1, type_name="general", description=""),
            TagTypeName(type_name_id=2, type_name="artist", description=""),
            TagTypeName(type_name_id=3, type_name="copyright", description=""),
            TagTypeName(type_name_id=4, type_name="character", description=""),
            TagTypeName(type_name_id=5, type_name="species", description=""),
            TagTypeName(type_name_id=6, type_name="invalid", description=""),
            TagTypeName(type_name_id=7, type_name="meta", description=""),
            TagTypeName(type_name_id=8, type_name="lore", description=""),
            TagTypeName(type_name_id=9, type_name="oc", description=""),
            TagTypeName(type_name_id=10, type_name="rating", description=""),
            TagTypeName(type_name_id=11, type_name="body-type", description=""),
            TagTypeName(type_name_id=12, type_name="origin", description=""),
            TagTypeName(type_name_id=13, type_name="error", description=""),
            TagTypeName(type_name_id=14, type_name="spoiler", description=""),
            TagTypeName(type_name_id=15, type_name="content-official", description=""),
            TagTypeName(type_name_id=16, type_name="content-fanmade", description=""),
        ]
        try:
            for data in initial_data:
                existing = self.session.query(TagTypeName).filter_by(type_name_id=data.type_name_id).first()
                if not existing:
                    self.session.add(data)
            self.session.commit()
        except Exception as e:
            self.logger.error(f"TagTypeNameの初期化中にエラー: {e}")
            self.session.rollback()
            raise

    def init_tagtypeformatmapping(self):
        """
        TagTypeFormatMappingテーブルのマスターデータを初期化する。
        メインのセッションを使用し、トランザクション内で実行する。
        """
        initial_data = [
            TagTypeFormatMapping(format_id=0, type_id=0, type_name_id=0),
            # Format 1 (danbooru)
            TagTypeFormatMapping(format_id=1, type_id=0, type_name_id=1),  # general
            TagTypeFormatMapping(format_id=1, type_id=1, type_name_id=2),  # artist
            TagTypeFormatMapping(format_id=1, type_id=3, type_name_id=3),  # copyright
            TagTypeFormatMapping(format_id=1, type_id=4, type_name_id=4),  # character
            TagTypeFormatMapping(format_id=1, type_id=5, type_name_id=7),  # meta
            # Format 2 (e621)
            TagTypeFormatMapping(format_id=2, type_id=0, type_name_id=1),  # general
            TagTypeFormatMapping(format_id=2, type_id=1, type_name_id=2),  # artist
            TagTypeFormatMapping(format_id=2, type_id=3, type_name_id=3),  # copyright
            TagTypeFormatMapping(format_id=2, type_id=4, type_name_id=4),  # character
            TagTypeFormatMapping(format_id=2, type_id=5, type_name_id=5),  # species
            TagTypeFormatMapping(format_id=2, type_id=6, type_name_id=6),  # invalid
            TagTypeFormatMapping(format_id=2, type_id=7, type_name_id=7),  # meta
            TagTypeFormatMapping(format_id=2, type_id=8, type_name_id=8),  # lore
            # Format 3 (derpibooru)
            TagTypeFormatMapping(format_id=3, type_id=0, type_name_id=1),  # general
            TagTypeFormatMapping(format_id=3, type_id=1, type_name_id=15),  # content-official
            TagTypeFormatMapping(format_id=3, type_id=2, type_name_id=1),  # general
            TagTypeFormatMapping(format_id=3, type_id=3, type_name_id=5),  # species
            TagTypeFormatMapping(format_id=3, type_id=4, type_name_id=9),  # oc
            TagTypeFormatMapping(format_id=3, type_id=5, type_name_id=10),  # rating
            TagTypeFormatMapping(format_id=3, type_id=6, type_name_id=11),  # body-type
            TagTypeFormatMapping(format_id=3, type_id=7, type_name_id=7),  # meta
            TagTypeFormatMapping(format_id=3, type_id=8, type_name_id=12),  # origin
            TagTypeFormatMapping(format_id=3, type_id=9, type_name_id=13),  # error
            TagTypeFormatMapping(format_id=3, type_id=10, type_name_id=14),  # spoiler
            TagTypeFormatMapping(format_id=3, type_id=11, type_name_id=16),  # content-fanmade
        ]
        try:
            for data in initial_data:
                existing = (
                    self.session.query(TagTypeFormatMapping)
                    .filter_by(format_id=data.format_id, type_id=data.type_id)
                    .first()
                )
                if not existing:
                    self.session.add(data)
            self.session.commit()
        except Exception as e:
            self.logger.error(f"TagTypeFormatMappingの初期化中にエラー: {e}")
            self.session.rollback()
            raise
