from __future__ import annotations

import hashlib
from pathlib import Path

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


def test_ensure_db_returns_fresh_download(monkeypatch, tmp_path):
    """ensure_db()が新規ダウンロード時にcached=Falseを返すことを確認。"""
    payload = b"abc"
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(payload)

    request = _build_request(tmp_path, "org/db", "db.sqlite")

    def fake_download_with_offline_fallback(spec, *, token=None):
        return db_path, False  # is_cached=False

    monkeypatch.setattr(
        hf_downloader, "download_with_offline_fallback", fake_download_with_offline_fallback
    )

    result = core_api.ensure_db(request)
    assert result.cached is False
    assert result.sha256 == _hash_bytes(payload)
    assert Path(result.db_path) == db_path


def test_ensure_db_returns_cached_download(monkeypatch, tmp_path):
    """ensure_db()がキャッシュ使用時にcached=Trueを返すことを確認。"""
    payload = b"xyz"
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(payload)

    request = _build_request(tmp_path, "org/db", "db.sqlite")

    def fake_download_with_offline_fallback(spec, *, token=None):
        return db_path, True  # is_cached=True

    monkeypatch.setattr(
        hf_downloader, "download_with_offline_fallback", fake_download_with_offline_fallback
    )

    result = core_api.ensure_db(request)
    assert result.cached is True
    assert result.sha256 == _hash_bytes(payload)


def test_ensure_databases_returns_cached_status_per_spec(monkeypatch, tmp_path):
    """ensure_databases()が各DBのキャッシュ状態を正しく返すことを確認。"""
    db_a = tmp_path / "a.sqlite"
    db_b = tmp_path / "b.sqlite"
    db_a.write_bytes(b"a")
    db_b.write_bytes(b"bb")

    req_a = _build_request(tmp_path, "org/a", "a.sqlite")
    req_b = _build_request(tmp_path, "org/b", "b.sqlite")

    call_count = [0]
    paths_and_cached = [(db_a, True), (db_b, False)]

    def fake_download_with_offline_fallback(spec, *, token=None):
        result = paths_and_cached[call_count[0]]
        call_count[0] += 1
        return result

    monkeypatch.setattr(
        hf_downloader, "download_with_offline_fallback", fake_download_with_offline_fallback
    )

    results = core_api.ensure_databases([req_a, req_b])
    assert [r.cached for r in results] == [True, False]
    assert results[0].sha256 == _hash_bytes(b"a")
    assert results[1].sha256 == _hash_bytes(b"bb")


def test_search_tags_filters_and_maps():
    rows = [
        {
            "tag": "cat",
            "source_tag": "cat",
            "format_name": "danbooru",
            "type_id": 1,
            "type_name": "general",
            "alias": False,
            "deprecated": False,
            "usage_count": 100,
            "translations": None,
            "format_statuses": {"danbooru": {"status": "active"}},
        },
        {
            "tag": "kitty",
            "source_tag": "kitty",
            "format_name": "danbooru",
            "type_id": 2,
            "type_name": "artist",
            "alias": False,
            "deprecated": True,
            "usage_count": 50,
            "translations": None,
            "format_statuses": {"danbooru": {"status": "active"}},
        },
        {
            "tag": "dog",
            "source_tag": "dog",
            "format_name": "e621",
            "type_id": 2,
            "type_name": "artist",
            "alias": True,
            "deprecated": False,
            "usage_count": 80,
            "translations": None,
            "format_statuses": {"e621": {"status": "active"}},
        },
        {
            "tag": "bunny",
            "source_tag": "bunny",
            "format_name": "danbooru",
            "type_id": 2,
            "type_name": "artist",
            "alias": False,
            "deprecated": False,
            "usage_count": 120,
            "translations": None,
            "format_statuses": {"danbooru": {"status": "active"}},
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
            type_id=2,
            type_name="artist",
            alias=False,
            deprecated=False,
            usage_count=120,
            translations=None,
            format_statuses={"danbooru": {"status": "active"}},
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
