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
        rows = list(self._rows)
        # repository は実 DB 値で SQL フィルタする
        if kwargs.get("min_usage") is not None:
            rows = [row for row in rows if (row["usage_count"] or 0) >= kwargs["min_usage"]]
        if kwargs.get("max_usage") is not None:
            rows = [row for row in rows if (row["usage_count"] or 0) <= kwargs["max_usage"]]
        if kwargs.get("alias") is not None:
            rows = [row for row in rows if row["alias"] is kwargs["alias"]]
        if kwargs.get("deprecated") is not None:
            rows = [row for row in rows if row["deprecated"] is kwargs["deprecated"]]
        if kwargs.get("format_names"):
            fmts = set(kwargs["format_names"])
            rows = [row for row in rows if any(f in (row.get("format_statuses") or {}) for f in fmts)]
        if kwargs.get("type_names"):
            types = set(kwargs["type_names"])
            rows = [row for row in rows if row["type_name"] in types]
        # build_row 相当の忠実化: 単一 concrete format でない呼び出しでは format 依存フィールドが
        # 0/False/"" で返る (format_id=0)。これを再現しないと #45 の二重フィルタ不整合が
        # テストで顕在化しない。
        fmt_names = kwargs.get("format_names") or (
            [kwargs["format_name"]] if kwargs.get("format_name") else []
        )
        if len(fmt_names) != 1:
            rows = [{**row, "usage_count": 0, "deprecated": False, "type_name": ""} for row in rows]
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit")
        rows = rows[offset:] if offset else rows
        return rows[:limit] if limit is not None else rows

    def search_tags_bulk_all(
        self, queries: list[str], *, format_name=None, resolve_preferred: bool = False
    ) -> dict[str, list[dict]]:
        self.calls.append(
            {"bulk_all": list(queries), "format_name": format_name, "resolve_preferred": resolve_preferred}
        )
        result: dict[str, list[dict]] = {}
        for query in queries:
            matched = [
                row for row in self._rows if row["tag"] == query or row.get("source_tag") == query
            ]
            if matched:
                result[query] = matched
        return result


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


def _usage_row(tag_id: int, usage: int) -> dict[str, object]:
    return {
        "tag": f"t{tag_id}",
        "source_tag": None,
        "tag_id": tag_id,
        "format_name": None,
        "type_id": 1,
        "type_name": "general",
        "alias": False,
        "deprecated": False,
        "usage_count": usage,
        "translations": None,
        "format_statuses": {},
    }


def test_search_tags_constrained_paginates_after_filter():
    """制約付き検索は unbounded fetch → filter → Python paging。total は filter 後の正確な件数。"""
    # min_usage=10 で usage<10 の先頭 2 件が落ちる
    rows = [_usage_row(1, 1), _usage_row(2, 1), _usage_row(3, 50), _usage_row(4, 60), _usage_row(5, 70)]
    repo = DummyRepo(rows=rows)

    result = core_api.search_tags(repo, TagSearchRequest(query="t", limit=2, offset=0, min_usage=10))

    # 制約ありでも repository が filter 後に limit する
    assert repo.calls[-1]["limit"] == 2
    assert repo.calls[-1]["min_usage"] == 10
    # usage>=10 の active 3 件 (3,4,5) 中、limit=2 → (3,4)
    assert [item.tag_id for item in result.items] == [3, 4]
    # bounded fetch のため total は不明
    assert result.total is None


def test_search_tags_unqualified_usage_filter_not_dropped():
    """#45: 無 format + min_usage で repository の一致が core_api 側で空にされない。

    repository は実 DB 値で usage>=min を拾うが、無 format では build_row が usage_count=0 で
    返す。core_api が Python で再フィルタすると usage_count(0) < min_usage で全 drop してしまう
    ため、再フィルタしない (フィルタの正本は repository) ことを保証する回帰テスト。
    """
    rows = [_usage_row(1, 50), _usage_row(2, 80)]  # 実 usage は閾値以上
    repo = DummyRepo(rows=rows)

    result = core_api.search_tags(repo, TagSearchRequest(query="t", min_usage=10))

    # repository の一致が保持され、空にならない
    assert [item.tag_id for item in result.items] == [1, 2]
    assert result.total == 2
    # 無 format のため表示上の usage_count は 0 (build_row 既定) になる
    assert all(item.usage_count == 0 for item in result.items)


def test_search_tags_constrained_offset_returns_later_rows():
    """制約付き検索でも offset は filter 後の行に適用される (先頭が落ちても空にならない)。"""
    rows = [_usage_row(1, 1), _usage_row(2, 50), _usage_row(3, 60), _usage_row(4, 70)]
    repo = DummyRepo(rows=rows)

    result = core_api.search_tags(repo, TagSearchRequest(query="t", limit=2, offset=1, min_usage=10))

    # usage>=10 の (2,3,4) を offset=1 → (3,4)
    assert [item.tag_id for item in result.items] == [3, 4]
    assert result.total is None


