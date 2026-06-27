"""旧 user DB スキーマから overlay スキーマへの移行処理テスト。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.runtime import _create_engine
from genai_tag_db_tools.db.schema import (
    USER_TAG_ID_OFFSET,
    Base,
    Tag,
    TagFormat,
    TagStatus,
    TagTranslation,
    TagTypeFormatMapping,
    TagTypeName,
    TagUsageCounts,
    UserOverlayBase,
)
from genai_tag_db_tools.db.user_db_migration import (
    MigrationResult,
    backup_user_db,
    detect_legacy_schema,
    migrate_legacy_to_overlay,
)

# --- フィクスチャ ---


def _make_engine(db_path: Path):
    """テスト用 SQLite エンジンを作成するヘルパー。"""
    engine = _create_engine(db_path)
    return engine


class TestDetectLegacySchema:
    """detect_legacy_schema のテスト。"""

    def test_empty_db_returns_false(self, tmp_path: Path) -> None:
        """空の user DB は legacy ではない。"""
        db_path = tmp_path / "empty.sqlite"
        engine = _make_engine(db_path)
        # テーブルを何も作成しない
        assert detect_legacy_schema(engine) is False
        engine.dispose()

    def test_db_with_only_overlay_tables_returns_false(self, tmp_path: Path) -> None:
        """overlay テーブルのみの DB は legacy ではない。"""
        db_path = tmp_path / "overlay_only.sqlite"
        engine = _make_engine(db_path)
        UserOverlayBase.metadata.create_all(engine)
        assert detect_legacy_schema(engine) is False
        engine.dispose()

    def test_db_with_populated_tags_table_returns_true(self, tmp_path: Path) -> None:
        """TAGS テーブルにデータがある DB は legacy と判定される。"""
        db_path = tmp_path / "legacy.sqlite"
        engine = _make_engine(db_path)
        Base.metadata.create_all(engine)

        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with Session() as session:
            # 最低限の依存テーブルを作成してから TAGS を挿入
            session.add(Tag(tag_id=1, source_tag="cat", tag="cat"))
            session.commit()

        assert detect_legacy_schema(engine) is True
        engine.dispose()

    def test_db_with_empty_tags_table_returns_false(self, tmp_path: Path) -> None:
        """TAGS テーブルが存在してもデータが空なら False。"""
        db_path = tmp_path / "empty_tags.sqlite"
        engine = _make_engine(db_path)
        Base.metadata.create_all(engine)
        # データは挿入しない
        assert detect_legacy_schema(engine) is False
        engine.dispose()


class TestBackupUserDb:
    """backup_user_db のテスト。"""

    def test_creates_backup_with_timestamp(self, tmp_path: Path) -> None:
        """バックアップファイルが _backup_YYYYMMDD_HHMMSS.sqlite で作成される。"""
        db_path = tmp_path / "user_tags.sqlite"
        engine = _make_engine(db_path)
        Base.metadata.create_all(engine)
        engine.dispose()

        backup_path = backup_user_db(db_path)

        assert backup_path.exists()
        # ファイル名のパターン確認
        pattern = r"user_tags_backup_\d{8}_\d{6}\.sqlite"
        assert re.match(pattern, backup_path.name), f"Unexpected filename: {backup_path.name}"

    def test_backup_is_identical_copy(self, tmp_path: Path) -> None:
        """バックアップファイルが元 DB と同一内容を持つ (WAL 対応 SQLite backup API)。"""
        db_path = tmp_path / "user_tags.sqlite"
        engine = _make_engine(db_path)
        Base.metadata.create_all(engine)
        # サンプルデータを挿入してバックアップ対象を確認
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with Session() as session:
            session.add(Tag(tag_id=1, source_tag="cat", tag="cat"))
            session.commit()
        engine.dispose()

        backup_path = backup_user_db(db_path)

        # バックアップ DB で同一データが読める
        import sqlite3

        conn = sqlite3.connect(str(backup_path))
        row = conn.execute("SELECT tag FROM TAGS WHERE tag_id = 1").fetchone()
        conn.close()
        assert row is not None and row[0] == "cat"


class TestMigrateLegacyToOverlay:
    """migrate_legacy_to_overlay のテスト。"""

    @pytest.fixture()
    def legacy_engine(self, tmp_path: Path):
        """旧スキーマのテスト用 legacy user DB を作成する。

        TAGS、TAG_STATUS、TAG_TRANSLATIONS、TAG_USAGE_COUNTS にサンプルデータを挿入する。
        """
        db_path = tmp_path / "legacy_user.sqlite"
        engine = _make_engine(db_path)

        # 旧スキーマ (Base) と overlay スキーマ (UserOverlayBase) を両方作成
        Base.metadata.create_all(engine)
        UserOverlayBase.metadata.create_all(engine)

        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with Session() as session:
            # 依存テーブルの準備（TAG_STATUS が FORMAT/TYPE を参照するため）
            session.add(TagTypeName(type_name_id=1, type_name="unknown"))
            session.add(TagFormat(format_id=1000, format_name="user_format"))
            session.add(TagTypeFormatMapping(format_id=1000, type_id=0, type_name_id=1))

            # TAGS に tag_id=1, 2 を挿入
            session.add(Tag(tag_id=1, source_tag="cat", tag="cat"))
            session.add(Tag(tag_id=2, source_tag="dog", tag="dog"))
            session.commit()

            # TAG_STATUS に tag_id=1, 2 の行を挿入（alias=False → preferred_tag_id=tag_id）
            session.add(
                TagStatus(
                    tag_id=1,
                    format_id=1000,
                    type_id=0,
                    alias=False,
                    preferred_tag_id=1,
                    deprecated=False,
                )
            )
            session.add(
                TagStatus(
                    tag_id=2,
                    format_id=1000,
                    type_id=0,
                    alias=False,
                    preferred_tag_id=2,
                    deprecated=False,
                )
            )
            session.commit()

            # TAG_TRANSLATIONS に tag_id=1 の翻訳を挿入
            session.add(TagTranslation(tag_id=1, language="ja", translation="ねこ"))
            session.commit()

            # TAG_USAGE_COUNTS に tag_id=1 の使用数を挿入
            session.add(TagUsageCounts(tag_id=1, format_id=1000, count=42))
            session.commit()

        yield engine
        engine.dispose()

    def test_tags_migrated_to_user_tags(self, legacy_engine) -> None:
        """TAGS の行が USER_TAGS に移行される (new_id = old_id + OFFSET)。"""
        result = migrate_legacy_to_overlay(legacy_engine, backup=False)

        assert result.tags_migrated == 2

        Session = sessionmaker(bind=legacy_engine, autoflush=False, autocommit=False)
        with Session() as session:
            rows = session.execute(text("SELECT tag_id, tag FROM USER_TAGS ORDER BY tag_id")).fetchall()

        assert len(rows) == 2
        assert rows[0][0] == 1 + USER_TAG_ID_OFFSET
        assert rows[0][1] == "cat"
        assert rows[1][0] == 2 + USER_TAG_ID_OFFSET
        assert rows[1][1] == "dog"

    def test_status_migrated_to_patch(self, legacy_engine) -> None:
        """TAG_STATUS の行が USER_TAG_STATUS_PATCH に移行される。"""
        result = migrate_legacy_to_overlay(legacy_engine, backup=False)

        assert result.status_migrated == 2

        Session = sessionmaker(bind=legacy_engine, autoflush=False, autocommit=False)
        with Session() as session:
            rows = session.execute(
                text(
                    "SELECT target_scope, target_tag_id, format_id, alias "
                    "FROM USER_TAG_STATUS_PATCH ORDER BY target_tag_id"
                )
            ).fetchall()

        assert len(rows) == 2
        # target_scope が 'user' であること
        assert rows[0][0] == "user"
        # tag_id がオフセットされていること
        assert rows[0][1] == 1 + USER_TAG_ID_OFFSET
        assert rows[1][1] == 2 + USER_TAG_ID_OFFSET

    def test_translations_migrated(self, legacy_engine) -> None:
        """TAG_TRANSLATIONS が USER_TAG_TRANSLATION_PATCH に移行される。"""
        result = migrate_legacy_to_overlay(legacy_engine, backup=False)

        assert result.translations_migrated == 1

        Session = sessionmaker(bind=legacy_engine, autoflush=False, autocommit=False)
        with Session() as session:
            rows = session.execute(
                text(
                    "SELECT target_scope, target_tag_id, language, translation "
                    "FROM USER_TAG_TRANSLATION_PATCH"
                )
            ).fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "user"
        assert rows[0][1] == 1 + USER_TAG_ID_OFFSET
        assert rows[0][2] == "ja"
        assert rows[0][3] == "ねこ"

    def test_usage_migrated(self, legacy_engine) -> None:
        """TAG_USAGE_COUNTS が USER_TAG_USAGE_PATCH に移行される。"""
        result = migrate_legacy_to_overlay(legacy_engine, backup=False)

        assert result.usage_migrated == 1

        Session = sessionmaker(bind=legacy_engine, autoflush=False, autocommit=False)
        with Session() as session:
            rows = session.execute(
                text(
                    "SELECT target_scope, target_tag_id, format_id, count "
                    "FROM USER_TAG_USAGE_PATCH"
                )
            ).fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "user"
        assert rows[0][1] == 1 + USER_TAG_ID_OFFSET
        assert rows[0][3] == 42

    def test_dry_run_does_not_write(self, legacy_engine) -> None:
        """dry_run=True では USER_TAGS に書き込まれない。"""
        result = migrate_legacy_to_overlay(legacy_engine, backup=False, dry_run=True)

        assert result.dry_run is True
        assert result.tags_migrated == 2  # 件数はカウントされる

        Session = sessionmaker(bind=legacy_engine, autoflush=False, autocommit=False)
        with Session() as session:
            rows = session.execute(text("SELECT COUNT(*) FROM USER_TAGS")).fetchone()

        assert rows[0] == 0  # 書き込まれていない

    def test_result_counts_match(self, legacy_engine) -> None:
        """MigrationResult の件数が実際の移行数と一致する。"""
        result = migrate_legacy_to_overlay(legacy_engine, backup=False)

        assert isinstance(result, MigrationResult)
        assert result.tags_migrated == 2
        assert result.status_migrated == 2
        assert result.translations_migrated == 1
        assert result.usage_migrated == 1
        assert result.dry_run is False
        assert result.backup_path is None  # backup=False なので

    def test_backup_created_when_db_path_given(self, tmp_path: Path) -> None:
        """db_path 指定時はバックアップファイルが作成される。"""
        db_path = tmp_path / "user_tags.sqlite"
        engine = _make_engine(db_path)
        Base.metadata.create_all(engine)
        UserOverlayBase.metadata.create_all(engine)

        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with Session() as session:
            session.add(Tag(tag_id=1, source_tag="cat", tag="cat"))
            session.commit()

        result = migrate_legacy_to_overlay(engine, db_path=db_path, backup=True)

        assert result.backup_path is not None
        assert result.backup_path.exists()
        engine.dispose()

    def test_no_backup_when_backup_false(self, tmp_path: Path) -> None:
        """backup=False のときはバックアップが作成されない。"""
        db_path = tmp_path / "user_tags.sqlite"
        engine = _make_engine(db_path)
        Base.metadata.create_all(engine)
        UserOverlayBase.metadata.create_all(engine)

        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with Session() as session:
            session.add(Tag(tag_id=1, source_tag="cat", tag="cat"))
            session.commit()

        result = migrate_legacy_to_overlay(engine, db_path=db_path, backup=False)

        assert result.backup_path is None
        # バックアップファイルが存在しないことを確認
        backup_files = list(tmp_path.glob("*_backup_*.sqlite"))
        assert len(backup_files) == 0
        engine.dispose()

    def test_idempotent_second_run_skips(self, legacy_engine) -> None:
        """移行後に detect_legacy_schema が False を返す（TAGS 削除による冪等性）。"""
        # 1 回目の移行
        result1 = migrate_legacy_to_overlay(legacy_engine, backup=False)
        assert result1.tags_migrated == 2

        # 移行後は TAGS の行が削除されているため detect_legacy_schema が False を返す
        assert not detect_legacy_schema(legacy_engine)

        # 2 回目の直接呼び出しは TAGS が空なので 0 件（重複挿入もなし）
        result2 = migrate_legacy_to_overlay(legacy_engine, backup=False)
        assert result2.tags_migrated == 0

        # USER_TAGS の件数は変わらない（重複挿入なし）
        Session = sessionmaker(bind=legacy_engine, autoflush=False, autocommit=False)
        with Session() as session:
            count_row = session.execute(text("SELECT COUNT(*) FROM USER_TAGS")).fetchone()

        assert count_row[0] == 2

    def test_missing_translations_table_adds_warning(self, tmp_path: Path) -> None:
        """TAG_TRANSLATIONS テーブルが存在しない場合は warnings に追加される。"""
        db_path = tmp_path / "no_translations.sqlite"
        engine = _make_engine(db_path)

        # TAG_TRANSLATIONS を除いた最小限のスキーマを作成
        # (TAG_USAGE_COUNTS, TAG_TRANSLATIONS のみ除外した TAGS を作成)
        UserOverlayBase.metadata.create_all(engine)
        # TAGS テーブルだけ raw SQL で作成
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS TAGS "
                    "(tag_id INTEGER PRIMARY KEY, source_tag TEXT, tag TEXT UNIQUE, "
                    "created_at DATETIME, updated_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO TAGS (tag_id, source_tag, tag) VALUES (1, 'cat', 'cat')"
                )
            )
            conn.commit()

        result = migrate_legacy_to_overlay(engine, backup=False)

        assert result.tags_migrated == 1
        # TAG_STATUS が存在しないので警告が含まれる
        warning_messages = " ".join(result.warnings)
        assert "TAG_STATUS" in warning_messages or "TAG_TRANSLATIONS" in warning_messages
        engine.dispose()
