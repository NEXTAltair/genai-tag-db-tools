"""OKF (Open Knowledge Format) バンドル操作の共有ユーティリティ。

stdlib のみで動作する。frontmatter のパースとバンドル走査を提供し、
``okf_validate.py`` / ``okf_index.py`` から import される。

OKF SPEC: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

frontmatter パーサは YAML 全体ではなく、OKF が想定する素直な部分集合だけを扱う:

- ``key: value`` のスカラー (前後の引用符は除去)
- ``key: [a, b, c]`` のインラインリスト
- 次行以降に ``  - item`` が並ぶブロックリスト

ネストした map やフロースタイル map は対象外 (OKF concept frontmatter には不要)。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

# 任意の階層に置けて、概念ドキュメントには使えない予約ファイル名 (OKF SPEC §3.1)。
RESERVED_FILENAMES = frozenset({"index.md", "log.md"})


def split_frontmatter(text: str) -> tuple[str, str]:
    """先頭の ``---`` で囲まれた frontmatter ブロックと本文を分離して返す。

    Args:
        text: Markdown ファイル全体の文字列。

    Returns:
        ``(frontmatter_block, body)`` のタプル。frontmatter が無ければ
        ``("", text)`` を返す。frontmatter_block は ``---`` 区切り行を含まない。

    Raises:
        ValueError: 開始 ``---`` 区切りがあるのに閉じ ``---`` が無い
            (unterminated frontmatter) 場合。``--skip-missing`` で malformed を
            「未付与」と取り違えないための guardrail。
    """
    if not text.startswith("---"):
        return "", text
    # 開始 --- 行の直後から、次の --- 行までを frontmatter とする。
    # rstrip() で CRLF (``---\r``) や末尾空白も区切りとして認識する。
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return "", text
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            block = "".join(lines[1:i])
            body = "".join(lines[i + 1 :])
            return block, body
    raise ValueError("frontmatter の閉じ '---' が無い (unterminated)")


def _strip_scalar(value: str) -> str:
    """スカラー値の前後空白と一重/二重引用符を除去する。

    クォートで始まるのに同じクォートで閉じていない値 (例: ``"Broken``) は
    不正な YAML スカラーとして ``ValueError`` を送出する。frontmatter を契約とする
    OKF バンドル (ADR 0010 / LoRAIro ADR 0082) で、検証が malformed scalar を
    silently 通さないための guardrail。
    """
    value = value.strip()
    if value and value[0] in "\"'":
        if len(value) >= 2 and value[-1] == value[0]:
            return value[1:-1]
        raise ValueError(f"不正な quoted scalar (クォート未終端): {value!r}")
    return value


def _parse_inline_list(value: str) -> list[str]:
    """``[a, b, c]`` 形式のインラインリストを要素リストへ変換する。"""
    inner = value.strip()[1:-1].strip()
    if not inner:
        return []
    return [_strip_scalar(item) for item in inner.split(",") if item.strip()]


def parse_frontmatter(text: str) -> dict[str, str | list[str]]:
    """Markdown の frontmatter をパースして key/value の dict を返す。

    OKF が想定する素直な部分集合のみ対応 (モジュール docstring 参照)。

    Args:
        text: Markdown ファイル全体の文字列。

    Returns:
        frontmatter の key/value。値はスカラー (str) かリスト (list[str])。
        frontmatter が無ければ空 dict。
    """
    block, _ = split_frontmatter(text)
    if not block:
        return {}
    result: dict[str, str | list[str]] = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("["):
            # inline list は ']' で閉じる必要がある。未終端 (例: ``[webapi``) は
            # plain scalar に fall through させず reject する (tags/depends_on は
            # 機械可読な list である契約。ADR 0010)。
            if not raw.endswith("]"):
                raise ValueError(f"不正な inline list (']' 未終端): {raw!r}")
            result[key] = _parse_inline_list(raw)
        elif raw == "":
            # ブロックリストの可能性: 次行以降の "  - item" を集める。
            items: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                items.append(_strip_scalar(lines[i].lstrip()[2:]))
                i += 1
            result[key] = items
        else:
            result[key] = _strip_scalar(raw)
    return result


def iter_concept_files(
    bundle_root: Path, *, extra_excludes: frozenset[str] = frozenset()
) -> Iterator[Path]:
    """バンドル配下の概念ドキュメント (*.md) を名前順に列挙する。

    予約ファイル名 (``index.md`` / ``log.md``) と ``extra_excludes`` の
    ファイル名は除外する。

    Args:
        bundle_root: バンドルのルートディレクトリ。
        extra_excludes: 追加で除外するファイル名の集合 (例: ``{"README.md"}``)。

    Yields:
        概念ドキュメントの Path。
    """
    excludes = RESERVED_FILENAMES | extra_excludes
    for path in sorted(bundle_root.rglob("*.md")):
        if path.name in excludes:
            continue
        yield path


def as_scalar(value: str | list[str] | None) -> str:
    """frontmatter 値を表示用スカラー文字列へ正規化する。"""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(value)
    return value
