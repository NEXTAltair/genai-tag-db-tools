"""旧 user DB スキーマから overlay スキーマへのデータ移行モジュール。

旧 user DB は Base (TAGS/TAG_STATUS/TAG_TRANSLATIONS/TAG_USAGE_COUNTS) を
直接使用していた。overlay スキーマ (UserOverlayBase) への移行処理を提供する。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.schema import USER_TAG_ID_OFFSET

import logging

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """移行処理の結果を保持するデータクラス。"""

    tags_migrated: int = 0
    status_migrated: int = 0
    translations_migrated: int = 0
    usage_migrated: int = 0
    backup_path: Path | None = None
    dry_run: bool = False
    warnings: list[str] = field(default_factory=list)


def detect_legacy_schema(engine: Engine) -> bool:
    """user DB に旧 TAGS テーブルが存在してデータがある場合 True を返す。

    移行済み DB は USER_TAGS にデータが入っているため False を返す（2 回目以降の
    migrate 呼び出しで重複バックアップが作成されるのを防ぐ）。

    Args:
        engine: 検査対象の SQLAlchemy Engine。

    Returns:
        未移行の旧スキーマが存在すれば True、そうでなければ False。
    """
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if "TAGS" not in table_names:
        return False

    with engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(*) FROM TAGS")).fetchone()
        tags_count = row[0] if row else 0

    if tags_count == 0:
        return False

    # USER_TAGS が既にデータを持つ場合は移行済みとみなす
    if "USER_TAGS" in table_names:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT COUNT(*) FROM USER_TAGS")).fetchone()
            user_tags_count = row[0] if row else 0
        if user_tags_count > 0:
            return False

    return True


def backup_user_db(db_path: Path) -> Path:
    """user DB のバックアップを作成する。

    Args:
        db_path: バックアップ元の DB ファイルパス。

    Returns:
        作成したバックアップファイルのパス。
        ファイル名: {stem}_backup_{YYYYMMDD_HHMMSS}.sqlite
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.stem}_backup_{timestamp}.sqlite"
    shutil.copy2(db_path, backup_path)
    logger.info("user DB バックアップ作成: %s", backup_path)
    return backup_path


