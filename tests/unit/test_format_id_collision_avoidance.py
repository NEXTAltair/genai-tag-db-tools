"""Test format_id collision avoidance between base and user databases."""

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genai_tag_db_tools.db.repository import MergedTagReader, TagReader, TagRepository
from genai_tag_db_tools.db.schema import Base, TagFormat
from genai_tag_db_tools.services.tag_register import TagRegisterService
from genai_tag_db_tools.models import TagRegisterRequest

pytestmark = pytest.mark.db_tools


@pytest.fixture
def base_session_factory() -> Callable[[], Session]:
    """Create a base database session factory with format_id=1 (danbooru)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # Initialize with format_id=1 → "danbooru"
    with factory() as session:
        base_format = TagFormat(format_id=1, format_name="danbooru", description="Base DB format")
        session.add(base_format)
        session.commit()

    return factory


@pytest.fixture
def user_session_factory() -> Callable[[], Session]:
    """Create an empty user database session factory."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_format_id_collision_avoidance(
    base_session_factory: Callable[[], Session],
    user_session_factory: Callable[[], Session],
):
    """Test that user DB format_id doesn't collide with base DB format_id."""
    # Create repositories
    base_reader = TagReader(base_session_factory)
    user_reader = TagReader(user_session_factory)  # Reader for user DB

    # Create MergedTagReader with base and user repos
    reader = MergedTagReader(base_repo=base_reader, user_repo=user_reader)

    # Create TagRepository with injected reader
    user_repo = TagRepository(user_session_factory, reader=reader)  # Writer for user DB

    # Verify base DB has format_id=1 → "danbooru"
    base_formats = base_reader.get_format_map()
    assert 1 in base_formats
    assert base_formats[1] == "danbooru"

    # Create TagRegisterService and register a new tag with format_name="Lorairo"
    service = TagRegisterService(repository=user_repo, reader=reader)
    request = TagRegisterRequest(
        tag="test_tag",
        source_tag="test_tag",
        format_name="Lorairo",
        type_name="unknown",
    )

    result = service.register_tag(request)
    assert result.created is True

    # Verify user DB created format_id=2 (not 1, avoiding collision)
    user_formats = user_reader.get_format_map()
    assert 2 in user_formats
    assert user_formats[2] == "Lorairo"
    assert 1 not in user_formats  # User DB should not have format_id=1

    # Verify MergedTagReader correctly merges both formats
    merged_formats = reader.get_format_map()
    assert 1 in merged_formats
    assert merged_formats[1] == "danbooru"
    assert 2 in merged_formats
    assert merged_formats[2] == "Lorairo"

    # Verify format_id lookups work correctly
    assert reader.get_format_id("danbooru") == 1
    assert reader.get_format_id("Lorairo") == 2
    assert reader.get_format_name(1) == "danbooru"
    assert reader.get_format_name(2) == "Lorairo"


def test_format_id_multiple_base_dbs():
    """Test format_id allocation with multiple base databases."""
    # Create base DB 1 with format_id=1
    engine1 = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine1)
    factory1 = sessionmaker(bind=engine1, autoflush=False, autocommit=False)
    with factory1() as session:
        session.add(TagFormat(format_id=1, format_name="danbooru"))
        session.commit()
    reader1 = TagReader(factory1)

    # Create base DB 2 with format_id=5
    engine2 = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine2)
    factory2 = sessionmaker(bind=engine2, autoflush=False, autocommit=False)
    with factory2() as session:
        session.add(TagFormat(format_id=5, format_name="e621"))
        session.commit()
    reader2 = TagReader(factory2)

    # Create user DB
    user_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(user_engine)
    user_factory = sessionmaker(bind=user_engine, autoflush=False, autocommit=False)
    user_reader = TagReader(user_factory)  # Reader for user DB

    # Create MergedTagReader with multiple base repos (pass list as base_repo)
    reader = MergedTagReader(base_repo=[reader1, reader2], user_repo=user_reader)

    # Create TagRepository with injected reader
    user_repo = TagRepository(user_factory, reader=reader)  # Writer for user DB

    # Register new format in user DB
    service = TagRegisterService(repository=user_repo, reader=reader)
    request = TagRegisterRequest(
        tag="test_tag",
        source_tag="test_tag",
        format_name="Lorairo",
        type_name="unknown",
    )
    service.register_tag(request)

    # Verify user DB allocated format_id=6 (max base format_id + 1)
    user_formats = user_reader.get_format_map()
    assert 6 in user_formats
    assert user_formats[6] == "Lorairo"

    # Verify merged view
    merged_formats = reader.get_format_map()
    assert merged_formats[1] == "danbooru"
    assert merged_formats[5] == "e621"
    assert merged_formats[6] == "Lorairo"


def test_format_creation_without_reader_uses_auto_increment():
    """Test that format creation without reader still uses auto-increment (legacy behavior)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    repo = TagRepository(factory)

    # Create format without passing reader (legacy path)
    format_id = repo.create_format_if_not_exists(
        format_name="Standalone", description="Test format", reader=None
    )

    # Should use auto-increment, starting from 1
    assert format_id == 1

    # Create another format
    format_id2 = repo.create_format_if_not_exists(
        format_name="Second", description="Second format", reader=None
    )
    assert format_id2 == 2
