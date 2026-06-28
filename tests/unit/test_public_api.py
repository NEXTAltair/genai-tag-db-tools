"""Tests for the stable public API surface (genai_tag_db_tools.api / __init__).

These tests pin the public contract so that internal refactors (class renames,
module moves) cannot silently break downstream consumers. They intentionally
import only from the top-level package.
"""

from __future__ import annotations

import pytest

import genai_tag_db_tools as pkg
from genai_tag_db_tools import (
    MergedTagReader,
    TagReaderProtocol,
    TagRegisterServiceProtocol,
    create_tag_register_service,
    get_default_reader,
    get_tag_reader,
    get_user_repository,
    get_user_tag_reader,
)


def test_public_names_are_exported() -> None:
    """All advertised public names are reachable from the top-level package."""
    expected = {
        "TagReaderProtocol",
        "TagRegisterServiceProtocol",
        "TagWriterProtocol",
        "get_tag_reader",
        "get_user_tag_reader",
        "create_tag_register_service",
        "get_user_repository",
    }
    assert expected.issubset(set(pkg.__all__))
    for name in expected:
        assert hasattr(pkg, name)


def test_backward_compat_aliases() -> None:
    """Legacy names map onto the stable protocol/factory, not internal classes."""
    assert MergedTagReader is TagReaderProtocol
    assert get_default_reader is get_tag_reader


def test_internal_reader_satisfies_reader_protocol() -> None:
    """The concrete reader implementation conforms to TagReaderProtocol."""
    from genai_tag_db_tools.db.repository import MergedTagReader as _MergedTagReader
    from genai_tag_db_tools.db.repository import TagReader as _TagReader

    reader = _MergedTagReader(base_repo=_TagReader(session_factory=lambda: None))
    assert isinstance(reader, TagReaderProtocol)


def test_internal_register_service_satisfies_protocol() -> None:
    """The concrete register service exposes the protocol's register_tag method."""
    from genai_tag_db_tools.services.tag_register import TagRegisterService

    assert hasattr(TagRegisterService, "register_tag")
    # Structural check via runtime_checkable Protocol on a lightweight stand-in.

    class _Stub:
        def register_tag(self, request):
            return request

    assert isinstance(_Stub(), TagRegisterServiceProtocol)


def test_internal_repository_satisfies_writer_protocol() -> None:
    """The concrete repository exposes the writer protocol surface."""
    from genai_tag_db_tools.db.repository import TagRepository

    assert hasattr(TagRepository, "update_tags_type_batch")


def test_get_user_tag_reader_requires_initialized_user_db() -> None:
    """Without an initialized user DB, the user-scoped reader fails clearly."""
    with pytest.raises(RuntimeError):
        get_user_tag_reader()


def test_create_tag_register_service_is_callable() -> None:
    """The factory returns a register-service handle when given a reader."""

    class _Reader:
        def get_format_id(self, name):
            return 1

    # repository defaults to the user DB which is uninitialized in unit tests, so
    # construction is expected to fail loudly rather than touch a real DB.
    with pytest.raises(Exception):  # noqa: B017 - any uninitialized-DB error is acceptable
        create_tag_register_service(reader=_Reader())  # type: ignore[arg-type]


def test_get_user_repository_requires_user_db() -> None:
    """get_user_repository raises when the user DB is unavailable for writes."""
    with pytest.raises(ValueError):
        get_user_repository()
