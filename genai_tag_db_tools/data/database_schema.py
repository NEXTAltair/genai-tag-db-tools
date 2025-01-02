from __future__ import annotations  # 循環参照や古いバージョン対策に入れておくと安全

from logging import getLogger
from typing import Optional, Set
from datetime import datetime
from matplotlib.pylab import f
import polars as pl

from sqlalchemy import (
    create_engine,
    StaticPool,
    ForeignKey,
    UniqueConstraint,
    Boolean,
    Index,
    func,
    DateTime,
    ForeignKeyConstraint,
    CheckConstraint,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    sessionmaker,
    Session,
    relationship,
    Mapped,
    mapped_column,
    declarative_base,
)

Base = declarative_base()


# --------------------------------------------------------------------------
# TagStatus モデル
# --------------------------------------------------------------------------
class TagStatus(Base):
    __tablename__ = "TAG_STATUS"

    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"), primary_key=True)
    format_id: Mapped[int] = mapped_column(
        ForeignKey("TAG_FORMATS.format_id"), primary_key=True
    )
    type_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    alias: Mapped[bool] = mapped_column(Boolean, nullable=False)
    preferred_tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"))

    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )

    # リレーション TagStatus → Tag (tag_id)
    tag: Mapped["Tag"] = relationship(
        "Tag",
        foreign_keys=[tag_id],
        back_populates="formats_status",
    )

    # リレーション TagStatus → TagFormat
    format: Mapped["TagFormat"] = relationship(
        "TagFormat",
        foreign_keys=[format_id],
        back_populates="tags_status",
    )

    # リレーション TagStatus → Tag (preferred_tag_id)
    preferred_tag: Mapped["Tag"] = relationship(
        "Tag",
        foreign_keys=[preferred_tag_id],
        back_populates="preferred_by",
    )

    # (format_id, type_id) → TagTypeFormatMapping
    type_mapping: Mapped["TagTypeFormatMapping"] = relationship(
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

    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )

    tag: Mapped["Tag"] = relationship("Tag", back_populates="translations")

    __table_args__ = (
        UniqueConstraint("tag_id", "language", "translation", name="uix_tag_lang_trans"),
    )


# --------------------------------------------------------------------------
# TagUsageCounts モデル
# --------------------------------------------------------------------------
class TagUsageCounts(Base):
    __tablename__ = "TAG_USAGE_COUNTS"

    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"), primary_key=True)
    format_id: Mapped[int] = mapped_column(
        ForeignKey("TAG_FORMATS.format_id"), primary_key=True
    )
    count: Mapped[int] = mapped_column()

    created_at: Mapped[Optional[datetime]] = mapped_column(
        server_default=func.now(), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        server_default=func.now(), nullable=True
    )

    tag: Mapped["Tag"] = relationship("Tag", back_populates="usage_counts")

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

    created_at: Mapped[Optional[datetime]] = mapped_column(
        server_default=func.now(), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        server_default=func.now(), nullable=True
    )

    # 1対多: Tag → TagStatus
    formats_status: Mapped[list["TagStatus"]] = relationship(
        "TagStatus",
        back_populates="tag",
        foreign_keys=[TagStatus.tag_id],
        cascade="all, delete-orphan",
    )

    # 1対多: Tag → TagStatus (preferred_tag 参照用)
    preferred_by: Mapped[list["TagStatus"]] = relationship(
        "TagStatus",
        back_populates="preferred_tag",
        foreign_keys=[TagStatus.preferred_tag_id],
        cascade="all, delete-orphan",
    )

    # 1対多: Tag → TagTranslation
    translations: Mapped[list["TagTranslation"]] = relationship(
        "TagTranslation",
        back_populates="tag",
        foreign_keys=[TagTranslation.tag_id],
        cascade="all, delete-orphan",
    )

    # 1対多: Tag → TagUsageCounts
    usage_counts: Mapped[list["TagUsageCounts"]] = relationship(
        "TagUsageCounts",
        back_populates="tag",
        foreign_keys=[TagUsageCounts.tag_id],
        cascade="all, delete-orphan",
    )


# --------------------------------------------------------------------------
# TagFormat モデル
# --------------------------------------------------------------------------
class TagFormat(Base):
    __tablename__ = "TAG_FORMATS"

    format_id: Mapped[int] = mapped_column(primary_key=True)
    format_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)

    # 1対多: TagFormat → TagStatus
    tags_status: Mapped[list["TagStatus"]] = relationship(
        "TagStatus",
        back_populates="format"
    )


# --------------------------------------------------------------------------
# TagTypeName モデル
# --------------------------------------------------------------------------
class TagTypeName(Base):
    __tablename__ = "TAG_TYPE_NAME"

    type_name_id: Mapped[int] = mapped_column(primary_key=True)
    type_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)


