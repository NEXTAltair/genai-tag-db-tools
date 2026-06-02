"""Machine-readable CLI introspection for tag-db (Issue #32).

`describe` / `list-commands` expose each command's input/output models, side
effects, and read-only flag as JSONL so agents can construct invocations and
decide whether a command is safe to run without parsing `--help` text.

Schemas are generated from the Pydantic models in ``models.py`` (the single
source of truth); this module never hand-writes field schemas. Two schema modes:

- ``compact`` (default): a short type notation per field (human + agent
  readable). Nested models are referenced by name.
- ``json_schema``: the full ``model_json_schema()`` (emitted by the CLI as a
  documented exception to the JSONL contract; see ADR 0005 / docs/cli.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel

from genai_tag_db_tools.models import (
    ConvertRequest,
    ConvertResult,
    EnsureDbRequest,
    EnsureDbResult,
    TagRegisterRequest,
    TagRegisterResult,
    TagSearchRequest,
    TagSearchResult,
    TagStatisticsResult,
)


@dataclass(frozen=True)
class CommandSpec:
    """Static metadata for one CLI command.

    Schemas are generated from ``input_model`` / ``output_model``; only the
    metadata that cannot be derived from the models is declared here.
    """

    name: str
    description: str
    side_effects: tuple[str, ...]
    read_only: bool
    input_model: type[BaseModel] | None
    output_model: type[BaseModel] | None


# side_effects / read_only follow docs/cli.md (steady state: base DBs present,
# no --user-db-dir). Cold-cache downloads and --user-db-dir writes are documented
# separately in docs/cli.md.
COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("search", "Search tags (read-only)", ("db_read",), True, TagSearchRequest, TagSearchResult),
    CommandSpec(
        "register",
        "Register a tag (writes user DB)",
        ("db_write",),
        False,
        TagRegisterRequest,
        TagRegisterResult,
    ),
    CommandSpec(
        "stats", "Show database statistics (read-only)", ("db_read",), True, None, TagStatisticsResult
    ),
    CommandSpec(
        "convert", "Convert tags to a format (read-only)", ("db_read",), True, ConvertRequest, ConvertResult
    ),
    CommandSpec(
        "ensure-dbs",
        "Download base DBs",
        ("network_read", "file_write"),
        False,
        EnsureDbRequest,
        EnsureDbResult,
    ),
)

_BY_NAME = {spec.name: spec for spec in COMMANDS}

_JSON_TO_PY = {"string": "str", "boolean": "bool", "number": "float", "object": "dict"}


def find_command(name: str) -> CommandSpec | None:
    """Return the spec for ``name`` or None if unknown."""
    return _BY_NAME.get(name)


def _strip_nullable(prop: dict[str, object]) -> tuple[dict[str, object], bool]:
    """Resolve ``X | None`` (anyOf with a null member) to (non-null schema, nullable)."""
    any_of = prop.get("anyOf")
    if isinstance(any_of, list):
        non_null = [m for m in any_of if isinstance(m, dict) and m.get("type") != "null"]
        nullable = any(isinstance(m, dict) and m.get("type") == "null" for m in any_of)
        if non_null:
            return non_null[0], nullable
    return prop, False


def _base_type(schema: dict[str, object]) -> str:
    """Render a (non-nullable) JSON Schema fragment to compact type notation."""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return ref.split("/")[-1]
    enum = schema.get("enum")
    if isinstance(enum, list):
        return "enum[" + ",".join(str(v) for v in enum) + "]"
    type_ = schema.get("type")
    if type_ == "array":
        items = schema.get("items")
        return f"list[{_base_type(items)}]" if isinstance(items, dict) else "list"
    if type_ == "integer":
        base = "int"
        if "minimum" in schema:
            base += f">={schema['minimum']}"
        if "maximum" in schema:
            base += f"<={schema['maximum']}"
        return base
    return _JSON_TO_PY.get(type_, type_ or "any") if isinstance(type_, str) else "any"


def _has_constraint(schema: dict[str, object]) -> bool:
    return any(key in schema for key in ("minimum", "maximum", "enum"))


def _field_notation(prop: dict[str, object], required: bool) -> str:
    inner, nullable = _strip_nullable(prop)
    base = _base_type(inner)
    if required:
        return f"{base} (required)"
    if nullable:
        return f"{base}?"
    default = prop.get("default")
    if default is not None and not _has_constraint(inner):
        return f"{base}={json.dumps(default, ensure_ascii=False)}"
    return base


def compact_fields(model: type[BaseModel]) -> dict[str, str]:
    """Compact ``field -> type notation`` map generated from the model schema."""
    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    return {
        name: _field_notation(prop, name in required)
        for name, prop in properties.items()
        if isinstance(prop, dict)
    }


def tool_line(spec: CommandSpec) -> dict[str, object]:
    """Build the ``kind:"tool"`` line for a command."""
    return {
        "kind": "tool",
        "name": spec.name,
        "message": spec.description,
        "read_only": spec.read_only,
        "side_effects": list(spec.side_effects),
        "input_model": spec.input_model.__name__ if spec.input_model else None,
        "output_model": spec.output_model.__name__ if spec.output_model else None,
    }


def model_lines(spec: CommandSpec) -> list[dict[str, object]]:
    """Build the ``kind:"model"`` lines (compact) for a command's input/output."""
    lines: list[dict[str, object]] = []
    for role, model in (("input", spec.input_model), ("output", spec.output_model)):
        if model is None:
            continue
        lines.append(
            {
                "kind": "model",
                "role": role,
                "name": model.__name__,
                "message": f"{role} for {spec.name}",
                "fields": compact_fields(model),
            }
        )
    return lines


def full_schemas(spec: CommandSpec) -> list[dict[str, object]]:
    """Raw ``model_json_schema()`` for the command's models (json_schema mode)."""
    return [
        model.model_json_schema() for model in (spec.input_model, spec.output_model) if model is not None
    ]
