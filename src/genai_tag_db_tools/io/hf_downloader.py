from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, hf_hub_download

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HFDatasetSpec:
    repo_id: str
    filename: str
    revision: str | None = None


def default_cache_dir() -> Path:
    """ユーザーキャッシュ配下の既定ディレクトリを返す。"""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "genai-tag-db-tools"


def _manifest_key(spec: HFDatasetSpec) -> str:
    safe_repo = spec.repo_id.replace("/", "__")
    safe_file = spec.filename.replace("/", "__")
    return f"{safe_repo}__{safe_file}"


def _manifest_path(dest_dir: Path, spec: HFDatasetSpec) -> Path:
    return dest_dir / "metadata" / f"{_manifest_key(spec)}.json"


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_remote_etag(spec: HFDatasetSpec, token: str | None) -> str | None:
    api = HfApi(token=token)
    try:
        info = api.file_metadata(
            repo_id=spec.repo_id,
            path=spec.filename,
            revision=spec.revision,
            repo_type="dataset",
        )
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning("HF metadata fetch failed: %s", exc)
        return None
    return info.etag


def download_hf_dataset_file(
    spec: HFDatasetSpec, *, dest_dir: Path, token: str | None = None
) -> Path:
    """HF Datasetから指定ファイルをダウンロードする。"""
    if dest_dir is None:
        raise ValueError("dest_dir は必須です。保存先を指定してください。")
    dest_dir.mkdir(parents=True, exist_ok=True)
    logger.info("HFダウンロード開始: %s/%s", spec.repo_id, spec.filename)

    local_path = hf_hub_download(
        repo_id=spec.repo_id,
        repo_type="dataset",
        filename=spec.filename,
        revision=spec.revision,
        token=token,
        local_dir=dest_dir,
        local_dir_use_symlinks=False,
    )
    resolved = Path(local_path).resolve()
    logger.info("HFダウンロード完了: %s", resolved)
    return resolved


def download_with_fallback(
    spec: HFDatasetSpec, *, dest_dir: Path, token: str | None = None
) -> Path:
    """リモートの更新確認とフォールバックを含めてダウンロードする。"""
    if dest_dir is None:
        raise ValueError("dest_dir は必須です。保存先を指定してください。")
    dest_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = _manifest_path(dest_dir, spec)
    manifest = _load_manifest(manifest_path)
    remote_etag = _fetch_remote_etag(spec, token)

    if manifest and remote_etag and manifest.get("etag") == remote_etag:
        cached = Path(manifest.get("path", ""))
        if cached.exists():
            logger.info("HFキャッシュ一致: %s", cached)
            return cached

    if manifest and remote_etag is None:
        cached = Path(manifest.get("path", ""))
        if cached.exists():
            logger.info("HFキャッシュを継続利用: %s", cached)
            return cached

    try:
        resolved = download_hf_dataset_file(spec, dest_dir=dest_dir, token=token)
    except Exception as exc:
        if manifest:
            cached = Path(manifest.get("path", ""))
            if cached.exists():
                logger.warning("HFダウンロード失敗のため既存キャッシュを使用: %s", exc)
                return cached
        raise

    _save_manifest(
        manifest_path,
        {
            "repo_id": spec.repo_id,
            "filename": spec.filename,
            "revision": spec.revision,
            "etag": remote_etag,
            "path": str(resolved),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return resolved


def ensure_db_ready(
    spec: HFDatasetSpec, *, dest_dir: Path, token: str | None = None
) -> Path:
    """DBファイルを取得し、runtime を初期化する。"""
    from genai_tag_db_tools.db.runtime import init_engine, set_database_path

    db_path = download_with_fallback(spec, dest_dir=dest_dir, token=token)
    set_database_path(db_path)
    init_engine(db_path)
    return db_path
