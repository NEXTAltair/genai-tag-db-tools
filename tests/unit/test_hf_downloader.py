import json
from pathlib import Path

import pytest

from genai_tag_db_tools.db.runtime import get_database_path
from genai_tag_db_tools.io.hf_downloader import (
    HFDatasetSpec,
    default_cache_dir,
    download_hf_dataset_file,
    download_with_fallback,
    ensure_db_ready,
)

pytestmark = pytest.mark.db_tools


def test_default_cache_dir_points_to_app_cache():
    cache_dir = default_cache_dir()
    assert "genai-tag-db-tools" in str(cache_dir)


def test_download_requires_dest_dir():
    spec = HFDatasetSpec(repo_id="dummy", filename="db.sqlite")
    with pytest.raises(ValueError):
        download_hf_dataset_file(spec, dest_dir=None)


def test_download_with_fallback_uses_cached_when_etag_matches(monkeypatch, tmp_path: Path) -> None:
    spec = HFDatasetSpec(repo_id="dummy/repo", filename="db.sqlite")
    cached = tmp_path / "db.sqlite"
    cached.write_text("")

    manifest_dir = tmp_path / "metadata"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "dummy__repo__db.sqlite.json"
    manifest_path.write_text(
        '{"etag": "abc123", "path": "' + str(cached).replace("\\", "/") + '"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader._fetch_remote_etag",
        lambda *_args, **_kwargs: "abc123",
    )

    def fail_download(*_args, **_kwargs):  # pragma: no cover - should not run
        raise AssertionError("download_hf_dataset_file should not be called")

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader.download_hf_dataset_file",
        fail_download,
    )

    result = download_with_fallback(spec, dest_dir=tmp_path)
    assert result == cached


def test_download_with_fallback_uses_cached_when_offline(monkeypatch, tmp_path: Path) -> None:
    spec = HFDatasetSpec(repo_id="dummy/repo", filename="db.sqlite")
    cached = tmp_path / "db.sqlite"
    cached.write_text("")

    manifest_dir = tmp_path / "metadata"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "dummy__repo__db.sqlite.json"
    manifest_path.write_text(
        '{"etag": "old", "path": "' + str(cached).replace("\\", "/") + '"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader._fetch_remote_etag",
        lambda *_args, **_kwargs: None,
    )

    def fail_download(*_args, **_kwargs):  # pragma: no cover - should not run
        raise AssertionError("download_hf_dataset_file should not be called")

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader.download_hf_dataset_file",
        fail_download,
    )

    result = download_with_fallback(spec, dest_dir=tmp_path)
    assert result == cached


def test_download_with_fallback_falls_back_on_download_error(monkeypatch, tmp_path: Path) -> None:
    spec = HFDatasetSpec(repo_id="dummy/repo", filename="db.sqlite")
    cached = tmp_path / "db.sqlite"
    cached.write_text("")

    manifest_dir = tmp_path / "metadata"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "dummy__repo__db.sqlite.json"
    manifest_path.write_text(
        '{"etag": "old", "path": "' + str(cached).replace("\\", "/") + '"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader._fetch_remote_etag",
        lambda *_args, **_kwargs: "new",
    )

    def fail_download(*_args, **_kwargs):
        raise RuntimeError("network error")

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader.download_hf_dataset_file",
        fail_download,
    )

    result = download_with_fallback(spec, dest_dir=tmp_path)
    assert result == cached


def test_download_with_fallback_updates_manifest_on_success(monkeypatch, tmp_path: Path) -> None:
    spec = HFDatasetSpec(repo_id="dummy/repo", filename="db.sqlite")
    resolved = tmp_path / "fresh.sqlite"
    resolved.write_text("")

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader._fetch_remote_etag",
        lambda *_args, **_kwargs: "new-etag",
    )

    def fake_download(*_args, **_kwargs):
        return resolved

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader.download_hf_dataset_file",
        fake_download,
    )

    result = download_with_fallback(spec, dest_dir=tmp_path)
    assert result == resolved

    manifest_path = tmp_path / "metadata" / "dummy__repo__db.sqlite.json"
    assert manifest_path.exists()
    content = manifest_path.read_text(encoding="utf-8")
    assert "new-etag" in content
    manifest = json.loads(content)
    assert Path(manifest["path"]) == resolved


def test_ensure_db_ready_sets_runtime(monkeypatch, tmp_path: Path):
    fake_db = tmp_path / "db.sqlite"
    fake_db.write_text("")

    def fake_download(*_args, **_kwargs):
        return fake_db

    monkeypatch.setattr("genai_tag_db_tools.io.hf_downloader.download_with_fallback", fake_download)

    spec = HFDatasetSpec(repo_id="dummy", filename="db.sqlite")
    result = ensure_db_ready(spec, dest_dir=tmp_path)

    assert result == fake_db
    assert get_database_path() == fake_db
