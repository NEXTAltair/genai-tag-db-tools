from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from genai_tag_db_tools.models import (
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

SchemaMode = Literal["inline", "ref", "none"]
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
        description="Search tags.",
        side_effects=("db_read",),
        read_only=True,
        input_model=TagSearchRequest,
        output_model=TagSearchResult,
    ),
    "register": ToolSpec(
        name="register",
        description="Register a user tag.",
        side_effects=("db_write",),
        read_only=False,
        input_model=TagRegisterRequest,
        output_model=TagRegisterResult,
    ),
    "stats": ToolSpec(
        name="stats",
        description="Show tag database statistics.",
        side_effects=("db_read",),
        read_only=True,
        input_model=None,
        output_model=TagStatisticsResult,
    ),
    "convert": ToolSpec(
        name="convert",
        description="Convert tags to a target format.",
        side_effects=("db_read",),
        read_only=True,
        input_model=ConvertTagsRequest,
        output_model=ConvertTagsResult,
    ),
}


def iter_tool_specs() -> Iterable[ToolSpec]:
    return TOOL_SPECS.values()


def get_tool_spec(name: str) -> ToolSpec:
    try:
        return TOOL_SPECS[name]
    except KeyError as exc:
        raise ValueError(f"unknown command for describe: {name}") from exc


def tool_line(spec: ToolSpec) -> dict[str, object]:
    return {
        "kind": "tool",
        "name": spec.name,
        "description": spec.description,
        "side_effects": list(spec.side_effects),
        "read_only": spec.read_only,
        "input_model": spec.input_model.__name__ if spec.input_model is not None else None,
        "output_model": spec.output_model.__name__,
        "error_model": CliErrorResult.__name__,
    }


def model_line(ref: ModelRef, schema_mode: SchemaMode) -> dict[str, object]:
    line: dict[str, object] = {
        "kind": "model",
        "role": ref.role,
        "name": ref.model.__name__,
        "version": "1",
        "schema_format": schema_mode,
    }
    if schema_mode == "inline":
        line["schema"] = ref.model.model_json_schema()
    elif schema_mode == "ref":
        line["ref"] = f"#/models/{ref.model.__name__}"
    return line


def iter_model_lines(specs: Iterable[ToolSpec], schema_mode: SchemaMode) -> Iterable[dict[str, object]]:
    if schema_mode == "none":
        return

    seen: set[tuple[ModelRole, str]] = set()
    for spec in specs:
        for ref in spec.model_refs:
            key = (ref.role, ref.model.__name__)
            if key in seen:
                continue
            seen.add(key)
            yield model_line(ref, schema_mode)
