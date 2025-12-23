from types import SimpleNamespace

import pytest

import genai_tag_db_tools.db.db_maintenance_tool as maintenance_module


def _make_tool(monkeypatch: pytest.MonkeyPatch, repo):
    monkeypatch.setattr(maintenance_module, "set_database_path", lambda path: None)
    monkeypatch.setattr(maintenance_module, "init_engine", lambda path: None)
    monkeypatch.setattr(maintenance_module, "TagRepository", lambda: repo)
    return maintenance_module.DatabaseMaintenanceTool("dummy.db")


@pytest.mark.db_tools
def test_detect_duplicates_in_tag_status(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def list_tag_statuses(self):
            return [
                SimpleNamespace(tag_id=1, format_id=2, preferred_tag_id=1, alias=False),
                SimpleNamespace(tag_id=1, format_id=2, preferred_tag_id=1, alias=False),
            ]

        def get_tag_by_id(self, tag_id):
            return SimpleNamespace(tag="cat")

        def get_format_name(self, format_id):
            return "danbooru"

    tool = _make_tool(monkeypatch, DummyRepo())

    duplicates = tool.detect_duplicates_in_tag_status()

    assert duplicates == [
        {
            "tag": "cat",
            "format": "danbooru",
            "type": None,
            "alias": False,
            "preferred_tag": "cat",
        }
    ]


@pytest.mark.db_tools
def test_detect_usage_counts_for_tags(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def get_all_tag_ids(self):
            return [1]

        def get_tag_format_ids(self):
            return [10, 20]

        def get_tag_by_id(self, tag_id):
            return SimpleNamespace(tag="cat")

        def get_usage_count(self, tag_id, format_id):
            return 5 if format_id == 20 else None

        def get_format_name(self, format_id):
            return "e621" if format_id == 20 else "danbooru"

    tool = _make_tool(monkeypatch, DummyRepo())

    results = tool.detect_usage_counts_for_tags()

    assert results == [{"tag": "cat", "format_name": "e621", "use_count": 5}]


@pytest.mark.db_tools
def test_detect_foreign_key_issues(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def list_tag_statuses(self):
            return [SimpleNamespace(tag_id=999, format_id=1, preferred_tag_id=999, alias=False)]

        def get_tag_by_id(self, tag_id):
            return None

    tool = _make_tool(monkeypatch, DummyRepo())

    assert tool.detect_foreign_key_issues() == [(999, None)]


@pytest.mark.db_tools
def test_detect_orphan_records(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def get_all_tag_ids(self):
            return [1, 2]

        def get_translations(self, tag_id):
            if tag_id == 1:
                return [SimpleNamespace(tag_id=3, language="ja", translation="x")]
            return []

        def list_tag_statuses(self):
            return [SimpleNamespace(tag_id=3, format_id=1, preferred_tag_id=3, alias=False)]

    tool = _make_tool(monkeypatch, DummyRepo())

    orphans = tool.detect_orphan_records()

    assert orphans["translations"] == [(3,)]
    assert orphans["status"] == [(3,)]


@pytest.mark.db_tools
def test_detect_inconsistent_alias_status(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def list_tag_statuses(self):
            return [
                SimpleNamespace(tag_id=1, format_id=1, preferred_tag_id=2, alias=False),
                SimpleNamespace(tag_id=3, format_id=1, preferred_tag_id=3, alias=True),
            ]

    tool = _make_tool(monkeypatch, DummyRepo())

    inconsistencies = tool.detect_inconsistent_alias_status()

    assert len(inconsistencies) == 2
    assert inconsistencies[0]["reason"].startswith("alias=False")
    assert inconsistencies[1]["reason"].startswith("alias=True")


@pytest.mark.db_tools
def test_detect_missing_translations(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def get_tag_languages(self):
            return ["ja", "en"]

        def get_all_tag_ids(self):
            return [1]

        def get_tag_by_id(self, tag_id):
            return SimpleNamespace(tag="cat")

        def get_translations(self, tag_id):
            return [SimpleNamespace(language="ja", translation="ねこ", tag_id=1)]

    tool = _make_tool(monkeypatch, DummyRepo())

    missing = tool.detect_missing_translations(required_languages={"ja", "en"})

    assert missing == [{"tag_id": 1, "tag": "cat", "missing_languages": ["en"]}]


@pytest.mark.db_tools
def test_detect_abnormal_usage_counts(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def get_all_tag_ids(self):
            return [1]

        def get_tag_format_ids(self):
            return [10]

        def get_usage_count(self, tag_id, format_id):
            return -1

        def get_tag_by_id(self, tag_id):
            return SimpleNamespace(tag="cat")

        def get_format_name(self, format_id):
            return "danbooru"

    tool = _make_tool(monkeypatch, DummyRepo())

    abnormal = tool.detect_abnormal_usage_counts(max_threshold=100)

    assert abnormal == [
        {
            "tag_id": 1,
            "tag": "cat",
            "format_id": 10,
            "format_name": "danbooru",
            "count": -1,
            "reason": "使用回数が範囲外 (0~100)",
        }
    ]


@pytest.mark.db_tools
def test_detect_invalid_tag_id(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def get_tag_id_by_name(self, name):
            return 42 if name == "invalid_tag" else None

    tool = _make_tool(monkeypatch, DummyRepo())

    assert tool.detect_invalid_tag_id() == 42


@pytest.mark.db_tools
def test_detect_invalid_preferred_tags(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def list_tag_statuses(self):
            return [SimpleNamespace(tag_id=1, format_id=1, preferred_tag_id=99, alias=True)]

        def get_tag_by_id(self, tag_id):
            return SimpleNamespace(tag="broken")

    tool = _make_tool(monkeypatch, DummyRepo())

    assert tool.detect_invalid_preferred_tags(99) == [(1, "broken")]


@pytest.mark.db_tools
def test_fix_inconsistent_alias_status_updates(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def __init__(self):
            self.updated = []

        def get_tag_status(self, tag_id, format_id):
            return SimpleNamespace(
                tag_id=tag_id,
                format_id=format_id,
                preferred_tag_id=99,
                alias=False,
                type_id=5,
            )

        def update_tag_status(self, **kwargs):
            self.updated.append(kwargs)

    repo = DummyRepo()
    tool = _make_tool(monkeypatch, repo)

    tool.fix_inconsistent_alias_status((10, 2))

    assert repo.updated == [
        {
            "tag_id": 10,
            "format_id": 2,
            "alias": False,
            "preferred_tag_id": 10,
            "type_id": 5,
        }
    ]


@pytest.mark.db_tools
def test_fix_duplicate_status_removes_excess(monkeypatch: pytest.MonkeyPatch):
    class DummyRepo:
        def __init__(self):
            self.deleted = []

        def list_tag_statuses(self, tag_id):
            return [
                SimpleNamespace(tag_id=tag_id, format_id=1),
                SimpleNamespace(tag_id=tag_id, format_id=1),
                SimpleNamespace(tag_id=tag_id, format_id=2),
            ]

        def delete_tag_status(self, tag_id, format_id):
            self.deleted.append((tag_id, format_id))

    repo = DummyRepo()
    tool = _make_tool(monkeypatch, repo)

    tool.fix_duplicate_status(1, 1)

    assert repo.deleted == [(1, 1)]
