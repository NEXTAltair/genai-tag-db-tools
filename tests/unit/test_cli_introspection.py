"""Unit tests for CLI introspection (Issue #32): list-commands / describe."""

from __future__ import annotations

import json

import pytest

import genai_tag_db_tools.cli as cli
from genai_tag_db_tools import introspection
from genai_tag_db_tools.models import TagSearchRequest


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> list[str]:
    cli.main(argv)
    return [line for line in capsys.readouterr().out.splitlines() if line.strip()]


class TestListCommands:
    def test_lists_all_commands_as_valid_jsonl(self, capsys: pytest.CaptureFixture[str]) -> None:
        lines = _run(["list-commands"], capsys)
        objs = [json.loads(line) for line in lines]  # every line must be valid JSON

        tools = [o for o in objs if o["kind"] == "tool"]
        assert [t["name"] for t in tools] == [
            "search",
            "register",
            "stats",
            "convert",
            "ensure-dbs",
        ]
        assert objs[-1] == {"kind": "result", "ok": True, "message": "5 commands", "count": 5}

    def test_side_effects_and_read_only_declared(self, capsys: pytest.CaptureFixture[str]) -> None:
        tools = {
            json.loads(line)["name"]: json.loads(line)
            for line in _run(["list-commands"], capsys)
            if json.loads(line)["kind"] == "tool"
        }
        assert tools["search"]["read_only"] is True
        assert tools["search"]["side_effects"] == ["db_read"]
        assert tools["register"]["read_only"] is False
        assert tools["register"]["side_effects"] == ["db_write"]
        assert tools["ensure-dbs"]["side_effects"] == ["network_read", "file_write"]


class TestDescribeCompact:
    def test_describe_search_tool_and_models(self, capsys: pytest.CaptureFixture[str]) -> None:
        objs = [json.loads(line) for line in _run(["describe", "search"], capsys)]

        tool = objs[0]
        assert tool["kind"] == "tool"
        assert tool["name"] == "search"

        models = {o["role"]: o for o in objs if o["kind"] == "model"}
        assert set(models) == {"input", "output"}
        fields = models["input"]["fields"]
        assert fields["query"] == "str (required)"
        assert fields["partial"] == "bool=true"
        assert fields["limit"] == "int>=1?"
        assert fields["offset"] == "int>=0"
        assert fields["format_names"] == "list[str]?"
        assert models["output"]["fields"]["items"] == "list[TagRecordPublic] (required)"
        assert objs[-1]["kind"] == "result"

    def test_input_fields_match_model_not_handwritten(self, capsys: pytest.CaptureFixture[str]) -> None:
        """fields のキーが Pydantic model_fields と一致 (手書きでなく生成の証明)。"""
        objs = [json.loads(line) for line in _run(["describe", "search"], capsys)]
        input_model = next(o for o in objs if o.get("role") == "input")
        assert set(input_model["fields"]) == set(TagSearchRequest.model_fields)

    def test_describe_stats_has_no_input_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        objs = [json.loads(line) for line in _run(["describe", "stats"], capsys)]
        roles = {o["role"] for o in objs if o["kind"] == "model"}
        assert roles == {"output"}  # stats takes no semantic input model
        assert objs[0]["input_model"] is None


class TestDescribeJsonSchema:
    def test_full_schema_is_note_then_raw_json_lines(self, capsys: pytest.CaptureFixture[str]) -> None:
        lines = _run(["describe", "search", "--schema", "json_schema"], capsys)
        # 先頭は人間向け # note (JSON ではない)
        assert lines[0].startswith("# ")
        with pytest.raises(json.JSONDecodeError):
            json.loads(lines[0])
        # 後続は生の model_json_schema (title/properties を持つ JSON)
        schemas = [json.loads(line) for line in lines[1:]]
        titles = {s.get("title") for s in schemas}
        assert "TagSearchRequest" in titles
        assert "TagSearchResult" in titles
        assert all("properties" in s for s in schemas)


class TestDescribeUnknown:
    def test_unknown_command_is_invalid_input_exit_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["describe", "nope"])
        assert int(exit_info.value.code or 0) == 2
        last = json.loads([line for line in capsys.readouterr().out.splitlines() if line.strip()][-1])
        assert last["kind"] == "error"
        assert last["code"] == "INVALID_INPUT"


class TestCompactRenderer:
    def test_find_command(self) -> None:
        assert introspection.find_command("search") is not None
        assert introspection.find_command("nope") is None
