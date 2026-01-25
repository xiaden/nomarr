#!/usr/bin/env python3
"""Index recommendation utility for Nomarr ArangoDB schema.

Analyzes AQL query patterns in persistence layer and compares with
indexes defined in arango_bootstrap_comp.py.

Reports:
  - Defined indexes (from bootstrap)
  - Recommended indexes (based on query analysis)
  - Missing indexes (recommended but not defined)
  - Unused indexes (defined but no matching queries)

Usage:
    python scripts/check_indexes.py [--verbose]
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PERSISTENCE_DIR = REPO_ROOT / "nomarr" / "persistence" / "database"
BOOTSTRAP_FILE = REPO_ROOT / "nomarr" / "components" / "platform" / "arango_bootstrap_comp.py"

# Legacy collections that no longer exist (TAG_UNIFICATION_REFACTOR)
LEGACY_COLLECTIONS = frozenset(
    {
        "file_tags",
        "library_tags",
        "artists",
        "albums",
        "genres",
        "labels",
        "years",
        "calibration_queue",
        "calibration_runs",
    }
)

# Valid collections in current schema
VALID_COLLECTIONS = frozenset(
    {
        "meta",
        "libraries",
        "library_files",
        "library_folders",
        "tags",
        "song_tag_edges",
        "sessions",
        "calibration_state",
        "calibration_history",
        "health",
        "worker_claims",
        "worker_restart_policy",
        "ml_capacity_estimates",
        "ml_capacity_probe_locks",
    }
)


@dataclass
class IndexSpec:
    """Represents an index specification."""

    collection: str
    fields: tuple[str, ...]
    index_type: str = "persistent"
    unique: bool = False
    sparse: bool = False
    source: str = ""  # File where defined/detected

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        """Key for deduplication: (collection, fields)."""
        return (self.collection, self.fields)

    def __hash__(self) -> int:
        return hash((self.collection, self.fields, self.unique))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IndexSpec):
            return False
        return self.collection == other.collection and self.fields == other.fields


@dataclass
class QueryPattern:
    """Detected query pattern from AQL."""

    collection: str
    filter_fields: list[str]
    is_equality: bool  # True for ==, False for range (<, >, <=, >=)
    source_file: str
    line_number: int
    query_snippet: str = ""


@dataclass
class IndexReport:
    """Full index analysis report."""

    defined: list[IndexSpec] = field(default_factory=list)
    recommended: list[IndexSpec] = field(default_factory=list)
    missing: list[IndexSpec] = field(default_factory=list)
    unused: list[IndexSpec] = field(default_factory=list)
    queries: list[QueryPattern] = field(default_factory=list)


def parse_bootstrap_indexes() -> list[IndexSpec]:
    """Parse index definitions from arango_bootstrap_comp.py."""
    indexes: list[IndexSpec] = []

    content = BOOTSTRAP_FILE.read_text(encoding="utf-8")

    # Pattern: _ensure_index(db, "collection", "type", ["field1", "field2"], unique=..., sparse=...)
    pattern = re.compile(
        r"_ensure_index\s*\(\s*"
        r"db\s*,\s*"
        r'"([^"]+)"\s*,\s*'  # collection
        r'"([^"]+)"\s*,\s*'  # index_type
        r"\[([^\]]+)\]"  # fields
        r"(?:[^)]*unique\s*=\s*(True|False))?"  # optional unique
        r"(?:[^)]*sparse\s*=\s*(True|False))?",  # optional sparse
        re.MULTILINE | re.DOTALL,
    )

    for match in pattern.finditer(content):
        collection = match.group(1)
        index_type = match.group(2)
        fields_raw = match.group(3)
        unique = match.group(4) == "True" if match.group(4) else False
        sparse = match.group(5) == "True" if match.group(5) else False

        # Parse fields list
        fields = tuple(f.strip().strip('"').strip("'") for f in fields_raw.split(","))

        indexes.append(
            IndexSpec(
                collection=collection,
                fields=fields,
                index_type=index_type,
                unique=unique,
                sparse=sparse,
                source=str(BOOTSTRAP_FILE.relative_to(REPO_ROOT)),
            )
        )

    return indexes


def extract_aql_queries(file_path: Path) -> list[tuple[str, int]]:
    """Extract AQL query strings from a Python file.

    Returns list of (query_string, line_number).
    """
    content = file_path.read_text(encoding="utf-8")
    queries: list[tuple[str, int]] = []

    # Find triple-quoted strings that look like AQL
    pattern = re.compile(r'"""(.*?)"""', re.DOTALL)

    for match in pattern.finditer(content):
        query = match.group(1)
        # Check if it looks like AQL (has FOR, FILTER, RETURN, etc.)
        if any(kw in query.upper() for kw in ["FOR ", "FILTER ", "RETURN ", "INSERT ", "UPDATE ", "UPSERT "]):
            # Calculate line number
            line_num = content[: match.start()].count("\n") + 1
            queries.append((query, line_num))

    return queries


def analyze_query_patterns(query: str, source_file: str, line_num: int) -> list[QueryPattern]:
    """Analyze an AQL query for filter patterns that could benefit from indexes."""
    patterns: list[QueryPattern] = []

    # Detect collection from FOR x IN collection
    for_pattern = re.compile(r"FOR\s+(\w+)\s+IN\s+(\w+)", re.IGNORECASE)
    collections: dict[str, str] = {}  # alias -> collection

    for match in for_pattern.finditer(query):
        alias = match.group(1)
        collection = match.group(2)
        # Skip if it's a variable (like @values)
        if not collection.startswith("@"):
            collections[alias] = collection

    # Detect FILTER conditions: alias.field == @param or alias.field == value
    filter_pattern = re.compile(
        r"FILTER\s+(?:.*?\s+AND\s+)*?"  # Optional preceding ANDs
        r"(\w+)\.(\w+)\s*(==|!=|<|>|<=|>=)\s*(@?\w+|\"[^\"]*\"|'[^']*'|\d+)",
        re.IGNORECASE,
    )

    for match in filter_pattern.finditer(query):
        alias = match.group(1)
        field_name = match.group(2)
        operator = match.group(3)

        if alias in collections:
            collection = collections[alias]
            is_equality = operator == "=="

            patterns.append(
                QueryPattern(
                    collection=collection,
                    filter_fields=[field_name],
                    is_equality=is_equality,
                    source_file=source_file,
                    line_number=line_num,
                    query_snippet=match.group(0)[:80],
                )
            )

    # Detect compound filters: FILTER a.x == @y AND a.z == @w
    compound_pattern = re.compile(
        r"FILTER\s+(\w+)\.(\w+)\s*==\s*@?\w+\s+AND\s+\1\.(\w+)\s*==\s*@?\w+",
        re.IGNORECASE,
    )

    for match in compound_pattern.finditer(query):
        alias = match.group(1)
        field1 = match.group(2)
        field2 = match.group(3)

        if alias in collections:
            collection = collections[alias]
            patterns.append(
                QueryPattern(
                    collection=collection,
                    filter_fields=[field1, field2],
                    is_equality=True,
                    source_file=source_file,
                    line_number=line_num,
                    query_snippet=match.group(0)[:80],
                )
            )

    return patterns


def recommend_indexes(queries: list[QueryPattern]) -> list[IndexSpec]:
    """Generate index recommendations from query patterns."""
    # Group by (collection, fields tuple)
    field_usage: dict[tuple[str, tuple[str, ...]], list[QueryPattern]] = {}

    for q in queries:
        # Skip legacy collections
        if q.collection in LEGACY_COLLECTIONS:
            continue
        # Skip collections not in valid schema
        if q.collection not in VALID_COLLECTIONS:
            continue

        key = (q.collection, tuple(sorted(q.filter_fields)))
        if key not in field_usage:
            field_usage[key] = []
        field_usage[key].append(q)

    recommendations: list[IndexSpec] = []

    for (collection, fields), usages in field_usage.items():
        # Skip system fields that are already indexed by default
        if fields == ("_id",) or fields == ("_key",):
            continue

        # For edge collections, _from and _to are common
        sources = {u.source_file for u in usages}

        recommendations.append(
            IndexSpec(
                collection=collection,
                fields=fields,
                index_type="persistent",
                unique=False,
                sparse=False,
                source=", ".join(sorted(sources)),
            )
        )

    return recommendations


def compare_indexes(defined: list[IndexSpec], recommended: list[IndexSpec]) -> tuple[list[IndexSpec], list[IndexSpec]]:
    """Compare defined vs recommended indexes.

    Returns (missing, unused).
    """
    defined_keys = {i.key for i in defined}
    recommended_keys = {i.key for i in recommended}

    # Missing: recommended but not defined
    missing = [i for i in recommended if i.key not in defined_keys]

    # Unused: defined but not in recommendations (may still be valid for unique constraints)
    unused = [i for i in defined if i.key not in recommended_keys]

    return missing, unused


def analyze_persistence_layer() -> IndexReport:
    """Full analysis of persistence layer queries vs defined indexes."""
    report = IndexReport()

    # 1. Parse defined indexes
    report.defined = parse_bootstrap_indexes()

    # 2. Scan persistence layer for query patterns
    all_queries: list[QueryPattern] = []

    for py_file in PERSISTENCE_DIR.glob("*_aql.py"):
        rel_path = str(py_file.relative_to(REPO_ROOT))
        queries = extract_aql_queries(py_file)

        for query_str, line_num in queries:
            patterns = analyze_query_patterns(query_str, rel_path, line_num)
            all_queries.extend(patterns)

    report.queries = all_queries

    # 3. Generate recommendations
    report.recommended = recommend_indexes(all_queries)

    # 4. Compare
    report.missing, report.unused = compare_indexes(report.defined, report.recommended)

    return report


def format_index(idx: IndexSpec, verbose: bool = False) -> str:
    """Format an index for display."""
    flags = []
    if idx.unique:
        flags.append("UNIQUE")
    if idx.sparse:
        flags.append("SPARSE")
    flag_str = f" [{', '.join(flags)}]" if flags else ""

    base = f"{idx.collection}({', '.join(idx.fields)}){flag_str}"
    if verbose and idx.source:
        base += f" <- {idx.source}"
    return base


def print_report(report: IndexReport, verbose: bool = False) -> None:
    """Print formatted index report."""
    print("\n" + "=" * 70)
    print("NOMARR INDEX ANALYSIS REPORT")
    print("=" * 70)

    # Defined indexes
    print(f"\n📋 DEFINED INDEXES ({len(report.defined)})")
    print("-" * 50)
    for idx in sorted(report.defined, key=lambda x: (x.collection, x.fields)):
        print(f"  ✓ {format_index(idx, verbose)}")

    # Recommended indexes (from query analysis)
    if verbose:
        print(f"\n🔍 QUERY-DERIVED RECOMMENDATIONS ({len(report.recommended)})")
        print("-" * 50)
        for idx in sorted(report.recommended, key=lambda x: (x.collection, x.fields)):
            print(f"  • {format_index(idx, verbose)}")

    # Missing indexes
    print(f"\n⚠️  POTENTIALLY MISSING INDEXES ({len(report.missing)})")
    print("-" * 50)
    if report.missing:
        for idx in sorted(report.missing, key=lambda x: (x.collection, x.fields)):
            print(f"  ✗ {format_index(idx, verbose)}")
    else:
        print("  (none - all recommended indexes are defined)")

    # Unused indexes (defined but no matching queries)
    print(f"\n📦 DEFINED BUT NO MATCHING QUERIES ({len(report.unused)})")
    print("-" * 50)
    if report.unused:
        for idx in sorted(report.unused, key=lambda x: (x.collection, x.fields)):
            note = ""
            if idx.unique:
                note = " (likely needed for constraint)"
            print(f"  ? {format_index(idx, verbose)}{note}")
        print("\n  Note: These may still be valid for unique constraints or")
        print("  queries not detected by static analysis.")
    else:
        print("  (all defined indexes have matching queries)")

    # Query patterns summary
    if verbose:
        print(f"\n📊 QUERY PATTERNS DETECTED ({len(report.queries)})")
        print("-" * 50)
        by_collection: dict[str, list[QueryPattern]] = {}
        for q in report.queries:
            if q.collection not in by_collection:
                by_collection[q.collection] = []
            by_collection[q.collection].append(q)

        for coll in sorted(by_collection.keys()):
            patterns = by_collection[coll]
            print(f"\n  {coll}:")
            for q in patterns[:5]:  # Limit display
                fields_str = ", ".join(q.filter_fields)
                print(f"    - {fields_str} ({q.source_file}:{q.line_number})")
            if len(patterns) > 5:
                print(f"    ... and {len(patterns) - 5} more")

    print("\n" + "=" * 70)

    # Summary
    total_issues = len(report.missing)
    if total_issues == 0:
        print("✅ Index coverage looks complete!")
    else:
        print(f"⚠️  {total_issues} potential index gap(s) detected.")
        print("   Review missing indexes and add to arango_bootstrap_comp.py if needed.")

    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze ArangoDB index coverage")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    report = analyze_persistence_layer()
    print_report(report, verbose=args.verbose)


if __name__ == "__main__":
    main()
