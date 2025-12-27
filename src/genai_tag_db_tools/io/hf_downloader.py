from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HFDatasetSpec:
    repo_id: str
    filename: str
    revision: str | None = None


def default_cache_dir() -> Path:
    """ユーザーDB配置用の既定ディレクトリを返す。

    Note:
        HF標準キャッシュは HF_HOME 環境変数で制御されます。
        このディレクトリはユーザーDB (user_tags.sqlite) の保存先です。
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "genai-tag-db-tools"


def download_hf_dataset_file(
    spec: HFDatasetSpec,
    *,
    token: str | None = None,
    local_files_only: bool = False,
) -> Path:
    """HF Datasetから指定ファイルをダウンロードする（標準キャッシュ使用）。

    Args:
        spec: HFデータセット参照情報
        token: HFアクセストークン
        local_files_only: オフラインモード（キャッシュのみ使用）

    Returns:
        Path: ダウンロードされたファイルへのパス（HFキャッシュ内symlink）
    """
    logger.info("HFダウンロード開始: %s/%s", spec.repo_id, spec.filename)

    local_path = hf_hub_download(
        repo_id=spec.repo_id,
        repo_type="dataset",
        filename=spec.filename,
        revision=spec.revision,
        token=token,
        local_files_only=local_files_only,
    )
    resolved = Path(local_path).resolve()
    logger.info("HFダウンロード完了: %s", resolved)
    return resolved


def download_with_offline_fallback(
    spec: HFDatasetSpec,
    *,
    token: str | None = None,
) -> tuple[Path, bool]:
    """オフラインフォールバック付きでダウンロード。

    Args:
        spec: HFデータセット参照情報
        token: HFアクセストークン

    Returns:
        tuple[Path, bool]: (resolved_path, is_cached)
            - resolved_path: ダウンロードされたファイルのパス
            - is_cached: オフラインモードでキャッシュを使用したか
    """
    try:
        # Try normal download first
        resolved = download_hf_dataset_file(spec, token=token, local_files_only=False)
        return resolved, False
    except Exception as network_exc:
        logger.warning("Network error, trying cached version: %s", network_exc)
        try:
            # Fallback to cached version
            resolved = download_hf_dataset_file(spec, token=token, local_files_only=True)
            logger.info("Using cached version: %s", resolved)
            return resolved, True
        except Exception as cache_exc:
            logger.error("No cached version available: %s", cache_exc)
            raise RuntimeError(
                f"Failed to download {spec.repo_id}/{spec.filename} and no cached version available"
            ) from network_exc


def ensure_db_ready(
    spec: HFDatasetSpec,
    *,
    token: str | None = None,
) -> Path:
    """DBファイルを取得し、runtime を初期化する。

    Args:
        spec: HFデータセット参照情報
        token: HFアクセストークン

    Returns:
        Path: 取得したDBファイルへのパス
    """
    from genai_tag_db_tools.db.runtime import init_engine, set_database_path

    db_path, _is_cached = download_with_offline_fallback(spec, token=token)

    set_database_path(db_path)
    init_engine(db_path)
    return db_path


def ensure_databases_ready(
    specs: list[HFDatasetSpec],
    *,
    token: str | None = None,
) -> list[Path]:
    """複数のDBファイルを取得し、base DB一覧として初期化する。

    Args:
        specs: HFデータセット参照情報のリスト
        token: HFアクセストークン

    Returns:
        list[Path]: 取得したDBファイルパスのリスト
    """
    from genai_tag_db_tools.db.runtime import (
        init_engine,
        set_base_database_paths,
        set_database_path,
    )

    if not specs:
        raise ValueError("specs は空にできません。")

    paths: list[Path] = []
    for spec in specs:
        db_path, _is_cached = download_with_offline_fallback(spec, token=token)
        paths.append(db_path)

    set_base_database_paths(paths)
    set_database_path(paths[0])
    init_engine(paths[0])
    return paths