# --------------------------------------------------------------------------
# TagTypeFormatMapping モデル
# --------------------------------------------------------------------------
class TagTypeFormatMapping(Base):
    __tablename__ = "TAG_TYPE_FORMAT_MAPPING"

    format_id: Mapped[int] = mapped_column(
        ForeignKey("TAG_FORMATS.format_id"), primary_key=True
    )
    type_id: Mapped[int] = mapped_column(primary_key=True)
    type_name_id: Mapped[int] = mapped_column(ForeignKey("TAG_TYPE_NAME.type_name_id"))
    description: Mapped[Optional[str]] = mapped_column(nullable=True)

    # リレーション: (format_id, type_id) → TagTypeName
    type_name: Mapped["TagTypeName"] = relationship("TagTypeName")

    statuses: Mapped[list["TagStatus"]] = relationship(
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
        engine: Optional[Engine] = None,
        session: Optional[Session] = None,
        init_master: bool = True,
    ):
        """
        Args:
            engine: SQLAlchemyのエンジン。Noneの場合はデフォルトのエンジンを作成
            session: SQLAlchemyのセッション。Noneの場合はエンジンから新規作成
            init_master: マスターデータを初期化するかどうか。デフォルトはTrue
        """
        self.logger = getLogger(__name__)
        self._sessions: Set[Session] = set()  # セッション追跡セット

        if engine is not None:
            self.engine = engine
        elif session is not None:
            self.engine = session.get_bind()
        else:
            # ここで db_path が未定義の場合など、どうするか？
            # from pathlib import Path
            # db_path = Path("some_default.db")
            # self.engine = create_engine( ... )
            raise ValueError("Need either an engine or a session with a bound engine.")

        self.sessionmaker = sessionmaker(bind=self.engine)

        # セッションの設定
        if session is not None:
            self.session = session
        else:
            self.session = self.create_session()

        if init_master:
            self.create_tables()
            self.init_master_data()

    def create_session(self) -> Session:
        session = self.sessionmaker()
        self._sessions.add(session)
        return session

    def cleanup(self):
        """リソースのクリーンアップ"""
        for sess in list(self._sessions):
            try:
                sess.close()
            except Exception as e:
                self.logger.error(f"セッションのクローズ中にエラー: {e}")
            finally:
                self._sessions.discard(sess)

    def __del__(self):
        self.cleanup()

    def create_tables(self):
        Base.metadata.create_all(self.engine)

    def init_master_data(self):
        """マスターデータを初期化"""
        self.init_tagformat()
        self.init_tagtypename()
        self.init_tagtypeformatmapping()

    def init_tagformat(self):
        session = self.create_session()
        initial_data = [
            TagFormat(format_id=0, format_name="unknown", description=""),
            TagFormat(format_id=1, format_name="danbooru", description=""),
            TagFormat(format_id=2, format_name="e621", description=""),
            TagFormat(format_id=3, format_name="derpibooru", description=""),
        ]
        try:
            for data in initial_data:
                existing = (
                    session.query(TagFormat)
                    .filter_by(format_name=data.format_name)
                    .first()
                )
                if not existing:
                    session.add(data)
            session.commit()
        except Exception as e:
            self.logger.error(f"TagFormatの初期化中にエラー: {e}")
            session.rollback()
            raise
        finally:
            session.close()
            self._sessions.discard(session)

    def init_tagtypename(self):
        session = self.create_session()
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
                existing = (
                    session.query(TagTypeName)
                    .filter_by(type_name_id=data.type_name_id)
                    .first()
                )
                if not existing:
                    session.add(data)
            session.commit()
        except Exception as e:
            self.logger.error(f"TagTypeNameの初期化中にエラー: {e}")
            session.rollback()
            raise
        finally:
            session.close()
            self._sessions.discard(session)

    def init_tagtypeformatmapping(self):
        session = self.create_session()
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
            TagTypeFormatMapping(
                format_id=3, type_id=1, type_name_id=15
            ),  # content-official
            TagTypeFormatMapping(format_id=3, type_id=2, type_name_id=1),  # general
            TagTypeFormatMapping(format_id=3, type_id=3, type_name_id=5),  # species
            TagTypeFormatMapping(format_id=3, type_id=4, type_name_id=9),  # oc
            TagTypeFormatMapping(format_id=3, type_id=5, type_name_id=10),  # rating
            TagTypeFormatMapping(format_id=3, type_id=6, type_name_id=11),  # body-type
            TagTypeFormatMapping(format_id=3, type_id=7, type_name_id=7),  # meta
            TagTypeFormatMapping(format_id=3, type_id=8, type_name_id=12),  # origin
            TagTypeFormatMapping(format_id=3, type_id=9, type_name_id=13),  # error
            TagTypeFormatMapping(format_id=3, type_id=10, type_name_id=14),  # spoiler
            TagTypeFormatMapping(
                format_id=3, type_id=11, type_name_id=16
            ),  # content-fanmade
        ]
        try:
            for data in initial_data:
                existing = (
                    session.query(TagTypeFormatMapping)
                    .filter_by(format_id=data.format_id, type_id=data.type_id)
                    .first()
                )
                if not existing:
                    session.add(data)
            session.commit()
        except Exception as e:
            self.logger.error(f"TagTypeFormatMappingの初期化中にエラー: {e}")
            session.rollback()
            raise
        finally:
            session.close()
            self._sessions.discard(session)

    @classmethod
    def create_test_instance(cls, engine: Engine) -> TagDatabase:
        return cls(engine=engine, init_master=False)

    def get_formatnames(self):
        query = "SELECT * FROM TAG_TYPE_NAME"
        df = pl.read_database(query, connection=self.engine)
        print(df)


if __name__ == "__main__":
    # テスト起動
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    db = TagDatabase(engine=engine, init_master=True)
    db.get_formatnames()
