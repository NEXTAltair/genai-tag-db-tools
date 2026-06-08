"""Unit tests for `tag-db aliases register` command (Issue #47)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from genai_tag_db_tools.models import AliasRegisterInput
from genai_tag_db_tools.services.tag_register import TagRegisterService


class DummyStatus:
    def __init__(self, alias: bool, preferred_tag_id: int) -> None:
        self.alias = alias
        self.preferred_tag_id = preferred_tag_id


class DummyRepo:
    def __init__(self) -> None:
        self.created_tags: list[tuple[str, str]] = []
        self.status_updates: list[dict] = []
        self._tag_ids: dict[str, int] = {}
        self._next_id = 100

    def create_tag(self, source_tag: str, tag: str) -> int:
        self.created_tags.append((source_tag, tag))
        new_id = self._next_id
        self._next_id += 1
        self._tag_ids[tag] = new_id
        return new_id

    def update_tag_status(
        self,
        tag_id: int,
        format_id: int,
        alias: bool,
        preferred_tag_id: int,
        type_id: int | None = None,
    ) -> None:
        self.status_updates.append(
            {"tag_id": tag_id, "format_id": format_id, "alias": alias, "preferred_tag_id": preferred_tag_id}
        )

    def add_or_update_translation(self, tag_id: int, language: str, translation: str) -> None:
        pass

    def create_format_if_not_exists(
        self, format_name: str, description: str | None = None, reader: object = None
    ) -> int:
        return 1001

    def create_type_name_if_not_exists(self, type_name: str, description: str | None = None) -> int:
        return 0

    def get_next_type_id(self, format_id: int) -> int:
        return 1

    def create_type_format_mapping_if_not_exists(
        self, format_id: int, type_id: int, type_name_id: int, description: str | None = None
    ) -> int:
        return type_id


class DummyReader:
    def __init__(self) -> None:
        self._tags: dict[str, int] = {"wedding dress": 99}
        self._statuses: dict[tuple[int, int], DummyStatus] = {}

    def get_tag_id_by_name(self, tag: str, partial: bool = False) -> int | None:
        return self._tags.get(tag)

    def get_format_id(self, format_name: str) -> int:
        result = {"Lorairo": 1001}.get(format_name)
        if result is None:
            raise ValueError(format_name)
        return result

    def get_type_id_for_format(self, type_name: str, format_id: int) -> int | None:
        return 0 if type_name == "unknown" else None

    def get_tag_status(self, tag_id: int, format_id: int) -> DummyStatus | None:
        return self._statuses.get((tag_id, format_id))


class TestRegisterAliasEntry:
    def _make_service(self, reader: DummyReader | None = None) -> TagRegisterService:
        repo = DummyRepo()
        r = reader or DummyReader()
        return TagRegisterService(repository=repo, reader=r)

    def test_missing_preferred_returns_missing_preferred_status(self) -> None:
        service = self._make_service()
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="nonexistent tag",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=True)
        assert result.status == "missing_preferred"
        assert result.alias == "weding dress"
        assert result.preferred == "nonexistent tag"

    def test_dry_run_returns_would_create(self) -> None:
        service = self._make_service()
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="wedding dress",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=True)
        assert result.status == "would_create"
        assert result.preferred_tag_id == 99

    def test_apply_returns_created_and_writes_db(self) -> None:
        repo = DummyRepo()
        service = TagRegisterService(repository=repo, reader=DummyReader())
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="wedding dress",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=False)
        assert result.status == "created"
        assert result.alias_tag_id is not None
        assert result.preferred_tag_id == 99
        assert len(repo.status_updates) == 1
        assert repo.status_updates[0]["alias"] is True
        assert repo.status_updates[0]["preferred_tag_id"] == 99

    def test_skipped_when_same_preferred_exists(self) -> None:
        reader = DummyReader()
        reader._tags["weding dress"] = 200
        reader._statuses[(200, 1001)] = DummyStatus(alias=True, preferred_tag_id=99)
        service = self._make_service(reader=reader)
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="wedding dress",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=False)
        assert result.status == "skipped"

    def test_conflict_when_different_preferred_exists(self) -> None:
        reader = DummyReader()
        reader._tags["weding dress"] = 200
        reader._tags["other dress"] = 300
        reader._statuses[(200, 1001)] = DummyStatus(alias=True, preferred_tag_id=300)
        service = self._make_service(reader=reader)
        entry = AliasRegisterInput(
            alias="weding dress",
            preferred="wedding dress",
            format_name="Lorairo",
            type_name="unknown",
        )
        result = service.register_alias_entry(entry, dry_run=False)
        assert result.status == "conflict"
