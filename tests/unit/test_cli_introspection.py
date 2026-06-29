"""Unit tests for CLI introspection (Issue #32): compact / json_schema modes."""

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
        objs = [json.loads(line) for line in _run(["list-commands"], capsys)]
        tools = [o for o in objs if o["kind"] == "tool"]
        assert {t["name"] for t in tools} == {
            "ensure-dbs",
            "search",
            "register",
            "stats",
            "convert",
            "aliases/register",
            "recommend/tag",
            "recommend/translation",
        }
        assert objs[-1] == {"kind": "result", "ok": True, "message": "commands listed", "count": 8}

    def test_side_effects_and_read_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        tools = {
            obj["name"]: obj
            for obj in (json.loads(line) for line in _run(["list-commands"], capsys))
            if obj["kind"] == "tool"
        }
        assert tools["search"]["read_only"] is True
        assert tools["search"]["side_effects"] == ["db_read"]
        assert tools["register"]["read_only"] is False
        assert tools["register"]["side_effects"] == ["db_write"]
        assert tools["ensure-dbs"]["side_effects"] == ["network_read", "file_write"]
        # recommend は advisory read-only。tag は DB を引き、translation は純計算。
        assert tools["recommend/tag"]["read_only"] is True
        assert tools["recommend/tag"]["side_effects"] == ["db_read"]
        assert tools["recommend/translation"]["read_only"] is True
        assert tools["recommend/translation"]["side_effects"] == []


class TestDescribeCompact:
    def test_describe_search_tool_and_models(self, capsys: pytest.CaptureFixture[str]) -> None:
        objs = [json.loads(line) for line in _run(["describe", "search"], capsys)]
        assert objs[0]["kind"] == "tool"
        assert objs[0]["name"] == "search"

        models = {o["role"]: o for o in objs if o["kind"] == "model"}
        assert set(models) == {"input", "output", "error"}
        fields = models["input"]["fields"]
        assert fields["query"] == "str (required)"
        assert fields["partial"] == "bool=true"
        assert fields["limit"] == "int>=1?"
        assert fields["offset"] == "int>=0"
        assert fields["format_names"] == "list[str]?"
        assert models["output"]["fields"]["items"] == "list[TagRecordPublic] (required)"
        assert objs[-1] == {
            "kind": "result",
            "ok": True,
            "message": "command described",
            "command": "search",
        }

    def test_input_fields_match_model_not_handwritten(self, capsys: pytest.CaptureFixture[str]) -> None:
        """fields のキーが Pydantic model_fields と一致 (手書きでなく生成の証明)。"""
        objs = [json.loads(line) for line in _run(["describe", "search"], capsys)]
        input_model = next(o for o in objs if o.get("role") == "input")
        assert set(input_model["fields"]) == set(TagSearchRequest.model_fields)

    def test_describe_stats_has_no_input_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        objs = [json.loads(line) for line in _run(["describe", "stats"], capsys)]
        assert objs[0]["input_model"] is None
        roles = {o["role"] for o in objs if o["kind"] == "model"}
        assert roles == {"output", "error"}  # stats takes no semantic input model


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
        assert {"TagSearchRequest", "TagSearchResult", "CliErrorResult"} <= titles
        assert all("properties" in s for s in schemas)


class TestDescribeUnknown:
    def test_unknown_command_is_invalid_input_exit_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["describe", "nope"])
        assert int(exit_info.value.code or 0) == 2
        last = json.loads([line for line in capsys.readouterr().out.splitlines() if line.strip()][-1])
        assert last["kind"] == "error"
        assert last["code"] == "INVALID_INPUT"


class TestSpecs:
    def test_get_tool_spec(self) -> None:
        assert introspection.get_tool_spec("search").name == "search"
        with pytest.raises(ValueError, match="unknown command"):
            introspection.get_tool_spec("nope")
