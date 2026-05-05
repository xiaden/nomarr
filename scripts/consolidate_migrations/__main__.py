"""CLI entry point for the migration consolidation tool.

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
    After consolidation, connects to ArangoDB and executes the reset AQL
    to clear applied_migrations and reset schema_version to "0".
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
        "--execute-db-reset",
        action="store_true",
        default=False,
        help=(
            "After consolidation, connect to ArangoDB and execute the reset AQL "
            "(clears applied_migrations, resets schema_version to '0'). "
            "Implies --consolidate. Requires python-arango."
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
    # DB connection args (only used with --execute-db-reset)
    parser.add_argument(
        "--db-host",
        default="http://127.0.0.1:8529",
        metavar="URL",
        help="ArangoDB host URL. Default: http://127.0.0.1:8529",
    )
    parser.add_argument(
        "--db-name",
        default="nomarr",
        metavar="NAME",
        help="ArangoDB database name. Default: nomarr",
    )
    parser.add_argument(
        "--db-user",
        default="root",
        metavar="USER",
        help="ArangoDB username. Default: root",
    )
    parser.add_argument(
        "--db-password",
        default="",
        metavar="PASSWORD",
        help="ArangoDB password. Default: (empty)",
    )
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


def _run_consolidate(migrations_dir: Path, shape_a: object) -> None:
    """Delete old migrations and write V001_baseline.py.

    Exits with code 2 on errors.
    """
    from scripts.consolidate_migrations.consolidator import (
        delete_old_migrations,
        generate_reset_aql,
        write_baseline,
    )

    # Delete old migrations (V004-V019)
    print("\nDeleting old migration files (dry_run=False)...", flush=True)
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
        baseline_path = write_baseline(migrations_dir, shape_a)  # type: ignore[arg-type]
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


def _run_db_reset(
    db_host: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> None:
    """Connect to ArangoDB and execute the reset AQL statements.

    Exits with code 2 on errors (including missing python-arango).
    """
    try:
        from arango import ArangoClient  # type: ignore[import-untyped]
    except ImportError:
        print(
            "ERROR: python-arango is not installed. Run: pip install python-arango",
            file=sys.stderr,
        )
        sys.exit(2)

    from scripts.consolidate_migrations.consolidator import generate_reset_aql

    reset_aql = generate_reset_aql()
    # Split the two AQL statements (separated by blank line)
    statements = [s.strip() for s in reset_aql.strip().split("\n\n") if s.strip()]

    print(f"\nConnecting to ArangoDB at {db_host} (db={db_name})...", flush=True)
    try:
        client = ArangoClient(hosts=db_host)
        db = client.db(db_name, username=db_user, password=db_password)
        for stmt in statements:
            print(f"  Executing: {stmt[:80]}...", flush=True)
            db.aql.execute(stmt)
        print("  DB reset complete.", flush=True)
    except Exception as exc:
        print(f"ERROR executing reset AQL: {exc}", file=sys.stderr)
        sys.exit(2)


def main() -> None:
    """Main CLI entry point."""
    _check_shadow_file()

    parser = _build_parser()
    args = parser.parse_args()

    # --execute-db-reset implies --consolidate
    if args.execute_db_reset:
        args.consolidate = True

    migrations_dir: Path = args.migrations_dir
    bootstrap_path: Path = args.bootstrap_path

    # ---- Validate (always runs) -----------------------------------------------
    shape_a, _shape_b, diff = _run_validate(migrations_dir, bootstrap_path)

    if not diff.is_match:  # type: ignore[union-attr]
        print("\nResult: SHAPES DO NOT MATCH", flush=True)
        if args.consolidate:
            print(
                "ERROR: --consolidate requires shapes to match. Fix replay mismatches before consolidating.",
                file=sys.stderr,
            )
        sys.exit(1)

    print("\nResult: SHAPES MATCH", flush=True)

    # ---- Consolidate (optional) ------------------------------------------------
    if args.consolidate:
        _run_consolidate(migrations_dir, shape_a)

    # ---- DB reset (optional) ---------------------------------------------------
    if args.execute_db_reset:
        _run_db_reset(args.db_host, args.db_name, args.db_user, args.db_password)

    sys.exit(0)


if __name__ == "__main__":
    main()
