from pathlib import Path

import pytest

from genai_tag_db_tools.db.runtime import get_database_path
from genai_tag_db_tools.io.hf_downloader import (
    HFDatasetSpec,
    default_cache_dir,
    download_hf_dataset_file,
    download_with_offline_fallback,
    ensure_db_ready,
)

pytestmark = pytest.mark.db_tools


def test_default_cache_dir_points_to_app_cache():
    """default_cache_dir()がユーザーDB配置用ディレクトリを返すことを確認。"""
    cache_dir = default_cache_dir()
    assert "genai-tag-db-tools" in str(cache_dir)


def test_download_uses_hf_standard_cache(monkeypatch, tmp_path: Path) -> None:
    """download_hf_dataset_file()がHF標準キャッシュを使用することを確認。"""
    spec = HFDatasetSpec(repo_id="dummy/repo", filename="db.sqlite")

    captured_calls = []

    def mock_hf_hub_download(**kwargs):
        captured_calls.append(kwargs)
        cache_path = tmp_path / "hub" / "models--dummy--repo" / "snapshots" / "abc123" / "db.sqlite"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("")
        return str(cache_path)

    monkeypatch.setattr("genai_tag_db_tools.io.hf_downloader.hf_hub_download", mock_hf_hub_download)

    result = download_hf_dataset_file(spec, token="test-token")

    # local_dirパラメータが渡されていないことを確認
    assert len(captured_calls) == 1
    assert "local_dir" not in captured_calls[0]
    assert captured_calls[0]["repo_id"] == "dummy/repo"
    assert result.exists()


def test_offline_fallback_uses_local_files_only(monkeypatch, tmp_path: Path) -> None:
    """オフラインフォールバックがlocal_files_onlyパラメータを使用することを確認。"""
    spec = HFDatasetSpec(repo_id="dummy/repo", filename="db.sqlite")

    call_count = [0]

    def mock_hf_hub_download(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ConnectionError("Network unavailable")
        else:
            assert kwargs.get("local_files_only") is True
            cache_path = tmp_path / "cached.sqlite"
            cache_path.write_text("")
            return str(cache_path)

    monkeypatch.setattr("genai_tag_db_tools.io.hf_downloader.hf_hub_download", mock_hf_hub_download)

    result, is_cached = download_with_offline_fallback(spec)

    assert call_count[0] == 2
    assert is_cached is True
    assert result.exists()


def test_offline_fallback_returns_fresh_download(monkeypatch, tmp_path: Path) -> None:
    """download_with_offline_fallback()がネットワーク成功時にis_cached=Falseを返すことを確認。"""
    spec = HFDatasetSpec(repo_id="dummy/repo", filename="db.sqlite")

    def mock_hf_hub_download(**kwargs):
        cache_path = tmp_path / "fresh.sqlite"
        cache_path.write_text("")
        return str(cache_path)

    monkeypatch.setattr("genai_tag_db_tools.io.hf_downloader.hf_hub_download", mock_hf_hub_download)

    result, is_cached = download_with_offline_fallback(spec)

    assert is_cached is False
    assert result.exists()


def test_offline_fallback_raises_when_no_cache_available(monkeypatch) -> None:
    """download_with_offline_fallback()がキャッシュなし時にエラーを投げることを確認。"""
    spec = HFDatasetSpec(repo_id="dummy/repo", filename="db.sqlite")

    def mock_hf_hub_download(**kwargs):
        raise ConnectionError("Network unavailable")

    monkeypatch.setattr("genai_tag_db_tools.io.hf_downloader.hf_hub_download", mock_hf_hub_download)

    with pytest.raises(RuntimeError, match=r"Failed to download.*no cached version available"):
        download_with_offline_fallback(spec)


def test_ensure_db_ready_sets_runtime(monkeypatch, tmp_path: Path):
    """ensure_db_ready()がruntimeを初期化することを確認。"""
    fake_db = tmp_path / "db.sqlite"
    fake_db.write_text("")

    def fake_download(*_args, **_kwargs):
        return fake_db, False

    monkeypatch.setattr(
        "genai_tag_db_tools.io.hf_downloader.download_with_offline_fallback", fake_download
    )

    spec = HFDatasetSpec(repo_id="dummy", filename="db.sqlite")
    result = ensure_db_ready(spec)

    assert result == fake_db
    assert get_database_path() == fake_db
