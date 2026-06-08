"""Machine-readable CLI introspection for tag-db (Issue #32).

`describe` / `list-commands` expose each command's input/output/error models,
side effects, and read-only flag as JSONL so agents can construct invocations and
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
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from genai_tag_db_tools.models import (
    AliasRegisterInput,
    AliasRegisterResult,
    CliErrorResult,
    ConvertTagsRequest,
    ConvertTagsResult,
    EnsureDbRequest,
    EnsureDbResult,
    TagRegisterRequest,
    TagRegisterResult,
    TagSearchRequest,
    TagSearchResult,
    TagStatisticsResult,
)

SchemaMode = Literal["compact", "json_schema"]
ModelRole = Literal["input", "output", "error"]


@dataclass(frozen=True)
class ModelRef:
    role: ModelRole
    model: type[BaseModel]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    side_effects: tuple[str, ...]
    read_only: bool
    input_model: type[BaseModel] | None
    output_model: type[BaseModel]

    @property
    def model_refs(self) -> tuple[ModelRef, ...]:
        refs: list[ModelRef] = []
        if self.input_model is not None:
            refs.append(ModelRef("input", self.input_model))
        refs.append(ModelRef("output", self.output_model))
        refs.append(ModelRef("error", CliErrorResult))
        return tuple(refs)


# side_effects / read_only follow docs/cli.md (steady state: base DBs present, no
# --user-db-dir). Cold-cache downloads and --user-db-dir writes are documented
# separately in docs/cli.md.
TOOL_SPECS: dict[str, ToolSpec] = {
    "ensure-dbs": ToolSpec(
        name="ensure-dbs",
        description="Download and prepare base tag databases.",
        side_effects=("network_read", "file_write"),
        read_only=False,
        input_model=EnsureDbRequest,
        output_model=EnsureDbResult,
    ),
    "search": ToolSpec(
        name="search",
        description="Search tags (read-only).",
        side_effects=("db_read",),
        read_only=True,
        input_model=TagSearchRequest,
        output_model=TagSearchResult,
    ),
    "register": ToolSpec(
        name="register",
        description="Register a user tag (writes user DB).",
        side_effects=("db_write",),
        read_only=False,
        input_model=TagRegisterRequest,
        output_model=TagRegisterResult,
    ),
    "stats": ToolSpec(
        name="stats",
        description="Show tag database statistics (read-only).",
        side_effects=("db_read",),
        read_only=True,
        input_model=None,
        output_model=TagStatisticsResult,
    ),
    "convert": ToolSpec(
        name="convert",
        description="Convert tags to a target format (read-only).",
        side_effects=("db_read",),
        read_only=True,
        input_model=ConvertTagsRequest,
        output_model=ConvertTagsResult,
    ),
    "aliases/register": ToolSpec(
        name="aliases/register",
        description="Bulk-register typo alias entries to user DB (dry-run by default).",
        side_effects=("db_write",),
        read_only=False,
        input_model=AliasRegisterInput,
        output_model=AliasRegisterResult,
    ),
}

_JSON_TO_PY = {"string": "str", "boolean": "bool", "number": "float", "object": "dict"}


def iter_tool_specs() -> Iterable[ToolSpec]:
    return TOOL_SPECS.values()


def get_tool_spec(name: str) -> ToolSpec:
    try:
        return TOOL_SPECS[name]
    except KeyError as exc:
        raise ValueError(f"unknown command for describe: {name}") from exc


# --- compact type notation (generated from model_json_schema) ---------------


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


# --- line builders ----------------------------------------------------------


def tool_line(spec: ToolSpec) -> dict[str, object]:
    return {
        "kind": "tool",
        "name": spec.name,
        "message": spec.description,
        "read_only": spec.read_only,
        "side_effects": list(spec.side_effects),
        "input_model": spec.input_model.__name__ if spec.input_model is not None else None,
        "output_model": spec.output_model.__name__,
        "error_model": CliErrorResult.__name__,
    }


def model_lines(spec: ToolSpec) -> list[dict[str, object]]:
    """Compact ``kind:"model"`` lines for input/output/error."""
    return [
        {
            "kind": "model",
            "role": ref.role,
            "name": ref.model.__name__,
            "message": f"{ref.role} for {spec.name}",
            "fields": compact_fields(ref.model),
        }
        for ref in spec.model_refs
    ]


def full_schemas(specs: Iterable[ToolSpec]) -> list[dict[str, object]]:
    """Raw ``model_json_schema()`` for the specs' models (json_schema mode, deduped)."""
    schemas: list[dict[str, object]] = []
    seen: set[str] = set()
    for spec in specs:
        for ref in spec.model_refs:
            if ref.model.__name__ in seen:
                continue
            seen.add(ref.model.__name__)
            schemas.append(ref.model.model_json_schema())
    return schemas