def migrate_legacy_to_overlay(
    engine: Engine,
    db_path: Path | None = None,
    *,
    backup: bool = True,
    dry_run: bool = False,
) -> MigrationResult:
    """旧スキーマから overlay テーブルへデータを移行する。

    旧 TAGS テーブルのデータを USER_TAGS へ、
    TAG_STATUS を USER_TAG_STATUS_PATCH へ、
    TAG_TRANSLATIONS を USER_TAG_TRANSLATION_PATCH へ、
    TAG_USAGE_COUNTS を USER_TAG_USAGE_PATCH へそれぞれ移行する。

    tag_id は USER_TAG_ID_OFFSET (1_000_000_000) を加算して再マッピングする。

    Args:
        engine: 移行対象 DB の SQLAlchemy Engine。
        db_path: DB ファイルパス。backup=True 時に必要。
        backup: True の場合、移行前にバックアップを作成する。
        dry_run: True の場合、INSERT せずに結果のみ返す。

    Returns:
        MigrationResult: 移行件数と警告のサマリー。
    """
    result = MigrationResult(dry_run=dry_run)

    # バックアップ作成
    if backup and db_path is not None and db_path.exists():
        result.backup_path = backup_user_db(db_path)

    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with Session() as session:
        # --- TAGS → USER_TAGS ---
        try:
            old_tags = session.execute(
                text("SELECT tag_id, source_tag, tag, created_at, updated_at FROM TAGS")
            ).fetchall()
        except OperationalError:
            result.warnings.append("TAGS テーブルが存在しません。スキップします。")
            old_tags = []

        # old_tag_id → new_tag_id のマッピングテーブル
        id_map: dict[int, int] = {row[0]: row[0] + USER_TAG_ID_OFFSET for row in old_tags}

        if not dry_run:
            for row in old_tags:
                old_id, source_tag, tag, created_at, updated_at = row
                new_id = id_map[old_id]
                session.execute(
                    text(
                        "INSERT OR IGNORE INTO USER_TAGS "
                        "(tag_id, source_tag, tag, created_at, updated_at) "
                        "VALUES (:tag_id, :source_tag, :tag, :created_at, :updated_at)"
                    ),
                    {
                        "tag_id": new_id,
                        "source_tag": source_tag,
                        "tag": tag,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    },
                )

            # INSERT OR IGNORE 衝突後に id_map を実際の tag_id で更新する。
            # tag テキストが既存 USER_TAGS と衝突した場合、実 tag_id はオフセット値と異なる。
            for old_row in old_tags:
                old_id, _, tag, _, _ = old_row
                actual = session.execute(
                    text("SELECT tag_id FROM USER_TAGS WHERE tag = :tag"),
                    {"tag": tag},
                ).first()
                if actual is not None and actual[0] != id_map[old_id]:
                    result.warnings.append(
                        f"Tag '{tag}': USER_TAGS 衝突のため id_map を更新 "
                        f"({id_map[old_id]} → {actual[0]})"
                    )
                    id_map[old_id] = actual[0]

        result.tags_migrated = len(old_tags)

        # --- TAG_STATUS → USER_TAG_STATUS_PATCH ---
        try:
            old_statuses = session.execute(
                text(
                    "SELECT tag_id, format_id, type_id, alias, preferred_tag_id, "
                    "deprecated, deprecated_at, created_at, updated_at "
                    "FROM TAG_STATUS"
                )
            ).fetchall()
        except OperationalError:
            result.warnings.append("TAG_STATUS テーブルが存在しません。スキップします。")
            old_statuses = []

        if not dry_run:
            for row in old_statuses:
                (
                    old_tag_id,
                    format_id,
                    type_id,
                    alias,
                    old_preferred_tag_id,
                    deprecated,
                    deprecated_at,
                    created_at,
                    updated_at,
                ) = row

                new_tag_id = id_map.get(old_tag_id, old_tag_id + USER_TAG_ID_OFFSET)

                # CHECK 制約:
                # alias=0 → preferred_scope=target_scope AND preferred_tag_id=target_tag_id
                # alias=1 → NOT (preferred_scope=target_scope AND preferred_tag_id=target_tag_id)
                if not alias:
                    # alias=False: preferred_tag_id は必ず self を指す (CHECK 制約)
                    preferred_scope = "user"
                    preferred_tag_id = new_tag_id
                elif old_preferred_tag_id in id_map:
                    # alias=True かつ preferred が user TAGS 内 → user scope
                    preferred_scope = "user"
                    preferred_tag_id = id_map[old_preferred_tag_id]
                else:
                    # alias=True かつ preferred が user TAGS にない → base DB のタグと仮定
                    preferred_scope = "base"
                    preferred_tag_id = old_preferred_tag_id
                    result.warnings.append(
                        f"TAG_STATUS tag_id={old_tag_id}: preferred_tag_id={old_preferred_tag_id} "
                        "が user TAGS に存在しないため preferred_scope='base' として移行します。"
                    )

                session.execute(
                    text(
                        "INSERT OR IGNORE INTO USER_TAG_STATUS_PATCH "
                        "(target_scope, target_tag_id, format_id, type_id, alias, "
                        "preferred_scope, preferred_tag_id, deprecated, deprecated_at, "
                        "created_at, updated_at) "
                        "VALUES (:target_scope, :target_tag_id, :format_id, :type_id, :alias, "
                        ":preferred_scope, :preferred_tag_id, :deprecated, :deprecated_at, "
                        ":created_at, :updated_at)"
                    ),
                    {
                        "target_scope": "user",
                        "target_tag_id": new_tag_id,
                        "format_id": format_id,
                        "type_id": type_id,
                        "alias": 1 if alias else 0,
                        "preferred_scope": preferred_scope,
                        "preferred_tag_id": preferred_tag_id,
                        "deprecated": 1 if deprecated else 0,
                        "deprecated_at": deprecated_at,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    },
                )
        result.status_migrated = len(old_statuses)

        # --- TAG_TRANSLATIONS → USER_TAG_TRANSLATION_PATCH ---
        try:
            old_translations = session.execute(
                text(
                    "SELECT tag_id, language, translation, created_at, updated_at "
                    "FROM TAG_TRANSLATIONS"
                )
            ).fetchall()
        except OperationalError:
            result.warnings.append("TAG_TRANSLATIONS テーブルが存在しません。スキップします。")
            old_translations = []

        skipped_translations = 0
        if not dry_run:
            for row in old_translations:
                old_tag_id, language, translation, created_at, updated_at = row
                new_tag_id = id_map.get(old_tag_id, old_tag_id + USER_TAG_ID_OFFSET)

                # NULL の language / translation は USER_TAG_TRANSLATION_PATCH の
                # Mapped[str] (nullable=False) に挿入できないためスキップする。
                # "" への変換は SQLite UNIQUE 制約との整合性が崩れるため行わない。
                if language is None or translation is None:
                    result.warnings.append(
                        f"TAG_TRANSLATIONS tag_id={old_tag_id}: "
                        "language または translation が NULL のためスキップします。"
                    )
                    skipped_translations += 1
                    continue

                session.execute(
                    text(
                        "INSERT OR IGNORE INTO USER_TAG_TRANSLATION_PATCH "
                        "(target_scope, target_tag_id, language, translation, "
                        "created_at, updated_at) "
                        "VALUES (:target_scope, :target_tag_id, :language, :translation, "
                        ":created_at, :updated_at)"
                    ),
                    {
                        "target_scope": "user",
                        "target_tag_id": new_tag_id,
                        "language": language,
                        "translation": translation,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    },
                )
        result.translations_migrated = len(old_translations) - skipped_translations

        # --- TAG_USAGE_COUNTS → USER_TAG_USAGE_PATCH ---
        try:
            old_usages = session.execute(
                text(
                    "SELECT tag_id, format_id, count, created_at, updated_at "
                    "FROM TAG_USAGE_COUNTS"
                )
            ).fetchall()
        except OperationalError:
            result.warnings.append("TAG_USAGE_COUNTS テーブルが存在しません。スキップします。")
            old_usages = []

        if not dry_run:
            for row in old_usages:
                old_tag_id, format_id, count, created_at, updated_at = row
                new_tag_id = id_map.get(old_tag_id, old_tag_id + USER_TAG_ID_OFFSET)

                session.execute(
                    text(
                        "INSERT OR IGNORE INTO USER_TAG_USAGE_PATCH "
                        "(target_scope, target_tag_id, format_id, count, "
                        "created_at, updated_at) "
                        "VALUES (:target_scope, :target_tag_id, :format_id, :count, "
                        ":created_at, :updated_at)"
                    ),
                    {
                        "target_scope": "user",
                        "target_tag_id": new_tag_id,
                        "format_id": format_id,
                        "count": count,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    },
                )
        result.usage_migrated = len(old_usages)

        if not dry_run:
            session.commit()

    logger.info(
        "legacy user DB 移行完了: tags=%d, status=%d, translations=%d, usage=%d, dry_run=%s",
        result.tags_migrated,
        result.status_migrated,
        result.translations_migrated,
        result.usage_migrated,
        result.dry_run,
    )
    return result
