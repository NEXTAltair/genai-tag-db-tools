"""CLI smoke tests for the base patch pipeline subcommands (#58/#60/#61)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import genai_tag_db_tools.cli as cli


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> list[dict]:
    cli.main(argv)
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_validate_base_patches_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    patch_file = tmp_path / "patches.jsonl"
    patch_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "patch_id": "sha256:a",
                "patch_type": "translation_correction",
                "target": {"target_type": "translation", "tag": "blue eyes", "field": "translation.ja"},
                "proposed": {"translation": "青い目", "language": "ja"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    objs = _run(["feedback", "validate-base-patches", "--file", str(patch_file)], capsys)
    result = objs[-1]
    assert result["kind"] == "result"
    assert result["ok"] is True
    assert result["valid"] == 1


def test_export_then_apply_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A hand-written base patch file (export already covered by unit tests);
    # here we exercise validate -> apply CLI against an empty base DB build output.
    from sqlalchemy import create_engine

    from genai_tag_db_tools.db.schema import Base, Tag, TagFormat, TagTypeFormatMapping, TagTypeName

    base_db = tmp_path / "base.sqlite"
    engine = create_engine(f"sqlite:///{base_db}")
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker

    with sessionmaker(bind=engine)() as session:
        session.add(TagFormat(format_id=999, format_name="unknown"))
        session.add(TagTypeName(type_name_id=3, type_name="unknown"))
        session.add(TagTypeFormatMapping(format_id=999, type_id=0, type_name_id=3))
        session.add(Tag(tag_id=7, source_tag="pixiv id", tag="pixiv id"))
        session.commit()
    engine.dispose()

    patch_file = tmp_path / "patches.jsonl"
    patch_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": "base",
                "patch_type": "status_correction",
                "target": {
                    "target_type": "tag_status",
                    "tag": "pixiv id",
                    "format_name": "unknown",
                    "field": "TAG_STATUS.deprecated",
                },
                "proposed": {"deprecated": True},
                "approved": True,
                "validated": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    objs = _run(
        ["feedback", "apply-base-patches", "--file", str(patch_file), "--base-db", str(base_db), "--apply"],
        capsys,
    )
    result = objs[-1]
    assert result["kind"] == "result"
    assert result["ok"] is True
    assert result["applied"] == 1


def test_list_commands_unchanged_by_feedback_group(capsys: pytest.CaptureFixture[str]) -> None:
    # feedback subcommands are intentionally not registered as tool specs
    # (settled policy: ADR 0009 / ADR 0005 / docs/cli.md, issue #103). The
    # introspection registry exposes runtime agent-callable commands only;
    # the feedback group is a base-DB build-time maintainer pipeline, so it
    # stays out of the introspection command set.
    objs = _run(["list-commands"], capsys)
    names = {o["name"] for o in objs if o["kind"] == "tool"}
    assert "feedback" not in names
