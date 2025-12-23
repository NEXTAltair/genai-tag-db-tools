from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from genai_tag_db_tools import core_api
from genai_tag_db_tools.io import hf_downloader
from genai_tag_db_tools.models import (
    DbCacheConfig,
    DbSourceRef,
    EnsureDbRequest,
    TagRecordPublic,
    TagRegisterRequest,
    TagSearchRequest,
)


class DummyRepo:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.calls: list[dict] = []

    def search_tags(self, keyword: str, **kwargs) -> list[dict]:
        self.calls.append({"keyword": keyword, **kwargs})
        return list(self._rows)


class DummyService:
    def __init__(self) -> None:
        self.called_with: TagRegisterRequest | None = None

    def register_tag(self, request: TagRegisterRequest):
        self.called_with = request
        return type("Result", (), {"created": True})()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_request(tmp_path: Path, repo_id: str, filename: str) -> EnsureDbRequest:
    return EnsureDbRequest(
        source=DbSourceRef(repo_id=repo_id, filename=filename),
        cache=DbCacheConfig(cache_dir=str(tmp_path), token=None),
    )


def test_ensure_db_marks_downloaded_when_manifest_changes(monkeypatch, tmp_path):
    payload = b"abc"
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(payload)

    request = _build_request(tmp_path, "org/db", "db.sqlite")
    spec = hf_downloader.HFDatasetSpec(repo_id="org/db", filename="db.sqlite", revision=None)
    manifest_path = hf_downloader._manifest_path(tmp_path, spec)
    hf_downloader._save_manifest(manifest_path, {"etag": "old", "path": str(db_path)})

    def fake_ensure_db_ready(spec, *, dest_dir, token=None):
        hf_downloader._save_manifest(
            hf_downloader._manifest_path(dest_dir, spec),
            {"etag": "new", "path": str(db_path)},
        )
        return db_path

    monkeypatch.setattr(hf_downloader, "ensure_db_ready", fake_ensure_db_ready)

    result = core_api.ensure_db(request)
    assert result.downloaded is True
    assert result.sha256 == _hash_bytes(payload)
    assert Path(result.db_path) == db_path


def test_ensure_db_marks_not_downloaded_when_manifest_same(monkeypatch, tmp_path):
    payload = b"xyz"
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(payload)

    request = _build_request(tmp_path, "org/db", "db.sqlite")
    spec = hf_downloader.HFDatasetSpec(repo_id="org/db", filename="db.sqlite", revision=None)
    manifest_path = hf_downloader._manifest_path(tmp_path, spec)
    hf_downloader._save_manifest(manifest_path, {"etag": "same", "path": str(db_path)})

    def fake_ensure_db_ready(spec, *, dest_dir, token=None):
        hf_downloader._save_manifest(
            hf_downloader._manifest_path(dest_dir, spec),
            {"etag": "same", "path": str(db_path)},
        )
        return db_path

    monkeypatch.setattr(hf_downloader, "ensure_db_ready", fake_ensure_db_ready)

    result = core_api.ensure_db(request)
    assert result.downloaded is False
    assert result.sha256 == _hash_bytes(payload)


def test_ensure_databases_requires_same_cache_dir(tmp_path):
    req_a = _build_request(tmp_path, "org/a", "a.sqlite")
    req_b = EnsureDbRequest(
        source=DbSourceRef(repo_id="org/b", filename="b.sqlite"),
        cache=DbCacheConfig(cache_dir=str(tmp_path / "other"), token=None),
    )
    with pytest.raises(ValueError):
        core_api.ensure_databases([req_a, req_b])


def test_ensure_databases_reports_downloaded_per_spec(monkeypatch, tmp_path):
    db_a = tmp_path / "a.sqlite"
    db_b = tmp_path / "b.sqlite"
    db_a.write_bytes(b"a")
    db_b.write_bytes(b"bb")

    req_a = _build_request(tmp_path, "org/a", "a.sqlite")
    req_b = _build_request(tmp_path, "org/b", "b.sqlite")
    spec_a = hf_downloader.HFDatasetSpec("org/a", "a.sqlite", None)
    spec_b = hf_downloader.HFDatasetSpec("org/b", "b.sqlite", None)

    hf_downloader._save_manifest(
        hf_downloader._manifest_path(tmp_path, spec_a),
        {"etag": "old-a", "path": str(db_a)},
    )
    hf_downloader._save_manifest(
        hf_downloader._manifest_path(tmp_path, spec_b),
        {"etag": "old-b", "path": str(db_b)},
    )

    def fake_ensure_databases_ready(specs, *, dest_dir, token=None):
        hf_downloader._save_manifest(
            hf_downloader._manifest_path(dest_dir, spec_a),
            {"etag": "old-a", "path": str(db_a)},
        )
        hf_downloader._save_manifest(
            hf_downloader._manifest_path(dest_dir, spec_b),
            {"etag": "new-b", "path": str(db_b)},
        )
        return [db_a, db_b]

    monkeypatch.setattr(hf_downloader, "ensure_databases_ready", fake_ensure_databases_ready)

    results = core_api.ensure_databases([req_a, req_b])
    assert [r.downloaded for r in results] == [False, True]
    assert results[0].sha256 == _hash_bytes(b"a")
    assert results[1].sha256 == _hash_bytes(b"bb")


def test_search_tags_filters_and_maps():
    rows = [
        {
            "tag": "cat",
            "source_tag": "cat",
            "format_name": "danbooru",
            "type_name": "general",
            "alias": False,
        },
        {
            "tag": "kitty",
            "source_tag": "kitty",
            "format_name": "danbooru",
            "type_name": "artist",
            "alias": False,
            "deprecated": True,
        },
        {
            "tag": "dog",
            "source_tag": "dog",
            "format_name": "e621",
            "type_name": "artist",
            "alias": True,
        },
        {
            "tag": "bunny",
            "source_tag": "bunny",
            "format_name": "danbooru",
            "type_name": "artist",
            "alias": False,
        },
    ]
    repo = DummyRepo(rows)
    request = TagSearchRequest(
        query="bunny",
        format_names=["danbooru"],
        type_names=["artist"],
        include_aliases=False,
        include_deprecated=False,
    )
    result = core_api.search_tags(repo, request)
    assert result.items == [
        TagRecordPublic(
            tag="bunny",
            source_tag="bunny",
            format_name="danbooru",
            type_name="artist",
            alias=False,
        )
    ]
    assert result.total == 1


def test_register_tag_delegates():
    service = DummyService()
    request = TagRegisterRequest(
        tag="cat",
        source_tag="cat",
        format_name="danbooru",
        type_name="general",
        alias=False,
        preferred_tag=None,
        translations=None,
    )
    result = core_api.register_tag(service, request)
    assert service.called_with == request
    assert result.created is True
