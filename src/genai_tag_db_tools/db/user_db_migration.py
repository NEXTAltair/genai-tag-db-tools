"""旧 user DB スキーマから overlay スキーマへのデータ移行モジュール。

旧 user DB は Base (TAGS/TAG_STATUS/TAG_TRANSLATIONS/TAG_USAGE_COUNTS) を
直接使用していた。overlay スキーマ (UserOverlayBase) への移行処理を提供する。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from genai_tag_db_tools.db.schema import USER_TAG_ID_OFFSET

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

    移行完了後は TAGS テーブルのデータが DELETE されるため、
    2 回目以降の呼び出しでは False を返す（重複バックアップ防止）。

    Args:
        engine: 検査対象の SQLAlchemy Engine。

    Returns:
        未移行の旧スキーマデータが存在すれば True、そうでなければ False。
    """
    inspector = inspect(engine)
    if "TAGS" not in inspector.get_table_names():
        return False

    with engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(*) FROM TAGS")).fetchone()
        count = row[0] if row else 0

    return count > 0


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
    # SQLite backup API を使用してバックアップを作成する。
    # WAL モード DB でも -wal/-shm の未フラッシュページを含む一貫したスナップショットを取得できる。
    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(backup_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    logger.info("user DB バックアップ作成: %s", backup_path)
    return backup_path


def _resolve_free_tag_id(session: object, candidate_id: int) -> int:
    """candidate_id が USER_TAGS で使用済みの場合、空き ID を返す。

    Args:
        session: SQLAlchemy セッション。
        candidate_id: 最初に試みる tag_id。

    Returns:
        使用可能な tag_id (>= USER_TAG_ID_OFFSET)。
    """
    from sqlalchemy.orm import Session as _Session

    s: _Session = session  # type: ignore[assignment]
    taken = s.execute(
        text("SELECT 1 FROM USER_TAGS WHERE tag_id = :id"),
        {"id": candidate_id},
    ).first()
    if taken is None:
        return candidate_id

    # 別タグが candidate_id を使用中 → MAX(tag_id) + 1 を割り当て
    max_row = s.execute(text("SELECT MAX(tag_id) FROM USER_TAGS")).first()
    max_id = max_row[0] if max_row and max_row[0] is not None else USER_TAG_ID_OFFSET - 1
    return max(USER_TAG_ID_OFFSET, max_id + 1)


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
    tag テキスト衝突は INSERT IGNORE でスキップ（id_map を実 tag_id で更新）、
    PK 衝突は別タグが既に OFFSET 後 ID を使用している場合に空き ID を割り当てる。

    移行完了後に旧データテーブルの行を削除する。これにより detect_legacy_schema が
    2 回目以降 False を返し、混在 DB (TAGS + USER_TAGS が両方存在する DB) でも
    正しく「移行済み」と判断できる。

    Args:
        engine: 移行対象 DB の SQLAlchemy Engine。
        db_path: DB ファイルパス。backup=True 時に必要。
        backup: True の場合、移行前にバックアップを作成する。
        dry_run: True の場合、INSERT / DELETE をせずに件数のみ返す。

    Returns:
        MigrationResult: 移行件数と警告のサマリー。
    """
    result = MigrationResult(dry_run=dry_run)

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

        # old_tag_id → new_tag_id のマッピング（初期値はオフセット加算）
        id_map: dict[int, int] = {row[0]: row[0] + USER_TAG_ID_OFFSET for row in old_tags}

        if not dry_run:
            for row in old_tags:
                old_id, source_tag, tag, created_at, updated_at = row

                # tag テキストで既存行を確認（同一タグが既に移行済みの場合）
                existing = session.execute(
                    text("SELECT tag_id FROM USER_TAGS WHERE tag = :tag"),
                    {"tag": tag},
                ).first()
                if existing is not None:
                    # 既存行あり → id_map を実 tag_id で更新してスキップ
                    if existing[0] != id_map[old_id]:
                        result.warnings.append(
                            f"Tag '{tag}' は既に USER_TAGS に存在します "
                            f"(tag_id={existing[0]})。id_map を更新します。"
                        )
                    id_map[old_id] = existing[0]
                    continue

                # PK 衝突チェック: offset 後 ID が別タグで使用済みの場合は空き ID を取得
                candidate_id = id_map[old_id]
                free_id = _resolve_free_tag_id(session, candidate_id)
                if free_id != candidate_id:
                    result.warnings.append(
                        f"Tag '{tag}' の offset ID {candidate_id} は別タグと PK 衝突のため "
                        f"{free_id} を割り当てます。"
                    )
                    id_map[old_id] = free_id

                session.execute(
                    text(
                        "INSERT INTO USER_TAGS "
                        "(tag_id, source_tag, tag, created_at, updated_at) "
                        "VALUES (:tag_id, :source_tag, :tag, :created_at, :updated_at)"
                    ),
                    {
                        "tag_id": id_map[old_id],
                        "source_tag": source_tag,
                        "tag": tag,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    },
                )

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
                    preferred_scope = "user"
                    preferred_tag_id = new_tag_id
                elif old_preferred_tag_id in id_map:
                    # preferred が user TAGS 内 → user scope
                    preferred_scope = "user"
                    preferred_tag_id = id_map[old_preferred_tag_id]
                else:
                    # preferred が user TAGS にない → base DB のタグと仮定
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

                # NULL の language / translation は Mapped[str] (nullable=False) に挿入不可。
                # "" への変換は SQLite UNIQUE 制約との整合性が崩れるためスキップする。
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

        # TAG_FORMATS のユーザー定義エントリを警告（overlay テーブルには移行しない）
        try:
            fmt_count = session.execute(
                text("SELECT COUNT(*) FROM TAG_FORMATS")
            ).scalar_one()
            if fmt_count > 0:
                result.warnings.append(
                    f"TAG_FORMATS に {fmt_count} 件の format 定義があります。"
                    "これらは overlay テーブルへは移行されません。"
                    "旧テーブルを将来削除する際は format メタデータのエクスポートを検討してください。"
                )
        except OperationalError:
            pass

        if not dry_run:
            # 移行済みの旧データを削除する。
            # これにより detect_legacy_schema が 2 回目以降 False を返し、
            # TAGS + USER_TAGS が混在する DB でも「移行済み」と正しく判断できる。
            # FK 制約の順序: TAGS を参照するテーブルを先に削除してから TAGS を削除する。
            # NULL の language/translation 行は無効データ (USER_TAG_TRANSLATION_PATCH に
            # 挿入不可) であり削除する。skipped_translations > 0 の場合は warning を
            # 出力済みで、backup=True (既定値) による復旧が可能。
            for legacy_table in ("TAG_USAGE_COUNTS", "TAG_TRANSLATIONS", "TAG_STATUS", "TAGS"):
                try:
                    session.execute(text(f"DELETE FROM {legacy_table}"))
                except OperationalError:
                    pass
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
