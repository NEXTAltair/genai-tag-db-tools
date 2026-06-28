"""Report writers (TSV / JSONL) for the base patch pipeline."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

ReportFormat = Literal["tsv", "jsonl"]


def infer_report_format(path: Path, *, default: ReportFormat = "tsv") -> ReportFormat:
    suffix = path.suffix.lower()
    if suffix in (".jsonl", ".ndjson", ".json"):
        return "jsonl"
    if suffix in (".tsv", ".tab", ".csv", ".txt"):
        return "tsv"
    return default


def write_report(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[dict[str, Any]],
    *,
    report_format: ReportFormat | None = None,
) -> None:
    """Write report rows to ``path`` as TSV (header + tab-separated) or JSONL."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    fmt = report_format or infer_report_format(path)

    if fmt == "jsonl":
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str))
                fh.write("\n")
        return

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if row.get(col) is None else _cell(row.get(col)) for col in columns])


def _cell(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)
