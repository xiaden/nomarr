"""Schema shape comparator.

Diffs two SchemaShape instances and reports mismatches. Used after
parse_ensure_schema (Shape A) and replay_migrations (Shape B) to verify
that the migration chain produces an identical schema to ensure_schema.

Blacklisted dynamic collections (vector index collections whose names
depend on runtime ML model discovery) are filtered from both shapes
before comparison so that they cannot cause false negatives.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.consolidate_migrations.blacklist import is_blacklisted
from scripts.consolidate_migrations.schema_model import (
    Collection,
    Graph,
    Index,
    SchemaShape,
    SeedDocument,
)


@dataclass(frozen=True)
class SchemaDiff:
    """Result of comparing two SchemaShape instances after blacklist filtering.

    Fields ending in ``_a`` contain items present in Shape A (ensure_schema)
    but missing from Shape B (replayed). Fields ending in ``_b`` are the
    reverse.
    """

    extra_collections_a: frozenset[Collection]
    extra_collections_b: frozenset[Collection]
    extra_indexes_a: frozenset[Index]
    extra_indexes_b: frozenset[Index]
    extra_graphs_a: frozenset[Graph]
    extra_graphs_b: frozenset[Graph]
    extra_seeds_a: frozenset[SeedDocument]
    extra_seeds_b: frozenset[SeedDocument]

    @property
    def is_match(self) -> bool:
        """True when all eight diff frozensets are empty (shapes are equivalent)."""
        return (
            not self.extra_collections_a
            and not self.extra_collections_b
            and not self.extra_indexes_a
            and not self.extra_indexes_b
            and not self.extra_graphs_a
            and not self.extra_graphs_b
            and not self.extra_seeds_a
            and not self.extra_seeds_b
        )


def _filter_shape(
    shape: SchemaShape,
) -> tuple[frozenset[Collection], frozenset[Index], frozenset[Graph], frozenset[SeedDocument]]:
    """Return filtered copies of shape components with blacklisted collections removed.

    Removes Collection entries whose name is blacklisted and Index entries
    whose collection name is blacklisted. Graphs and SeedDocuments are not
    filtered — graph edge definitions reference collections by name but graphs
    themselves are fixed named entities defined in ensure_schema.
    """
    collections = frozenset(c for c in shape.collections if not is_blacklisted(c.name))
    indexes = frozenset(i for i in shape.indexes if not is_blacklisted(i.collection))
    return collections, indexes, shape.graphs, shape.seed_documents


def compare_shapes(shape_a: SchemaShape, shape_b: SchemaShape) -> SchemaDiff:
    """Diff two SchemaShape instances after filtering blacklisted collections.

    Args:
        shape_a: The canonical shape from parse_ensure_schema (ensure_schema source).
        shape_b: The replayed shape from replay_migrations.

    Returns:
        A SchemaDiff describing what is in A but not B and vice versa.
    """
    colls_a, idxs_a, graphs_a, seeds_a = _filter_shape(shape_a)
    colls_b, idxs_b, graphs_b, seeds_b = _filter_shape(shape_b)

    return SchemaDiff(
        extra_collections_a=colls_a - colls_b,
        extra_collections_b=colls_b - colls_a,
        extra_indexes_a=idxs_a - idxs_b,
        extra_indexes_b=idxs_b - idxs_a,
        extra_graphs_a=graphs_a - graphs_b,
        extra_graphs_b=graphs_b - graphs_a,
        extra_seeds_a=seeds_a - seeds_b,
        extra_seeds_b=seeds_b - seeds_a,
    )


def _fmt_collection(c: Collection) -> str:
    kind = "edge" if c.edge else "document"
    return f"  {c.name} ({kind})"


def _fmt_index(i: Index) -> str:
    fields_str = ", ".join(i.fields)
    attrs: list[str] = []
    if i.unique:
        attrs.append("unique")
    if i.sparse:
        attrs.append("sparse")
    if i.expire_after is not None:
        attrs.append(f"ttl={i.expire_after}s")
    attrs_str = f" [{', '.join(attrs)}]" if attrs else ""
    return f"  {i.collection}: {i.index_type}({fields_str}){attrs_str}"


def _fmt_graph(g: Graph) -> str:
    return f"  {g.name}"


def _fmt_seed(s: SeedDocument) -> str:
    return f"  {s.collection}/{s.key}"


def format_diff_report(diff: SchemaDiff) -> str:
    """Produce a human-readable multi-line diff report.

    Returns a single "Shapes match." line when the diff is empty.
    Otherwise groups mismatches by category with clear labels.
    """
    if diff.is_match:
        return "Shapes match."

    lines: list[str] = ["Schema shapes do NOT match:", ""]

    sections: list[tuple[str, frozenset]] = [
        ("Collections only in Shape A (ensure_schema)", diff.extra_collections_a),
        ("Collections only in Shape B (replayed)", diff.extra_collections_b),
        ("Indexes only in Shape A (ensure_schema)", diff.extra_indexes_a),
        ("Indexes only in Shape B (replayed)", diff.extra_indexes_b),
        ("Graphs only in Shape A (ensure_schema)", diff.extra_graphs_a),
        ("Graphs only in Shape B (replayed)", diff.extra_graphs_b),
        ("Seed documents only in Shape A (ensure_schema)", diff.extra_seeds_a),
        ("Seed documents only in Shape B (replayed)", diff.extra_seeds_b),
    ]

    for label, items in sections:
        if not items:
            continue
        lines.append(f"{label} ({len(items)}):")
        if items and next(iter(items)).__class__ is Collection:
            sorted_items = sorted(items, key=lambda c: c.name)  # type: ignore[attr-defined]
            lines.extend(_fmt_collection(c) for c in sorted_items)
        elif items and next(iter(items)).__class__ is Index:
            sorted_items = sorted(items, key=lambda i: (i.collection, i.index_type, i.fields))  # type: ignore[attr-defined]
            lines.extend(_fmt_index(i) for i in sorted_items)
        elif items and next(iter(items)).__class__ is Graph:
            sorted_items = sorted(items, key=lambda g: g.name)  # type: ignore[attr-defined]
            lines.extend(_fmt_graph(g) for g in sorted_items)
        else:
            sorted_items = sorted(items, key=lambda s: (s.collection, s.key))  # type: ignore[attr-defined]
            lines.extend(_fmt_seed(s) for s in sorted_items)
        lines.append("")

    return "\n".join(lines).rstrip()
