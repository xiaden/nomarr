#!/usr/bin/env python3
# noqa: N999 — script uses hyphens in filename (not an importable module)
"""
Check for transitive import violations in the nomarr codebase.

Uses grimp to build an import graph and detect both direct and transitive
imports that violate the persistence boundary:
  - nomarr.components → nomarr.persistence.database
  - nomarr.workflows → nomarr.persistence.database
  - nomarr.services → nomarr.persistence.database

Exit codes:
  0 - No violations found
  1 - Violations detected
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

# Ensure the project root is on the Python path so grimp can find
# the 'nomarr' package regardless of working directory.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import grimp  # noqa: E402 — must be after sys.path setup so grimp can find nomarr

# Forbidden import pairs: (importer, imported)
FORBIDDEN_PAIRS = [
    ("nomarr.components", "nomarr.persistence.database"),
    ("nomarr.workflows", "nomarr.persistence.database"),
    ("nomarr.services", "nomarr.persistence.database"),
]

# Authorized intermediaries — chains passing through these modules are allowed
# because they travel through the Database facade (ADR-031) or its sub-facades.
AUTHORIZED_INTERMEDIARIES = [
    "nomarr.persistence.db",
    "nomarr.persistence.api",
]

CACHE_DIR = Path(".cache")
GRAPH_CACHE_DIR = CACHE_DIR / "grimp-graph"
HASH_FILE = CACHE_DIR / "grimp-graph-hash.txt"


def compute_nomarr_hash() -> str:
    """Compute a hash of all .py files under nomarr/ for cache invalidation.

    Uses file paths and modification times to detect changes.
    """
    nomarr_dir = Path("nomarr")
    if not nomarr_dir.exists():
        return ""

    # Collect all .py file paths and mtimes, sorted for determinism
    py_files = sorted(nomarr_dir.rglob("*.py"))
    hash_input = []
    for py_file in py_files:
        try:
            mtime = py_file.stat().st_mtime
            hash_input.append(f"{py_file}:{mtime}")
        except OSError:
            # File may have been deleted between rglob and stat
            continue

    # Hash the combined string
    combined = "\n".join(hash_input)
    return hashlib.sha256(combined.encode()).hexdigest()


def load_cached_hash() -> str:
    """Load the cached hash from disk, or return empty string if not found."""
    if not HASH_FILE.exists():
        return ""
    try:
        return HASH_FILE.read_text().strip()
    except OSError:
        return ""


def save_hash(hash_value: str) -> None:
    """Save the hash to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(hash_value + "\n")


def build_graph(use_cache: bool = True) -> grimp.ImportGraph:
    """Build the grimp import graph for the nomarr package.

    Uses grimp's built-in cache_dir for efficient serialization.
    Cache is stored in .cache/grimp-graph/.
    """
    cache_dir = str(GRAPH_CACHE_DIR) if use_cache else None

    print("Building import graph with grimp...", file=sys.stderr)
    graph = grimp.build_graph("nomarr", cache_dir=cache_dir)
    print("Graph built successfully.", file=sys.stderr)
    return graph


def invalidate_cache() -> None:
    """Remove the cached graph and hash file."""
    if GRAPH_CACHE_DIR.exists():
        shutil.rmtree(GRAPH_CACHE_DIR)
    if HASH_FILE.exists():
        HASH_FILE.unlink()


def _chain_is_authorized(chain: tuple[str, ...]) -> bool:
    """Return True if the chain passes through an authorized intermediary.

    Only the intermediate modules (between the importer and the imported)
    are checked — not the endpoints themselves.
    """
    intermediates = chain[1:-1]
    return any(
        any(im == auth or im.startswith(auth + ".") for auth in AUTHORIZED_INTERMEDIARIES) for im in intermediates
    )


def check_violations(graph: grimp.ImportGraph, verbose: bool = False) -> list[tuple[str, str, list[str]]]:
    """Check for forbidden import chains.

    Returns a list of tuples: (importer, imported, chain)
    where chain is a list of module names in the import path.

    Chains that pass through an authorized intermediary (e.g., the Database
    facade per ADR-031) are excluded — they are by-design, not violations.
    """
    violations = []
    excluded_count = 0

    for importer, imported in FORBIDDEN_PAIRS:
        chains = graph.find_shortest_chains(importer, imported, as_packages=True)

        for chain in sorted(chains):
            if _chain_is_authorized(chain):
                excluded_count += 1
                continue
            violations.append((importer, imported, list(chain)))

            if verbose:
                print(f"\nViolation: {importer} → {imported}", file=sys.stderr)
                print(f"  Chain: {' → '.join(chain)}", file=sys.stderr)
                # Print details for each step in the chain
                for i in range(len(chain) - 1):
                    src = chain[i]
                    dst = chain[i + 1]
                    details = graph.get_import_details(importer=src, imported=dst)
                    for detail in details:
                        line_num = detail.get("line_number", "?")
                        line_content = detail.get("line_contents", "").strip()
                        print(f"    {src}:{line_num} → {dst}", file=sys.stderr)
                        if line_content:
                            print(f"      {line_content}", file=sys.stderr)

    if verbose and excluded_count > 0:
        print(
            f"\nℹ Excluded {excluded_count} chain(s) passing through authorized "
            "intermediaries (Database facade per ADR-031).",
            file=sys.stderr,
        )

    return violations


def format_violations(violations: list[tuple[str, str, list[str]]]) -> str:
    """Format violations as human-readable output."""
    if not violations:
        return "No transitive import violations found."

    lines = [f"Found {len(violations)} transitive import violation(s):\n"]

    for i, (_importer, _imported, chain) in enumerate(violations, 1):
        chain_str = " → ".join(chain)
        lines.append(f"{i}. {chain_str}")

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Check for transitive import violations in nomarr")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force graph rebuild, ignoring cache",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full import details for each violation chain",
    )
    args = parser.parse_args()

    # Check cache validity
    current_hash = compute_nomarr_hash()
    cached_hash = load_cached_hash()
    cache_valid = (
        (not args.no_cache) and (current_hash == cached_hash) and current_hash != "" and GRAPH_CACHE_DIR.exists()
    )

    if args.no_cache:
        print("--no-cache specified, rebuilding graph...", file=sys.stderr)
        invalidate_cache()
        graph = build_graph(use_cache=False)
        # Still save the hash for future runs
        save_hash(current_hash)
    elif not cache_valid:
        if current_hash != cached_hash and cached_hash:
            print(
                "Cache invalidated (nomarr/ files changed), rebuilding...",
                file=sys.stderr,
            )
            invalidate_cache()
        graph = build_graph(use_cache=True)
        save_hash(current_hash)
    else:
        print("Cache is valid, loading from cache...", file=sys.stderr)
        graph = build_graph(use_cache=True)

    # Check for violations
    violations = check_violations(graph, verbose=args.verbose)

    # Output results
    output = format_violations(violations)
    print(output)

    # Exit with appropriate code
    if violations:
        print(f"\n❌ {len(violations)} violation(s) detected", file=sys.stderr)
        return 1
    print("\n✅ No violations found", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