def test_search_tags_filters_and_maps():
    rows = [
        {
            "tag": "cat",
            "source_tag": "cat",
            "tag_id": 1,
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
            "tag_id": 2,
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
            "tag_id": 3,
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
            "tag_id": 4,
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
        partial=False,
        format_names=["danbooru"],
        type_names=["artist"],
        include_aliases=False,
        include_deprecated=False,
    )
    result = core_api.search_tags(repo, request)
    assert repo.calls[0]["partial"] is False
    assert repo.calls[0]["alias"] is False
    assert repo.calls[0]["deprecated"] is False
    assert result.items == [
        TagRecordPublic(
            tag="bunny",
            source_tag="bunny",
            tag_id=4,
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


def _batch_rows() -> list[dict]:
    return [
        {
            "tag": "cat",
            "source_tag": "cat",
            "tag_id": 1,
            "type_id": 1,
            "type_name": "general",
            "alias": False,
            "deprecated": False,
            "usage_count": 100,
            "translations": {"japanese": ["猫"]},
            "format_statuses": {"danbooru": {"status": "active"}},
        },
        {
            "tag": "dog",
            "source_tag": "dog",
            "tag_id": 2,
            "type_id": 1,
            "type_name": "general",
            "alias": False,
            "deprecated": False,
            "usage_count": 80,
            "translations": {"japanese": ["犬"]},
            "format_statuses": {"danbooru": {"status": "active"}},
        },
    ]


def test_search_tags_batch_maps_rows_per_query():
    """search_tags_batch は query ごとに TagSearchResult を返し、未一致 query は含めない (#998)。"""
    repo = DummyRepo(_batch_rows())

    result = core_api.search_tags_batch(repo, ["cat", "dog", "missing"])

    assert set(result.keys()) == {"cat", "dog"}
    assert [item.tag_id for item in result["cat"].items] == [1]
    assert result["cat"].total == 1
    assert isinstance(result["cat"].items[0], TagRecordPublic)
    assert result["cat"].items[0].translations == {"japanese": ["猫"]}
    # bulk_all を 1 回だけ呼ぶ (per-query search_tags を N 回呼ばない)
    bulk_calls = [c for c in repo.calls if "bulk_all" in c]
    assert len(bulk_calls) == 1
    assert bulk_calls[0]["bulk_all"] == ["cat", "dog", "missing"]


def test_search_tags_batch_passes_single_concrete_format():
    """単一 concrete format 指定時は format_name として bulk_all に渡す (#998)。"""
    repo = DummyRepo(_batch_rows())

    core_api.search_tags_batch(repo, ["cat"], format_names=["danbooru"])

    call = [c for c in repo.calls if "bulk_all" in c][-1]
    assert call["format_name"] == "danbooru"


def test_search_tags_batch_multi_or_all_format_disables_filter():
    """複数 format / "all" 指定は format 非依存 (format_name=None) で検索する (#998)。"""
    repo = DummyRepo(_batch_rows())

    core_api.search_tags_batch(repo, ["cat"], format_names=["danbooru", "e621"])
    core_api.search_tags_batch(repo, ["cat"], format_names=["all"])

    bulk_calls = [c for c in repo.calls if "bulk_all" in c]
    assert bulk_calls[0]["format_name"] is None
    assert bulk_calls[1]["format_name"] is None


def test_search_tags_batch_empty_queries_returns_empty():
    """空 query リストは空 dict を返す (#998)。"""
    repo = DummyRepo(_batch_rows())
    assert core_api.search_tags_batch(repo, []) == {}


def test_search_tags_applies_offset_and_limit_in_repository():
    rows = [
        {
            "tag": f"tag{i}",
            "source_tag": f"tag{i}",
            "tag_id": i,
            "format_name": "danbooru",
            "type_id": 1,
            "type_name": "general",
            "alias": False,
            "deprecated": False,
            "usage_count": 100,
            "translations": None,
            "format_statuses": {"danbooru": {"status": "active"}},
        }
        for i in range(1, 6)
    ]
    repo = DummyRepo(rows)
    # min_usage=1 は全行 (usage=100) を通すが、制約付きパス (unbounded fetch → Python paging)
    # を通すことで offset/limit が Python 側で適用され total が保持されることを検証する。
    request = TagSearchRequest(
        query="tag",
        partial=True,
        include_aliases=True,
        include_deprecated=True,
        min_usage=1,
        offset=1,
        limit=2,
    )

    result = core_api.search_tags(repo, request)

    # 制約付きでも repository が filter 後に offset/limit する
    assert repo.calls[-1]["limit"] == 2
    assert repo.calls[-1]["offset"] == 1
    assert [item.tag_id for item in result.items] == [2, 3]
    assert result.total is None


def test_search_tags_plain_keyword_bounds_repo_query():
    """plain keyword + limit は limit/offset を repository に pushdown して bound する (autocomplete)。

    format/type/usage 制約が無い検索では post-filter が何も落とさないため、SQL LIMIT を
    そのまま渡して repository クエリ (および preload) を bound できる。
    """
    rows = [_usage_row(i, 100) for i in range(1, 6)]
    repo = DummyRepo(rows)
    request = TagSearchRequest(query="tag", partial=True, limit=2, offset=1)
    result = core_api.search_tags(repo, request)

    # offset/limit は MergedTagReader が merge 後に扱うため core_api はそのまま渡す。
    assert repo.calls[0].get("limit") == 2
    assert repo.calls[0].get("offset") == 1
    assert repo.calls[0].get("alias") is None
    assert repo.calls[0].get("deprecated") is False
    assert [item.tag_id for item in result.items] == [2, 3]
    # bounded fetch のため total は不明 (None)
    assert result.total is None


def test_search_tags_treats_all_filters_as_unqualified():
    rows = [
        {
            "tag": "cat",
            "source_tag": "cat",
            "tag_id": 1,
            "format_name": None,
            "type_id": None,
            "type_name": "",
            "alias": False,
            "deprecated": False,
            "usage_count": 0,
            "translations": None,
            "format_statuses": {"danbooru": {"status": "active"}},
        }
    ]
    repo = DummyRepo(rows)
    request = TagSearchRequest(query="cat", format_names=["all"], type_names=["all"], limit=1)

    result = core_api.search_tags(repo, request)

    assert repo.calls[0]["format_names"] is None
    assert repo.calls[0]["type_names"] is None
    assert [item.tag_id for item in result.items] == [1]


def test_search_tags_passes_none_limit_when_not_set():
    """limit 未設定時は None が渡されること（既存動作を壊さない）。"""
    rows = [
        {
            "tag": "sample_tag",
            "source_tag": "sample_tag",
            "tag_id": 1,
            "format_name": "danbooru",
            "type_id": 1,
            "type_name": "general",
            "alias": False,
            "deprecated": False,
            "usage_count": 100,
            "translations": None,
            "format_statuses": {},
        }
    ]
    repo = DummyRepo(rows)
    request = TagSearchRequest(query="tag", partial=True)
    core_api.search_tags(repo, request)
    assert repo.calls[0].get("limit") is None


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


def test_initialize_databases_with_format_name(tmp_path, monkeypatch):
    """Test initialize_databases() with custom format_name parameter."""
    from unittest.mock import Mock

    # Create dummy DB files
    db_cc4 = tmp_path / "genai-image-tag-db-cc4.sqlite"
    db_mit = tmp_path / "genai-image-tag-db-mit.sqlite"
    db_cc0 = tmp_path / "genai-image-tag-db-cc0.sqlite"
    db_cc4.write_bytes(b"cc4")
    db_mit.write_bytes(b"mit")
    db_cc0.write_bytes(b"cc0")

    # Mock HuggingFace download to return the dummy files
    call_count = [0]
    paths = [db_cc4, db_mit, db_cc0]

    def fake_download(spec, *, token=None):
        path = paths[call_count[0]]
        call_count[0] += 1
        return (path, False)

    monkeypatch.setattr(hf_downloader, "download_with_offline_fallback", fake_download)

    # Mock runtime functions
    mock_set_paths = Mock()
    mock_init_engine = Mock()
    mock_init_user = Mock(return_value=tmp_path / "user_tags.sqlite")

    monkeypatch.setattr("genai_tag_db_tools.db.runtime.set_base_database_paths", mock_set_paths)
    monkeypatch.setattr("genai_tag_db_tools.db.runtime.init_engine", mock_init_engine)
    monkeypatch.setattr("genai_tag_db_tools.db.runtime.init_user_db", mock_init_user)

    # Execute
    results = core_api.initialize_databases(
        user_db_dir=tmp_path,
        format_name="TestApp",
    )

    # Verify format_name was passed through
    mock_init_user.assert_called_once_with(tmp_path, format_name="TestApp")
    assert len(results) == 3  # Default 3 databases


def test_initialize_databases_init_user_db_default_behavior(tmp_path, monkeypatch):
    """Test init_user_db defaults to False when user_db_dir is None."""
    from unittest.mock import Mock

    # Create dummy DB files
    db_cc4 = tmp_path / "genai-image-tag-db-cc4.sqlite"
    db_mit = tmp_path / "genai-image-tag-db-mit.sqlite"
    db_cc0 = tmp_path / "genai-image-tag-db-cc0.sqlite"
    db_cc4.write_bytes(b"cc4")
    db_mit.write_bytes(b"mit")
    db_cc0.write_bytes(b"cc0")

    # Mock HuggingFace download
    call_count = [0]
    paths = [db_cc4, db_mit, db_cc0]

    def fake_download(spec, *, token=None):
        path = paths[call_count[0]]
        call_count[0] += 1
        return (path, False)

    monkeypatch.setattr(hf_downloader, "download_with_offline_fallback", fake_download)

    # Mock runtime functions
    mock_set_paths = Mock()
    mock_init_engine = Mock()
    mock_init_user = Mock()

    monkeypatch.setattr("genai_tag_db_tools.db.runtime.set_base_database_paths", mock_set_paths)
    monkeypatch.setattr("genai_tag_db_tools.db.runtime.init_engine", mock_init_engine)
    monkeypatch.setattr("genai_tag_db_tools.db.runtime.init_user_db", mock_init_user)

    # Execute with user_db_dir=None (default init_user_db should be False)
    results = core_api.initialize_databases(user_db_dir=None)

    # Verify init_user_db was NOT called
    mock_init_user.assert_not_called()
    assert len(results) == 3


def test_initialize_databases_init_user_db_explicit_true(tmp_path, monkeypatch):
    """Test init_user_db can be explicitly set to True even when user_db_dir is None."""
    from unittest.mock import Mock

    # Create dummy DB files
    db_cc4 = tmp_path / "genai-image-tag-db-cc4.sqlite"
    db_mit = tmp_path / "genai-image-tag-db-mit.sqlite"
    db_cc0 = tmp_path / "genai-image-tag-db-cc0.sqlite"
    db_cc4.write_bytes(b"cc4")
    db_mit.write_bytes(b"mit")
    db_cc0.write_bytes(b"cc0")

    # Mock HuggingFace download
    call_count = [0]
    paths = [db_cc4, db_mit, db_cc0]

    def fake_download(spec, *, token=None):
        path = paths[call_count[0]]
        call_count[0] += 1
        return (path, False)

    monkeypatch.setattr(hf_downloader, "download_with_offline_fallback", fake_download)

    # Mock runtime functions
    mock_set_paths = Mock()
    mock_init_engine = Mock()
    mock_init_user = Mock()
    mock_default_cache = Mock(return_value=tmp_path)

    monkeypatch.setattr("genai_tag_db_tools.db.runtime.set_base_database_paths", mock_set_paths)
    monkeypatch.setattr("genai_tag_db_tools.db.runtime.init_engine", mock_init_engine)
    monkeypatch.setattr("genai_tag_db_tools.db.runtime.init_user_db", mock_init_user)
    monkeypatch.setattr("genai_tag_db_tools.io.hf_downloader.default_cache_dir", mock_default_cache)

    # Execute with user_db_dir=None but init_user_db=True
    results = core_api.initialize_databases(user_db_dir=None, init_user_db=True)

    # Verify init_user_db WAS called with default cache dir
    mock_init_user.assert_called_once()
    assert len(results) == 3


def test_initialize_databases_init_user_db_explicit_false(tmp_path, monkeypatch):
    """Test init_user_db can be explicitly set to False even when user_db_dir is provided."""
    from unittest.mock import Mock

    # Create dummy DB files
    db_cc4 = tmp_path / "genai-image-tag-db-cc4.sqlite"
    db_mit = tmp_path / "genai-image-tag-db-mit.sqlite"
    db_cc0 = tmp_path / "genai-image-tag-db-cc0.sqlite"
    db_cc4.write_bytes(b"cc4")
    db_mit.write_bytes(b"mit")
    db_cc0.write_bytes(b"cc0")

    # Mock HuggingFace download
    call_count = [0]
    paths = [db_cc4, db_mit, db_cc0]

    def fake_download(spec, *, token=None):
        path = paths[call_count[0]]
        call_count[0] += 1
        return (path, False)

    monkeypatch.setattr(hf_downloader, "download_with_offline_fallback", fake_download)

    # Mock runtime functions
    mock_set_paths = Mock()
    mock_init_engine = Mock()
    mock_init_user = Mock()

    monkeypatch.setattr("genai_tag_db_tools.db.runtime.set_base_database_paths", mock_set_paths)
    monkeypatch.setattr("genai_tag_db_tools.db.runtime.init_engine", mock_init_engine)
    monkeypatch.setattr("genai_tag_db_tools.db.runtime.init_user_db", mock_init_user)

    # Execute with user_db_dir=tmp_path but init_user_db=False
    results = core_api.initialize_databases(user_db_dir=tmp_path, init_user_db=False)

    # Verify init_user_db was NOT called
    mock_init_user.assert_not_called()
    assert len(results) == 3
