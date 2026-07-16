"""CLI entry point for the migration consolidation tool — HISTORICAL (ArangoDB era).

This tool was used to consolidate ArangoDB migration files (V004-V019)
into a single V001_baseline.py migration.  It is no longer applicable
after the PostgreSQL transition.  Retained for historical reference only.

Run as:
    python -m scripts.consolidate_migrations [options]

Two modes of operation:

``validate`` (default):
    Parse ensure_schema -> Shape A, replay migrations -> Shape B, compare
    them, print the diff report.  Exits 0 if shapes match, 1 if they
    differ, 2 on runtime errors.

``--consolidate``:
    Performs validate first (hard fail if shapes don't match), then
    generates the new V001_baseline.py migration, deletes old migrations
    (V004-V019), and prints the reset AQL.

``--execute-db-reset`` (implies ``--consolidate``):
    After consolidation, connects to the database and executes the reset
    statements to clear applied_migrations and reset schema_version.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Default paths (relative to repo root, resolved at runtime)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_MIGRATIONS_DIR = _REPO_ROOT / "nomarr" / "migrations"
_DEFAULT_BOOTSTRAP_PATH = _REPO_ROOT / "nomarr" / "components" / "platform" / "arango_bootstrap_comp.py"
_OLD_SINGLE_FILE = _REPO_ROOT / "scripts" / "consolidate_migrations.py"


def _check_shadow_file() -> None:
    """Warn if the old single-file script still exists and may shadow this package."""
    if _OLD_SINGLE_FILE.exists():
        print(
            "WARNING: Found old single-file script at "
            f"'{_OLD_SINGLE_FILE}' — this may shadow the package when running "
            "'python -m scripts.consolidate_migrations' on some Python versions. "
            "Delete it once you have migrated to the package-based tool.",
            file=sys.stderr,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.consolidate_migrations",
        description=(
            "Compare Shape A (ensure_schema) against Shape B (replayed migrations). "
            "Optionally consolidate the migration history into a single V001 baseline."
        ),
    )
    parser.add_argument(
        "--consolidate",
        action="store_true",
        default=False,
        help=(
            "After successful validation, delete old migration files (V004-V019) "
            "and write V001_baseline.py. Hard-fails if shapes do not match."
        ),
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=_DEFAULT_MIGRATIONS_DIR,
        metavar="PATH",
        help=f"Path to nomarr/migrations/ directory. Default: {_DEFAULT_MIGRATIONS_DIR}",
    )
    parser.add_argument(
        "--bootstrap-path",
        type=Path,
        default=_DEFAULT_BOOTSTRAP_PATH,
        metavar="PATH",
        help=(f"Path to arango_bootstrap_comp.py (ensure_schema source). Default: {_DEFAULT_BOOTSTRAP_PATH}"),
    )
    # DB connection args removed — PostgreSQL migration complete.
    return parser


def _run_validate(migrations_dir: Path, bootstrap_path: Path) -> tuple[object, object, object]:
    """Parse, replay, compare, and print the diff report.

    Returns (shape_a, shape_b, diff).  Exits with code 2 on runtime errors.
    """
    # Lazy imports so the module itself is lightweight
    from scripts.consolidate_migrations.ensure_schema_parser import parse_ensure_schema
    from scripts.consolidate_migrations.migration_replayer import replay_migrations
    from scripts.consolidate_migrations.schema_comparator import compare_shapes, format_diff_report

    # -- Shape A: parse ensure_schema -------------------------------------------
    print(f"Parsing Shape A from: {bootstrap_path}", flush=True)
    try:
        shape_a = parse_ensure_schema(bootstrap_path)
    except FileNotFoundError:
        print(f"ERROR: bootstrap path not found: {bootstrap_path}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"ERROR parsing ensure_schema: {exc}", file=sys.stderr)
        sys.exit(2)

    print(
        f"  Shape A: {len(shape_a.collections)} collections, "
        f"{len(shape_a.indexes)} indexes, "
        f"{len(shape_a.graphs)} graphs, "
        f"{len(shape_a.seed_documents)} seed documents",
        flush=True,
    )

    # -- Shape B: replay migrations ---------------------------------------------
    print(f"\nReplaying migrations from: {migrations_dir}", flush=True)
    try:
        shape_b, warnings = replay_migrations(shape_a, migrations_dir)
    except FileNotFoundError:
        print(f"ERROR: migrations directory not found: {migrations_dir}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"ERROR replaying migrations: {exc}", file=sys.stderr)
        sys.exit(2)

    if warnings:
        print(f"\nReplay warnings ({len(warnings)}):", flush=True)
        for w in warnings:
            print(f"  [WARN] {w}", flush=True)

    print(
        f"\n  Shape B: {len(shape_b.collections)} collections, "
        f"{len(shape_b.indexes)} indexes, "
        f"{len(shape_b.graphs)} graphs, "
        f"{len(shape_b.seed_documents)} seed documents",
        flush=True,
    )

    # -- Compare ----------------------------------------------------------------
    diff = compare_shapes(shape_a, shape_b)
    report = format_diff_report(diff)

    print("\n" + "=" * 60, flush=True)
    print("DIFF REPORT", flush=True)
    print("=" * 60, flush=True)
    print(report, flush=True)
    print("=" * 60, flush=True)

    return shape_a, shape_b, diff


def _merge_shapes(shape_a: object, shape_b: object) -> object:
    """Merge two SchemaShapes, taking the union of collections, indexes, and seeds.

    Used when Shape B (replayed migrations) has items that were never folded
    into the ensure_schema baseline (Shape A). The merged shape represents
    the true final schema state.
    """
    from scripts.consolidate_migrations.schema_model import SchemaShape

    a: SchemaShape = shape_a  # type: ignore[assignment]
    b: SchemaShape = shape_b  # type: ignore[assignment]

    return SchemaShape(
        collections=a.collections | b.collections,
        indexes=a.indexes | b.indexes,
        graphs=a.graphs | b.graphs,
        seed_documents=a.seed_documents | b.seed_documents,
    )


def _run_consolidate(migrations_dir: Path, shape_a: object, shape_b: object, diff: object) -> None:
    """Delete old migrations and write V001_baseline.py.

    When shapes differ, the merged shape (union of A ∪ B) is used as the
    baseline to ensure all schema objects from both the ensure_schema
    baseline AND the migration chain are captured.
    """
    from scripts.consolidate_migrations.consolidator import (
        delete_old_migrations,
        generate_reset_aql,
        write_baseline,
    )

    if not diff.is_match:  # type: ignore[union-attr]
        print("\nShapes differ — merging Shape A ∪ Shape B for baseline generation.", flush=True)
        baseline_shape = _merge_shapes(shape_a, shape_b)
    else:
        baseline_shape = shape_a

    # Delete old migrations
    print("\nDeleting old migration files...", flush=True)
    try:
        deleted = delete_old_migrations(migrations_dir, dry_run=False)
    except Exception as exc:
        print(f"ERROR deleting old migrations: {exc}", file=sys.stderr)
        sys.exit(2)

    for p in deleted:
        print(f"  Deleted: {p}", flush=True)

    # Write V001_baseline.py
    print("\nWriting V001_baseline.py...", flush=True)
    try:
        baseline_path = write_baseline(migrations_dir, baseline_shape)  # type: ignore[arg-type]
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"ERROR writing baseline: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"  Written: {baseline_path}", flush=True)

    # Print the reset AQL
    reset_aql = generate_reset_aql()
    print("\n" + "=" * 60, flush=True)
    print("RESET AQL (execute in ArangoDB to reset migration state):", flush=True)
    print("=" * 60, flush=True)
    print(reset_aql, flush=True)
    print("=" * 60, flush=True)


def main() -> None:
    """Main CLI entry point."""
    _check_shadow_file()

    parser = _build_parser()
    args = parser.parse_args()

    migrations_dir: Path = args.migrations_dir
    bootstrap_path: Path = args.bootstrap_path

    # ---- Validate (always runs) -----------------------------------------------
    shape_a, shape_b, diff = _run_validate(migrations_dir, bootstrap_path)

    if not diff.is_match:  # type: ignore[union-attr]
        print("\nResult: SHAPES DO NOT MATCH — baseline is stale.", flush=True)
    else:
        print("\nResult: SHAPES MATCH", flush=True)

    # ---- Consolidate (optional) ------------------------------------------------
    if args.consolidate:
        _run_consolidate(migrations_dir, shape_a, shape_b, diff)

    sys.exit(0)


if __name__ == "__main__":
    main()
