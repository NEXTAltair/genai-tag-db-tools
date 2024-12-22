from logging import getLogger
from typing import Optional, Set
from pathlib import Path
from datetime import datetime
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
    sessionmaker,
    Mapped,
    mapped_column,
    declarative_base,
)

# グローバル変数として db_path を定義
db_path = Path("genai_tag_db_tools/data/tags_v4.db")


Base = declarative_base()

engine = create_engine(
    f"sqlite:///{db_path.absolute()}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
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
        {"format_id": pl.UInt32, "format_name": pl.Utf8, "description": pl.Utf8}
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


class Tag(Base):
    __tablename__ = "TAGS"

    tag_id: Mapped[int] = mapped_column(primary_key=True)
    source_tag: Mapped[str] = mapped_column()
    created_at: Mapped[Optional[datetime]] = mapped_column(
        server_default=func.now(), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        server_default=func.now(), nullable=True
    )
    tag: Mapped[str] = mapped_column()

    # 多対多の関係として明確化
    formats_status: Mapped[list["TagStatus"]] = relationship(
        back_populates="tag",
        foreign_keys="[TagStatus.tag_id]",
        cascade="all, delete-orphan",
    )

    # エイリアス関係として明確化
    preferred_by: Mapped[list["TagStatus"]] = relationship(
        "TagStatus",
        back_populates="preferred_tag",
        foreign_keys="[TagStatus.preferred_tag_id]",
        cascade="all, delete-orphan",
    )

    # 翻訳を一体多の関係として明確化
    translations: Mapped[list["TagTranslation"]] = relationship(
        back_populates="tag",
        foreign_keys="[TagTranslation.tag_id]",
        cascade="all, delete-orphan",
    )


class TagFormat(Base):
    __tablename__ = "TAG_FORMATS"

    format_id: Mapped[int] = mapped_column(primary_key=True)
    format_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[Optional[str]]

    # 多対多の関係として明確化
    tags_status: Mapped[list["TagStatus"]] = relationship(back_populates="format")


class TagTypeName(Base):
    __tablename__ = "TAG_TYPE_NAME"

    type_name_id: Mapped[int] = mapped_column(primary_key=True)
    type_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)


class TagTypeFormatMapping(Base):
    __tablename__ = "TAG_TYPE_FORMAT_MAPPING"

    format_id: Mapped[int] = mapped_column(
        ForeignKey("TAG_FORMATS.format_id"), primary_key=True
    )
    type_id: Mapped[int] = mapped_column(primary_key=True)
    type_name_id: Mapped[int] = mapped_column(ForeignKey("TAG_TYPE_NAME.type_name_id"))
    description: Mapped[Optional[str]] = mapped_column(nullable=True)

    type_name: Mapped["TagTypeName"] = relationship()
    # overlaps パラメータを追加して警告を解消
    statuses: Mapped[list["TagStatus"]] = relationship(
        back_populates="type_mapping",
        overlaps="tags_status",  # 重複を明示的に許可
        viewonly=True,  # 読み取り専用に設定
    )


