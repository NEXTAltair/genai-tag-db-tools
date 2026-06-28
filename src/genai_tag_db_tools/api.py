"""Stable public API surface for genai-tag-db-tools.

This module defines the *public contract* that downstream consumers (e.g. LoRAIro)
should depend on. It deliberately hides the concrete implementation classes
(``MergedTagReader`` / ``OverlayTagReader`` / ``TagReader`` / ``TagRepository`` /
``TagRegisterService``) behind lightweight :class:`typing.Protocol` types and
factory functions.

Why this exists
---------------
Historically downstream code imported internal classes directly, e.g.::

    from genai_tag_db_tools.db.repository import MergedTagReader, get_default_reader
    from genai_tag_db_tools.services.tag_register import TagRegisterService
    from genai_tag_db_tools.db.runtime import get_user_session_factory

Those imports couple callers to internal module layout and class names, so any
internal refactor (overlay redesign, renames) breaks them. The protocols and
factories below provide a stable surface that survives internal refactors.

Public surface
--------------
Types (use only for annotations; treat instances as opaque handles):
    * ``TagReaderProtocol``           - read-only tag database handle
    * ``TagRegisterServiceProtocol``  - tag registration service handle
    * ``TagWriterProtocol``           - write-capable user-DB repository handle

Factories:
    * ``get_tag_reader()``            - merged (base + user overlay) reader
    * ``get_user_tag_reader()``       - user-DB-only reader
    * ``create_tag_register_service()`` - registration service
    * ``get_user_repository()``       - write-capable user repository

Obtain a handle from a factory and pass it back into the module-level helpers
(``search_tags``, ``convert_tags``, ``register_tag`` ...). Do not call methods on
the handles directly and do not rely on their concrete runtime type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from genai_tag_db_tools.models import TagRegisterRequest, TagRegisterResult

__all__ = [
    "TagReaderProtocol",
    "TagRegisterServiceProtocol",
    "TagWriterProtocol",
    "create_tag_register_service",
    "get_tag_reader",
    "get_user_repository",
    "get_user_tag_reader",
]


@runtime_checkable
class TagReaderProtocol(Protocol):
    """Stable, read-only handle to the tag database.

    Treat instances as opaque: obtain one via :func:`get_tag_reader` or
    :func:`get_user_tag_reader` and pass it to the module-level helpers such as
    ``search_tags`` / ``convert_tags`` / ``get_statistics``. The method set below
    is the contract those helpers rely on; downstream code should not call these
    directly and should annotate variables as ``TagReaderProtocol``.
    """

    def search_tags(self, *args: Any, **kwargs: Any) -> Any: ...
    def search_tags_bulk(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_format_id(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_format_name(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_tag_by_id(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_tag_status(self, *args: Any, **kwargs: Any) -> Any: ...
    def list_tags(self, *args: Any, **kwargs: Any) -> Any: ...
    def list_tag_statuses(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_tag_formats(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_all_types(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_tag_types(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_type_id_for_format(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_type_name_by_format_type_id(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_unknown_type_tag_ids(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class TagRegisterServiceProtocol(Protocol):
    """Stable handle for registering tags.

    Obtain one via :func:`create_tag_register_service` and pass it to
    ``register_tag(service, request)``.
    """

    def register_tag(self, request: TagRegisterRequest) -> TagRegisterResult: ...


@runtime_checkable
class TagWriterProtocol(Protocol):
    """Stable, write-capable handle to the user tag database.

    Obtain one via :func:`get_user_repository` and pass it to write helpers such
    as ``update_tags_type_batch``. Treat instances as opaque.
    """

    def update_tags_type_batch(self, *args: Any, **kwargs: Any) -> Any: ...


def get_tag_reader() -> TagReaderProtocol:
    """Return the default merged reader (base DBs + user overlay).

    This is the stable replacement for the internal
    ``genai_tag_db_tools.db.repository.get_default_reader``. Databases must be
    initialized first via :func:`genai_tag_db_tools.initialize_databases`.
    """
    from genai_tag_db_tools.db.repository import get_default_reader

    return cast("TagReaderProtocol", get_default_reader())


def get_user_tag_reader() -> TagReaderProtocol:
    """Return a reader scoped to the user database only (no base DBs).

    Useful for operations that should read/search exclusively within the user's
    own overlay tags. Raises ``RuntimeError`` if the user DB is not initialized.
    """
    from genai_tag_db_tools.db.overlay_reader import OverlayTagReader
    from genai_tag_db_tools.db.repository import MergedTagReader
    from genai_tag_db_tools.db.runtime import get_user_session_factory_optional

    user_factory = get_user_session_factory_optional()
    if user_factory is None:
        raise RuntimeError(
            "User database is not initialized. Call initialize_databases(..., init_user_db=True) first."
        )
    user_reader = OverlayTagReader(session_factory=user_factory)
    # Expose the user overlay as the base scope of a MergedTagReader so the full
    # reader interface is available while keeping base DBs out of scope.
    return cast("TagReaderProtocol", MergedTagReader(base_repo=user_reader, user_repo=None))


def create_tag_register_service(
    reader: TagReaderProtocol | None = None,
) -> TagRegisterServiceProtocol:
    """Create a tag registration service.

    Stable replacement for instantiating
    ``genai_tag_db_tools.services.tag_register.TagRegisterService`` directly.

    Args:
        reader: Optional reader handle (e.g. from :func:`get_tag_reader`). When
            omitted the service builds the default reader/repository itself.
    """
    from genai_tag_db_tools.services.tag_register import TagRegisterService

    service = TagRegisterService(reader=cast("Any", reader))
    return cast("TagRegisterServiceProtocol", service)


def get_user_repository() -> TagWriterProtocol:
    """Return a write-capable repository bound to the user database.

    Stable replacement for the internal
    ``genai_tag_db_tools.db.repository.get_default_repository``. Raises
    ``ValueError`` if the user DB is not available for writes.
    """
    from genai_tag_db_tools.db.repository import get_default_repository

    return cast("TagWriterProtocol", get_default_repository())
