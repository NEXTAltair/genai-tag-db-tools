"""OKF バンドルの索引を frontmatter から生成する汎用ツール (stdlib only)。

frontmatter を唯一の正準ソース (SSoT) とみなし、そこから派生ビューを生成する:

- ``--index``  : OKF SPEC §6 の ``index.md`` (箇条書き、progressive disclosure) を生成。
- ``--table``  : 人間向け Markdown テーブルを生成。列は frontmatter キーで指定するため
  プロジェクト非依存 (``--columns id,title,timestamp,status`` 等)。

いずれも ``--check`` で「生成結果が既存ファイルと一致するか」だけを検証できる
(CI/skill が drift を検出する用途)。``--table-output`` 先に
``<!-- OKF-TABLE:START -->`` / ``<!-- OKF-TABLE:END -->`` マーカーがあれば、その間だけを
置換するため、テーブル前後の人手の散文 (説明・テンプレ) を保持できる。

特殊列:
- ``id``   : ファイル名先頭の連番 (例 ``0001-foo.md`` -> ``0001``)。無ければ stem。
- ``file`` : ファイル名。

使い方:
    python3 okf_index.py --bundle-root docs/decisions --index --exclude README.md
    python3 okf_index.py --bundle-root docs/decisions --table \\
        --columns id,title,timestamp,status --headers "ADR,タイトル,日付,ステータス" \\
        --link-column id --table-output docs/decisions/README.md
    python3 okf_index.py --bundle-root docs/decisions --table ... --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _okf import as_scalar, iter_concept_files, parse_frontmatter

TABLE_START = "<!-- OKF-TABLE:START -->"
TABLE_END = "<!-- OKF-TABLE:END -->"
_LEADING_NUM = re.compile(r"^(\d+)")


def _id_of(path: Path) -> str:
    m = _LEADING_NUM.match(path.stem)
    return m.group(1) if m else path.stem


def _cell(path: Path, fm: dict[str, str | list[str]], col: str) -> str:
    if col == "id":
        return _id_of(path)
    if col == "file":
        return path.name
    if col == "title":
        return as_scalar(fm.get("title")) or path.stem
    return as_scalar(fm.get(col))


def _md_escape(text: str) -> str:
    """テーブルセル内のパイプをエスケープする。"""
    return text.replace("|", "\\|")


def _collect(
    bundle_root: Path, excludes: frozenset[str], sort_by: str
) -> list[tuple[Path, dict[str, str | list[str]]]]:
    rows = [
        (p, parse_frontmatter(p.read_text(encoding="utf-8")))
        for p in iter_concept_files(bundle_root, extra_excludes=excludes)
    ]
    if sort_by == "file":
        rows.sort(key=lambda r: r[0].name)
    else:
        rows.sort(key=lambda r: _cell(r[0], r[1], sort_by))
    return rows


def build_index(
    rows: list[tuple[Path, dict[str, str | list[str]]]], bundle_root: Path, title: str, title_key: str
) -> str:
    """OKF SPEC §6 形式の index.md 本文を生成する。"""
    lines = [f"# {title}", ""]
    for path, fm in rows:
        rel = path.relative_to(bundle_root).as_posix()
        label = as_scalar(fm.get(title_key)) or path.stem
        desc = as_scalar(fm.get("description"))
        entry = f"* [{label}]({rel})"
        if desc:
            entry += f" — {desc}"
        lines.append(entry)
    lines.append("")
    return "\n".join(lines)


def build_table(
    rows: list[tuple[Path, dict[str, str | list[str]]]],
    bundle_root: Path,
    columns: list[str],
    headers: list[str],
    link_column: str | None,
) -> str:
    """Markdown テーブル本文を生成する。"""
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for path, fm in rows:
        cells: list[str] = []
        rel = path.relative_to(bundle_root).as_posix()
        for col in columns:
            value = _md_escape(_cell(path, fm, col))
            if col == link_column:
                value = f"[{value}]({rel})"
            cells.append(value)
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _inject(existing: str, table: str) -> str:
    """マーカー間にテーブルを差し込む。無ければテーブルのみを返す。"""
    if TABLE_START in existing and TABLE_END in existing:
        pre = existing[: existing.index(TABLE_START) + len(TABLE_START)]
        post = existing[existing.index(TABLE_END) :]
        return f"{pre}\n{table}\n{post}"
    return table + "\n"


def _emit(content: str, output: Path | None, check: bool, label: str) -> int:
    """書き込み or --check 検証。差分があれば 1 を返す。"""
    if output is None:
        print(content)
        return 0
    current = output.read_text(encoding="utf-8") if output.exists() else ""
    if check:
        if current != content:
            print(f"DRIFT: {output} が最新でない ({label} を再生成してください)", file=sys.stderr)
            return 1
        print(f"OK: {output} は最新 ({label})")
        return 0
    output.write_text(content, encoding="utf-8")
    print(f"生成: {output} ({label})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OKF バンドルの索引を frontmatter から生成する。")
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--exclude", default="", help="除外ファイル名のカンマ区切り。")
    parser.add_argument("--sort-by", default="file", help="並び替えに使う列 (既定: file)。")
    parser.add_argument("--check", action="store_true", help="書き込まず最新かどうか検証する。")
    # index
    parser.add_argument("--index", action="store_true", help="index.md を生成する。")
    parser.add_argument(
        "--index-output", type=Path, default=None, help="index.md の出力先 (既定: <root>/index.md)。"
    )
    parser.add_argument("--index-title", default="Index")
    parser.add_argument("--title-key", default="title")
    # table
    parser.add_argument("--table", action="store_true", help="Markdown テーブルを生成する。")
    parser.add_argument("--columns", default="id,title,timestamp,status")
    parser.add_argument("--headers", default="", help="表示ヘッダのカンマ区切り (既定: columns と同じ)。")
    parser.add_argument("--link-column", default=None, help="リンク化する列名。")
    parser.add_argument("--table-output", type=Path, default=None)
    args = parser.parse_args()

    bundle_root: Path = args.bundle_root
    if not bundle_root.is_dir():
        print(f"エラー: バンドルが見つからない: {bundle_root}", file=sys.stderr)
        return 2
    if not (args.index or args.table):
        print("エラー: --index か --table のいずれかを指定してください。", file=sys.stderr)
        return 2

    excludes = frozenset(k.strip() for k in args.exclude.split(",") if k.strip())
    rows = _collect(bundle_root, excludes, args.sort_by)

    rc = 0
    if args.index:
        content = build_index(rows, bundle_root, args.index_title, args.title_key)
        output = args.index_output or (bundle_root / "index.md")
        rc |= _emit(content, output, args.check, "index.md")
    if args.table:
        columns = [c.strip() for c in args.columns.split(",") if c.strip()]
        headers = [h.strip() for h in args.headers.split(",")] if args.headers else columns
        if len(headers) != len(columns):
            print("エラー: --headers の数が --columns と一致しません。", file=sys.stderr)
            return 2
        table = build_table(rows, bundle_root, columns, headers, args.link_column)
        if args.table_output is not None:
            existing = args.table_output.read_text(encoding="utf-8") if args.table_output.exists() else ""
            content = _inject(existing, table)
        else:
            content = table
        rc |= _emit(content, args.table_output, args.check, "table")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
