"""Consolidation actions: delete old migrations and generate the V001 baseline.

This module handles the post-comparison consolidation step:

1.  **Delete old migrations** — removes V004-V019 migration files from
    ``nomarr/migrations/`` after verifying they match the known set.
2.  **Generate baseline source** — produces the Python source for a new
    ``V001_baseline.py`` migration that idempotently creates all collections,
    indexes, graphs, and seed documents represented in a ``SchemaShape``.
3.  **Generate reset AQL** — produces the two AQL statements needed to clear
    ``applied_migrations`` and reset the ``schema_version`` in ``meta``.
4.  **Write baseline** — writes the generated source to disk, refusing to
    overwrite an existing file.

Intended usage: called by the CLI after ``compare_shapes()`` returns a matching
diff (``diff.is_match is True``).
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

from .blacklist import is_blacklisted
from .migration_replayer import discover_migrations
from .schema_model import Collection, Graph, Index, SchemaShape, SeedDocument

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration files targeted for deletion (V004-V019)
# ---------------------------------------------------------------------------

MIGRATION_FILES_TO_DELETE: tuple[str, ...] = (
    "V004_add_segment_scores_stats.py",
    "V005_add_vectors_track_collections.py",
    "V006_add_applied_migrations.py",
    "V007_split_vectors_hot_cold.py",
    "V008_normalize_cold_vectors.py",
    "V009_rename_essentia_tag_keys.py",
    "V010_add_vram_promises.py",
    "V011_drop_vram_promises_ttl_index.py",
    "V012_drop_gpu_warmup_claims.py",
    "V013_rename_song_tag_edges_collection.py",
    "V014_add_ml_model_graph.py",
    "V015_add_navidrome_song_map.py",
    "V016_add_file_state_edges.py",
    "V017_remove_dead_state_fields.py",
    "V018_split_vectors_per_library.py",
    "V019_navidrome_graph_model.py",
)

# ---------------------------------------------------------------------------
# Source code generation helpers
# ---------------------------------------------------------------------------


def _repr_list(items: list[str]) -> str:
    """Render a list of strings as a compact Python list literal."""
    inner = ", ".join(f'"{item}"' for item in sorted(items))
    return f"[{inner}]"


def _render_collections(collections: frozenset[Collection]) -> str:
    """Render collection-creation code for all non-blacklisted collections."""
    doc_names = sorted(c.name for c in collections if not c.edge and not is_blacklisted(c.name))
    edge_names = sorted(c.name for c in collections if c.edge and not is_blacklisted(c.name))

    lines: list[str] = []
    if doc_names:
        lines.append("    # -- Document collections --")
        for name in doc_names:
            lines.append(f'    if not db.has_collection("{name}"):  # type: ignore[union-attr]')
            lines.append("        with contextlib.suppress(CollectionCreateError):")
            lines.append(f'            db.create_collection("{name}")  # type: ignore[union-attr]')
            lines.append(f'            logger.info("[V001] Created document collection {name}")')
        lines.append("")

    if edge_names:
        lines.append("    # -- Edge collections --")
        for name in edge_names:
            lines.append(f'    if not db.has_collection("{name}"):  # type: ignore[union-attr]')
            lines.append("        with contextlib.suppress(CollectionCreateError):")
            lines.append(f'            db.create_collection("{name}", edge=True)  # type: ignore[union-attr]')
            lines.append(f'            logger.info("[V001] Created edge collection {name}")')
        lines.append("")

    return "\n".join(lines)


def _render_indexes(indexes: frozenset[Index]) -> str:
    """Render index-creation code for all non-blacklisted indexes."""
    filtered = sorted(
        (idx for idx in indexes if not is_blacklisted(idx.collection)),
        key=lambda i: (i.collection, i.index_type, i.fields),
    )
    if not filtered:
        return ""

    lines: list[str] = ["    # -- Indexes --"]
    for idx in filtered:
        fields_repr = "[" + ", ".join(f'"{f}"' for f in idx.fields) + "]"
        if idx.index_type == "ttl":
            expire = idx.expire_after if idx.expire_after is not None else 0
            lines.append("    with contextlib.suppress(IndexCreateError):")
            lines.append(f'        db.collection("{idx.collection}").add_ttl_index(  # type: ignore[union-attr]')
            lines.append(f"            fields={fields_repr}, expiry_time={expire}")
            lines.append("        )")
        else:
            # persistent / hash / skiplist all map to add_persistent_index in python-arango
            kwargs: list[str] = [f"fields={fields_repr}"]
            if idx.unique:
                kwargs.append("unique=True")
            if idx.sparse:
                kwargs.append("sparse=True")
            kwargs_str = ", ".join(kwargs)
            lines.append("    with contextlib.suppress(IndexCreateError):")
            lines.append(
                f'        db.collection("{idx.collection}").add_persistent_index({kwargs_str})  # type: ignore[union-attr]'
            )
    lines.append("")
    return "\n".join(lines)


def _render_graphs(graphs: frozenset[Graph]) -> str:
    """Render graph-creation code for all named graphs."""
    if not graphs:
        return ""

    lines: list[str] = ["    # -- Graphs --"]
    for graph in sorted(graphs, key=lambda g: g.name):
        lines.append(f'    if not db.has_graph("{graph.name}"):  # type: ignore[union-attr]')
        lines.append("        with contextlib.suppress(GraphCreateError):")
        lines.append("            db.create_graph(  # type: ignore[union-attr]")
        lines.append(f'                "{graph.name}",')
        lines.append("                edge_definitions=[")
        for ed in sorted(graph.edge_definitions, key=lambda e: e.edge_collection):
            from_repr = "[" + ", ".join(f'"{c}"' for c in sorted(ed.from_vertex_collections)) + "]"
            to_repr = "[" + ", ".join(f'"{c}"' for c in sorted(ed.to_vertex_collections)) + "]"
            lines.append("                    {")
            lines.append(f'                        "edge_collection": "{ed.edge_collection}",')
            lines.append(f'                        "from_vertex_collections": {from_repr},')
            lines.append(f'                        "to_vertex_collections": {to_repr},')
            lines.append("                    },")
        lines.append("                ],")
        lines.append("            )")
        lines.append(f'            logger.info("[V001] Created graph {graph.name}")')
    lines.append("")
    return "\n".join(lines)


def _render_seeds(seed_documents: frozenset[SeedDocument]) -> str:
    """Render seed-document insertion code."""
    if not seed_documents:
        return ""

    lines: list[str] = ["    # -- Seed documents --"]
    for seed in sorted(seed_documents, key=lambda s: (s.collection, s.key)):
        lines.append(f'    if not db.collection("{seed.collection}").get("{seed.key}"):  # type: ignore[union-attr]')
        lines.append("        with contextlib.suppress(Exception):")
        lines.append(f'            db.collection("{seed.collection}").insert(  # type: ignore[union-attr]')
        lines.append(f'                {{"_key": "{seed.key}"}}, silent=True')
        lines.append("            )")
        lines.append(f'            logger.info("[V001] Inserted seed document {seed.collection}/{seed.key}")')
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_baseline_source(shape: SchemaShape) -> str:
    """Generate Python source for ``V001_baseline.py``.

    The generated file is a complete, idempotent migration that replaces
    V004-V019.  It creates all non-blacklisted collections, indexes, graphs,
    and seed documents from *shape*.

    Args:
        shape: The merged ``SchemaShape`` representing the final schema state
               (typically ``shape_a`` from ``parse_ensure_schema``).

    Returns:
        Python source code string ready to be written to ``V001_baseline.py``.

    """
    collections_code = _render_collections(shape.collections)
    indexes_code = _render_indexes(shape.indexes)
    graphs_code = _render_graphs(shape.graphs)
    seeds_code = _render_seeds(shape.seed_documents)

    body_parts = [p for p in [collections_code, indexes_code, graphs_code, seeds_code] if p.strip()]
    body = "\n".join(body_parts) if body_parts else "    pass  # nothing to create\n"

    # Determine which exception imports are actually needed
    need_collection = bool([c for c in shape.collections if not is_blacklisted(c.name)])
    need_index = bool([i for i in shape.indexes if not is_blacklisted(i.collection)])
    need_graph = bool(shape.graphs)

    import_parts: list[str] = []
    if need_collection:
        import_parts.append("CollectionCreateError")
    if need_graph:
        import_parts.append("GraphCreateError")
    if need_index:
        import_parts.append("IndexCreateError")

    if import_parts:
        arango_import = "    from arango.exceptions import " + ", ".join(import_parts)
    else:
        arango_import = ""

    source = textwrap.dedent(
        '''\
        """V001: Consolidated baseline schema — replaces V004\\u2013V019.

        This migration was generated by ``scripts/consolidate_migrations``
        and represents the cumulative schema state after replaying all
        migrations from V004 through V019.  It idempotently creates all
        collections, indexes, graphs, and seed documents.

        Blacklisted dynamic collection patterns (e.g. per-model vector
        collections) are intentionally excluded — they are created at
        runtime by ``ensure_schema()`` based on the current model state.

        Forward-only; no downgrade path.
        """

        from __future__ import annotations

        import contextlib
        import logging
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from nomarr.persistence.arango_client import DatabaseLike

        logger = logging.getLogger(__name__)

        # Required metadata
        MIGRATION_VERSION: str = "0.0.0"
        DESCRIPTION: str = "Consolidated baseline schema — replaces V004\\u2013V019"


        def upgrade(db: DatabaseLike) -> None:
            """Create all schema objects idempotently.

            This is the consolidated baseline migration produced by the
            consolidation tool.  It creates all collections, indexes, graphs,
            and seed documents previously spread across V004\\u2013V019.

            Safe to run multiple times — all operations use ``has_collection``
            or ``try/except`` guards to avoid errors on re-run.

            Args:
                db: ArangoDB database handle.

            """
        '''
    )

    if arango_import:
        source += arango_import + "\n\n"

    source += body

    return source


def generate_reset_aql() -> str:
    """Return the two AQL statements needed to reset the DB migration state.

    These statements should be executed in an ArangoDB database to clear the
    applied migrations tracking and reset the schema version to ``"0"`` so
    that the new ``V001_baseline.py`` migration will be picked up on the next
    application start.

    Returns:
        Multi-line string containing two AQL statements (separated by a blank
        line), suitable for printing or for direct execution via python-arango.

    """
    return textwrap.dedent(
        """\
        // (1) Clear all documents from applied_migrations:
        FOR doc IN applied_migrations REMOVE doc IN applied_migrations

        // (2) Reset schema_version in the meta collection to "0":
        FOR doc IN meta FILTER doc._key == "schema_version" UPDATE doc WITH {value: "0"} IN meta
        """
    )


def delete_old_migrations(migrations_dir: Path, *, dry_run: bool = True) -> list[Path]:
    """Delete (or list) migration files V004-V019 from *migrations_dir*.

    Cross-validates the delete list against what ``discover_migrations()``
    finds on disk:

    - Warns if any file in ``MIGRATION_FILES_TO_DELETE`` is missing from disk.
    - Warns if ``discover_migrations()`` finds migration files *not* in the
      delete list (i.e. unexpected files that would survive the cleanup).

    Args:
        migrations_dir: Path to the ``nomarr/migrations/`` directory.
        dry_run: If ``True`` (default), only list the files that *would* be
                 deleted without actually removing them.

    Returns:
        List of paths that were deleted (or would be deleted in dry-run mode).

    """
    delete_set = set(MIGRATION_FILES_TO_DELETE)

    # Discover all migration files currently on disk
    discovered = discover_migrations(migrations_dir)
    discovered_names = {p.name for p in discovered}

    # Warn about files on disk but not in our delete list
    unexpected = discovered_names - delete_set
    for name in sorted(unexpected):
        logger.warning(
            "Migration file %s exists on disk but is NOT in MIGRATION_FILES_TO_DELETE — it will NOT be deleted.",
            name,
        )

    # Build the list of paths to act on
    targets: list[Path] = []
    for filename in MIGRATION_FILES_TO_DELETE:
        target = migrations_dir / filename
        if not target.exists():
            logger.warning(
                "Expected migration file %s not found on disk — skipping.",
                filename,
            )
            continue
        targets.append(target)

    if dry_run:
        logger.info("DRY RUN — would delete %d migration file(s):", len(targets))
        for path in targets:
            logger.info("  %s", path)
    else:
        for path in targets:
            path.unlink()
            logger.info("Deleted migration file: %s", path)
        logger.info("Deleted %d migration file(s).", len(targets))

    return targets


def write_baseline(migrations_dir: Path, shape: SchemaShape) -> Path:
    """Write the generated ``V001_baseline.py`` to *migrations_dir*.

    Refuses to overwrite an existing file — raises ``FileExistsError`` if
    ``V001_baseline.py`` already exists in *migrations_dir*.

    Args:
        migrations_dir: Path to the ``nomarr/migrations/`` directory.
        shape: The ``SchemaShape`` to use for baseline generation.

    Returns:
        Path to the written file.

    Raises:
        FileExistsError: If ``V001_baseline.py`` already exists.

    """
    dest = migrations_dir / "V001_baseline.py"
    if dest.exists():
        msg = f"Refusing to overwrite existing file: {dest}"
        raise FileExistsError(msg)

    source = generate_baseline_source(shape)
    dest.write_text(source, encoding="utf-8")
    logger.info("Wrote consolidated baseline migration to %s", dest)
    return dest
