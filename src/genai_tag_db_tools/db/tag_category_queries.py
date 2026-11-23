"""検索分類テーブル (TAG_CATEGORIES / TAG_CATEGORY_MEMBERSHIPS) の読み取りクエリ (Issue #153)。

分類テーブルは公開 base DB にだけあり、旧 DB には無い。ここでは作成・migration を一切せず、
呼び出し側が ``has_category_tables`` で有無を確かめてから使う。

ID の集合は ``json_each`` で 1 つの bind 変数に束ねる。件数によらず 1 文で済み、
SQLite の bind 変数上限 (古い SQLite は 999) にも当たらない。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import exists, func, inspect, select
from sqlalchemy.orm import Session

from genai_tag_db_tools.db.schema import Tag, TagCategoryMembership, TagCategoryNode
from genai_tag_db_tools.models import TagCategory

CATEGORY_TABLES = (TagCategoryNode.__tablename__, TagCategoryMembership.__tablename__)


def has_category_tables(session: Session) -> bool:
    """接続先 DB に分類テーブルが 2 つともあるかを返す。"""
    inspector = inspect(session.connection())
    return all(inspector.has_table(name) for name in CATEGORY_TABLES)


def category_sort_key(category: TagCategory) -> tuple[str, list[str]]:
    """namespace → path の順で並べるためのキー。"""
    return category.namespace, category.path


def to_public_category(node: TagCategoryNode) -> TagCategory:
    """ORM ノードを公開型へ変換する。``path`` は JSON 文字列の配列。"""
    return TagCategory(
        category_id=node.category_id,
        namespace=node.namespace,
        parent_id=node.parent_id,
        label=node.label,
        depth=node.depth,
        path=json.loads(node.path),
    )


def _json_values(values: Iterable[object]) -> Any:
    """値の集合を ``SELECT value FROM json_each(?)`` (bind 変数 1 つ) にする。"""
    table = func.json_each(json.dumps(list(values), ensure_ascii=False)).table_valued("value")
    return select(table.c.value)


def category_ids_select(category_ids: list[str], *, include_descendants: bool) -> Any:
    """指定分類 (と子孫) の category_id を返す SELECT を作る。

    子孫は ``parent_id`` を辿る再帰 CTE で解決する。``UNION`` で重複を除くため、
    万一の循環参照でも停止する。
    """
    seeds = select(TagCategoryNode.category_id).where(
        TagCategoryNode.category_id.in_(_json_values(category_ids))
    )
    if not include_descendants:
        return seeds
    tree = seeds.cte("category_tree", recursive=True)
    children = select(TagCategoryNode.category_id).join(
        tree, TagCategoryNode.parent_id == tree.c.category_id
    )
    tree = tree.union(children)
    return select(tree.c.category_id)


def apply_category_exists_filter(
    query: Any,
    tag_id_column: Any,
    category_ids: list[str],
    *,
    include_descendants: bool,
) -> Any:
    """指定分類のいずれかに所属するタグだけに絞る (OR)。EXISTS なので行は重複しない。"""
    membership = select(TagCategoryMembership.tag_id).where(
        TagCategoryMembership.tag_id == tag_id_column,
        TagCategoryMembership.category_id.in_(
            category_ids_select(category_ids, include_descendants=include_descendants)
        ),
    )
    return query.filter(exists(membership))


def list_categories(session: Session, namespace: str | None = None) -> list[TagCategory]:
    """分類ノードを namespace → path 順で返す。"""
    query = session.query(TagCategoryNode)
    if namespace is not None:
        query = query.filter(TagCategoryNode.namespace == namespace)
    return sorted((to_public_category(node) for node in query.all()), key=category_sort_key)


def categories_by_tag(session: Session, tag_ids: list[int]) -> dict[int, tuple[str, list[TagCategory]]]:
    """tag_id ごとのタグ文字列と所属分類を 1 文で取得する。

    タグ文字列も返すのは、複数 DB で同じ数値 tag_id が別のタグを指す場合に、呼び出し側が
    無関係なタグへ分類を付けないよう照合するため。

    Returns:
        分類を持つ tag_id → (この DB の TAGS.tag, 分類 (namespace → path 順))。
        分類の無い tag_id はキーを持たない。
    """
    if not tag_ids:
        return {}
    rows = (
        session.query(TagCategoryMembership.tag_id, Tag.tag, TagCategoryNode)
        .join(TagCategoryNode, TagCategoryNode.category_id == TagCategoryMembership.category_id)
        .join(Tag, Tag.tag_id == TagCategoryMembership.tag_id)
        .filter(TagCategoryMembership.tag_id.in_(_json_values(sorted(set(tag_ids)))))
        .all()
    )
    result: dict[int, tuple[str, list[TagCategory]]] = {}
    for tag_id, tag, node in rows:
        result.setdefault(tag_id, (tag, []))[1].append(to_public_category(node))
    for _, categories in result.values():
        categories.sort(key=category_sort_key)
    return result


def category_counts(session: Session) -> tuple[int, int]:
    """(分類ノード数, 所属関係数) を返す。"""
    node_count = session.query(func.count()).select_from(TagCategoryNode).scalar() or 0
    membership_count = session.query(func.count()).select_from(TagCategoryMembership).scalar() or 0
    return int(node_count), int(membership_count)
