"""models.py の Pydantic モデルバリデーションテスト"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genai_tag_db_tools.models import (
    DbCacheConfig,
    DbSourceRef,
    EnsureDbRequest,
    EnsureDbResult,
    TagRecordPublic,
    TagRegisterRequest,
    TagRegisterResult,
    TagSearchRequest,
    TagSearchResult,
    TagStatisticsResult,
    TagTranslationInput,
)


@pytest.mark.db_tools
def test_db_source_ref_valid():
    ref = DbSourceRef(
        repo_id="NEXTAltair/genai-image-tag-db-CC4",
        filename="genai-image-tag-db-cc4.sqlite",
    )
    assert ref.repo_id == "NEXTAltair/genai-image-tag-db-CC4"
    assert ref.filename == "genai-image-tag-db-cc4.sqlite"
    assert ref.revision is None


@pytest.mark.db_tools
def test_db_source_ref_with_revision():
    ref = DbSourceRef(repo_id="org/repo", filename="file.db", revision="v1.0.0")
    assert ref.revision == "v1.0.0"


@pytest.mark.db_tools
def test_db_source_ref_requires_repo_id():
    with pytest.raises(ValidationError):
        DbSourceRef(filename="file.db")


@pytest.mark.db_tools
def test_db_source_ref_requires_filename():
    with pytest.raises(ValidationError):
        DbSourceRef(repo_id="org/repo")


@pytest.mark.db_tools
def test_db_cache_config_valid():
    cache = DbCacheConfig(cache_dir="/path/to/cache")
    assert cache.cache_dir == "/path/to/cache"
    assert cache.token is None


@pytest.mark.db_tools
def test_db_cache_config_with_token():
    cache = DbCacheConfig(cache_dir="/path/to/cache", token="hf_token")
    assert cache.token == "hf_token"


@pytest.mark.db_tools
def test_db_cache_config_requires_cache_dir():
    with pytest.raises(ValidationError):
        DbCacheConfig()


@pytest.mark.db_tools
def test_ensure_db_request_valid():
    request = EnsureDbRequest(
        source=DbSourceRef(repo_id="org/repo", filename="file.db"),
        cache=DbCacheConfig(cache_dir="/cache"),
    )
    assert request.source.repo_id == "org/repo"
    assert request.cache.cache_dir == "/cache"


@pytest.mark.db_tools
def test_ensure_db_result_valid():
    result = EnsureDbResult(
        db_path="/path/to/db.sqlite",
        cached=True,
        sha256="abc123",
    )
    assert result.db_path == "/path/to/db.sqlite"
    assert result.cached is True
    assert result.sha256 == "abc123"


@pytest.mark.db_tools
def test_ensure_db_result_requires_all_fields():
    with pytest.raises(ValidationError):
        EnsureDbResult(db_path="/path/to/db.sqlite", cached=True)


@pytest.mark.db_tools
def test_tag_search_request_defaults():
    request = TagSearchRequest(query="cat")
    assert request.query == "cat"
    assert request.format_names is None
    assert request.type_names is None
    assert request.resolve_preferred is True
    assert request.include_aliases is True
    assert request.include_deprecated is False


@pytest.mark.db_tools
def test_tag_search_request_with_filters():
    request = TagSearchRequest(
        query="cat",
        format_names=["danbooru"],
        type_names=["character"],
        include_deprecated=True,
    )
    assert request.format_names == ["danbooru"]
    assert request.type_names == ["character"]
    assert request.include_deprecated is True


@pytest.mark.db_tools
def test_tag_record_public_valid():
    record = TagRecordPublic(
        tag="cat",
        source_tag="cat",
        format_name="danbooru",
        type_name="general",
        alias=False,
    )
    assert record.tag == "cat"
    assert record.source_tag == "cat"
    assert record.format_name == "danbooru"
    assert record.type_name == "general"
    assert record.alias is False


@pytest.mark.db_tools
def test_tag_record_public_minimal():
    record = TagRecordPublic(tag="cat")
    assert record.tag == "cat"
    assert record.source_tag is None
    assert record.format_name is None
    assert record.type_name is None
    assert record.alias is None


@pytest.mark.db_tools
def test_tag_search_result_valid():
    result = TagSearchResult(
        items=[
            TagRecordPublic(tag="cat"),
            TagRecordPublic(tag="dog"),
        ],
        total=2,
    )
    assert len(result.items) == 2
    assert result.total == 2


@pytest.mark.db_tools
def test_tag_search_result_total_optional():
    result = TagSearchResult(items=[TagRecordPublic(tag="cat")])
    assert len(result.items) == 1
    assert result.total is None


@pytest.mark.db_tools
def test_tag_translation_input_valid():
    translation = TagTranslationInput(language="ja", translation="猫")
    assert translation.language == "ja"
    assert translation.translation == "猫"


@pytest.mark.db_tools
def test_tag_translation_input_requires_both_fields():
    with pytest.raises(ValidationError):
        TagTranslationInput(language="ja")


@pytest.mark.db_tools
def test_tag_register_request_minimal():
    request = TagRegisterRequest(
        tag="cat",
        format_name="danbooru",
        type_name="general",
    )
    assert request.tag == "cat"
    assert request.source_tag is None
    assert request.format_name == "danbooru"
    assert request.type_name == "general"
    assert request.alias is False
    assert request.preferred_tag is None
    assert request.translations is None


@pytest.mark.db_tools
def test_tag_register_request_with_all_fields():
    request = TagRegisterRequest(
        tag="kitty",
        source_tag="kitty",
        format_name="danbooru",
        type_name="general",
        alias=True,
        preferred_tag="cat",
        translations=[TagTranslationInput(language="ja", translation="子猫")],
    )
    assert request.tag == "kitty"
    assert request.source_tag == "kitty"
    assert request.alias is True
    assert request.preferred_tag == "cat"
    assert len(request.translations) == 1
    assert request.translations[0].language == "ja"


@pytest.mark.db_tools
def test_tag_register_result_valid():
    result = TagRegisterResult(created=True)
    assert result.created is True


@pytest.mark.db_tools
def test_tag_register_result_requires_created():
    with pytest.raises(ValidationError):
        TagRegisterResult()


@pytest.mark.db_tools
def test_tag_statistics_result_valid():
    stats = TagStatisticsResult(
        total_tags=1000,
        total_aliases=100,
        total_formats=5,
        total_types=10,
    )
    assert stats.total_tags == 1000
    assert stats.total_aliases == 100
    assert stats.total_formats == 5
    assert stats.total_types == 10


@pytest.mark.db_tools
def test_tag_statistics_result_requires_all_fields():
    with pytest.raises(ValidationError):
        TagStatisticsResult(total_tags=1000, total_aliases=100)