class TagStatus(Base):
    __tablename__ = "TAG_STATUS"

    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"), primary_key=True)
    format_id: Mapped[int] = mapped_column(
        ForeignKey("TAG_FORMATS.format_id"), primary_key=True
    )
    type_id: Mapped[int] = mapped_column()
    alias: Mapped[bool] = mapped_column(Boolean, nullable=False)
    preferred_tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )

    # リレーションシップの定義
    tag: Mapped["Tag"] = relationship(
        foreign_keys=[tag_id], back_populates="formats_status"
    )
    format: Mapped["TagFormat"] = relationship(
        back_populates="tags_status",
        overlaps="type_mapping,statuses",  # 重複を明示的に許可
    )
    preferred_tag: Mapped["Tag"] = relationship(
        foreign_keys=[preferred_tag_id], back_populates="preferred_by"
    )
    type_mapping: Mapped["TagTypeFormatMapping"] = relationship(
        "TagTypeFormatMapping",
        primaryjoin="and_(TagStatus.format_id == TagTypeFormatMapping.format_id, "
        "TagStatus.type_id == TagTypeFormatMapping.type_id)",
        back_populates="statuses",
        overlaps="format,tags_status",  # 重複を明示的に許可
        viewonly=True,  # 読み取り専用に設定
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


class TagUsageCounts(Base):
    """タグの使用回数を管理するテーブル

    このテーブルはTAGSとTAG_FORMATSの両方を親に持ち、
    それぞれのタグのフォーマット別使用回数を記録します。
    """

    __tablename__ = "TAG_USAGE_COUNTS"

    # 複合主キーの定義
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

    # テーブル全体の制約とインデックス
    __table_args__ = (
        UniqueConstraint("tag_id", "format_id", name="uix_tag_format"),
        Index("idx_tag_id", "tag_id"),  # パフォーマンス向上のためのインデックス
        Index("idx_format_id", "format_id"),  # パフォーマンス向上のためのインデックス
    )


class TagTranslation(Base):
    __tablename__ = "TAG_TRANSLATIONS"

    translation_id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("TAGS.tag_id"))
    language: Mapped[Optional[str]] = mapped_column()
    translation: Mapped[Optional[str]] = mapped_column()
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )

    # Relationship
    tag: Mapped["Tag"] = relationship(back_populates="translations")

    __table_args__ = (
        UniqueConstraint(
            "tag_id", "language", "translation", name="uix_tag_lang_trans"
        ),
    )


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
            self.engine = create_engine(
                f"sqlite:///{db_path.absolute()}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )

        self.sessionmaker = sessionmaker(bind=self.engine)

        # セッションの設定
        if session is not None:
            self.session = session
        else:
            self.sessionmaker = sessionmaker(bind=self.engine)
            self.session = self.create_session()

        if init_master:
            self.init_master_data()

        # デフォルトの場合のみテーブルとマスターデータを作成
        if init_master:
            self.create_tables()
            self.init_master_data()

    def create_session(self) -> Session:
        session = self.sessionmaker()
        self._sessions.add(session)
        return session

    def init_master_data(self):
        """マスターデータの初期化をまとめて実行"""
        self.init_tagformat()
        self.init_tagtypename()
        self.init_tagtypeformatmapping()

    def create_tables(self):
        """テーブルの作成"""
        Base.metadata.create_all(self.engine)

    @classmethod
    def create_test_instance(cls, engine: Engine) -> "TagDatabase":
        """テスト用のインスタンスを作成

        Args:
            engine: テスト用のエンジン

        Returns:
            TagDatabase: テスト用のインスタンス
        """
        return cls(engine=engine, init_master=False)

    def cleanup(self):
        """リソースのクリーンアップ"""
        for session in list(self._sessions):
            if session:
                try:
                    session._close_impl(invalidate=True)
                except Exception as e:
                    self.logger.error(f"セッションのクローズ中にエラー: {e}")
                finally:
                    self._sessions.discard(session)

    def __del__(self):
        """デストラクタでクリーンアップを実行"""
        self.cleanup()

    def init_tagformat(self):
        """Initialize format data that should be registered at creation"""
        initial_data = [
            TagFormat(format_id=0, format_name="unknown", description=""),
            TagFormat(format_id=1, format_name="danbooru", description=""),
            TagFormat(format_id=2, format_name="e621", description=""),
            TagFormat(format_id=3, format_name="derpibooru", description=""),
        ]
        session = self.create_session()
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
        """Initialize tag type names"""
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
        session = self.create_session()
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
        """Initialize tag type format mappings"""
        initial_data = [
            # Format 0 (unknown)
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
        session = self.create_session()
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

    def get_formatnames(self):
        """Test function to get TAG_TYPE_NAME table"""
        query = "SELECT * FROM TAG_TYPE_NAME"
        df = pl.read_database(query, connection=self.engine)
        print(df)


if __name__ == "__main__":
    db = TagDatabase()
    db.get_formatnames()
