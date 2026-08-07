"""Sabotage tests: no ArangoDB naming conventions in non-persistence code (AR-3).

Shipped state (per CONTRACTS.md AR-3):
- Field names use ``id``, ``key``, ``rev`` — not ``_id``, ``_key``, ``_rev``.
- No collection-prefixed filenames in persistence.
- No AQL primitives in non-persistence code.

The tests scan source code at test time and report violations. The scan
scope is clean — all previously identified field-reference violations were
resolved in Part B, and the suite is GREEN.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Non-persistence directories to scan for ArangoDB naming violations
NON_PERSISTENCE_DIRS = [
    Path("nomarr/components"),
    Path("nomarr/services"),
    Path("nomarr/workflows"),
    Path("nomarr/interfaces"),
    Path("nomarr/helpers"),
]

# Persistence database directory to check for collection-prefixed filenames
PERSISTENCE_DATABASE_DIR = Path("nomarr/persistence/database")

# ArangoDB field patterns (string literals like "_id", "_key", "_rev")
# These match dict access patterns: doc["_id"], doc.get("_key"), etc.
ARANGO_ID_PATTERN = re.compile(r"""["_']_id["']""")
ARANGO_KEY_PATTERN = re.compile(r"""["_']_key["']""")
ARANGO_REV_PATTERN = re.compile(r"""["_']_rev["']""")

# AQL primitive patterns
AQL_PATTERNS = [
    re.compile(r"\bFOR\s+\w+\s+IN\b"),
    re.compile(r"\bFILTER\s+\w+\."),
    re.compile(r"\bRETURN\s+\w+\."),
    re.compile(r"\bUPSERT\b"),
    re.compile(r"\bLET\s+\w+\s*="),
    re.compile(r"\bINBOUND\b"),
    re.compile(r"\bOUTBOUND\b"),
]

# Collection-prefixed filename patterns (ArangoDB convention)
COLLECTION_PREFIX_PATTERN = re.compile(r"^(aql_|collection_|edge_|graph_)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan_files_for_pattern(
    directories: list[Path],
    pattern: re.Pattern[str],
    *,
    exclude_comments: bool = False,
) -> list[tuple[str, int, str]]:
    """Scan Python files in directories for a regex pattern.

    Args:
        directories: Directories to scan (relative to project root).
        pattern: Compiled regex pattern to match.
        exclude_comments: If True, skip lines that are pure comments.

    Returns:
        List of (filepath, line_number, line_text) tuples for matches.
    """
    violations: list[tuple[str, int, str]] = []
    project_root = Path(__file__).parent.parent.parent

    for directory in directories:
        dir_path = project_root / directory
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_num, line in enumerate(content.splitlines(), start=1):
                # Skip pure comment lines if requested
                if exclude_comments and line.lstrip().startswith("#"):
                    continue
                if pattern.search(line):
                    violations.append((str(py_file.relative_to(project_root)), line_num, line.strip()))

    return violations


def _format_violations(violations: list[tuple[str, int, str]], limit: int = 20) -> str:
    """Format violations into a human-readable report."""
    if not violations:
        return "No violations found."
    lines = [f"Found {len(violations)} violation(s):"]
    for filepath, line_num, line_text in violations[:limit]:
        lines.append(f"  {filepath}:{line_num}: {line_text}")
    if len(violations) > limit:
        lines.append(f"  ... and {len(violations) - limit} more")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Test 1: No _id field references in non-persistence code
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoArangoIdFields:
    """Shipped state: no ``_id`` field references in non-persistence code.

    Per AR-3, field names use ``id``, not ``_id``. The scan scope is clean —
    no ``_id`` string literals remain in components, services, workflows,
    interfaces, or helpers.
    """

    def test_no_id_field_references_in_non_persistence(self):
        """Non-persistence code has no ``_id`` field references.

        Scans components/, services/, workflows/, interfaces/, helpers/
        for string literals like ``"_id"`` or ``'_id'``. Any match is an
        AR-3 violation and fails the test.
        """
        violations = _scan_files_for_pattern(NON_PERSISTENCE_DIRS, ARANGO_ID_PATTERN)
        report = _format_violations(violations)
        assert len(violations) == 0, (
            f"AR-3 violation: _id field references found in non-persistence code.\n"
            f"Field names should use 'id', not '_id'.\n{report}"
        )


# ---------------------------------------------------------------------------
# Test 2: No _key field references in non-persistence code
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoArangoKeyFields:
    """Shipped state: no ``_key`` field references in non-persistence code.

    Per AR-3, field names use ``key``, not ``_key``. The scan scope is clean —
    no ``_key`` string literals remain in components, services, workflows,
    interfaces, or helpers.
    """

    def test_no_key_field_references_in_non_persistence(self):
        """Non-persistence code has no ``_key`` field references.

        Scans components/, services/, workflows/, interfaces/, helpers/
        for string literals like ``"_key"`` or ``'_key'``. Any match is an
        AR-3 violation and fails the test.
        """
        violations = _scan_files_for_pattern(NON_PERSISTENCE_DIRS, ARANGO_KEY_PATTERN)
        report = _format_violations(violations)
        assert len(violations) == 0, (
            f"AR-3 violation: _key field references found in non-persistence code.\n"
            f"Field names should use 'key', not '_key'.\n{report}"
        )


# ---------------------------------------------------------------------------
# Test 3: No _rev field references in non-persistence code
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoArangoRevFields:
    """Shipped state: no ``_rev`` field references in non-persistence code.

    Per AR-3, field names use ``rev``, not ``_rev``. The scan scope is clean —
    no ``_rev`` string literals remain in components, services, workflows,
    interfaces, or helpers.
    """

    def test_no_rev_field_references_in_non_persistence(self):
        """Non-persistence code has no ``_rev`` field references.

        Scans components/, services/, workflows/, interfaces/, helpers/
        for string literals like ``"_rev"`` or ``'_rev'``. Any match is an
        AR-3 violation and fails the test.
        """
        violations = _scan_files_for_pattern(NON_PERSISTENCE_DIRS, ARANGO_REV_PATTERN)
        report = _format_violations(violations)
        assert len(violations) == 0, (
            f"AR-3 violation: _rev field references found in non-persistence code.\n"
            f"Field names should use 'rev', not '_rev'.\n{report}"
        )


# ---------------------------------------------------------------------------
# Test 4: No collection-prefixed filenames in persistence
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoCollectionPrefixedFilenames:
    """Check that persistence filenames don't use ArangoDB collection-prefix convention.

    Per AR-3, no filenames like ``aql_*``, ``collection_*``, ``edge_*``,
    ``graph_*`` in nomarr/persistence/database/. Files use the ``*_repo.py``
    convention (PostgreSQL-era); the test passes with no violations.
    """

    def test_no_collection_prefixed_filenames_in_persistence(self):
        """Persistence filenames don't use ArangoDB collection-prefix convention.

        Checks nomarr/persistence/database/ for filenames starting with
        aql_, collection_, edge_, or graph_ (ArangoDB conventions).
        """
        project_root = Path(__file__).parent.parent.parent
        db_dir = project_root / PERSISTENCE_DATABASE_DIR

        if not db_dir.exists():
            pytest.skip(f"Directory {PERSISTENCE_DATABASE_DIR} does not exist")

        violations: list[str] = []
        for py_file in db_dir.rglob("*.py"):
            filename = py_file.name
            if COLLECTION_PREFIX_PATTERN.match(filename):
                violations.append(str(py_file.relative_to(project_root)))

        assert len(violations) == 0, (
            f"AR-3 violation: Collection-prefixed filenames found in persistence.\n"
            f"Filenames should not use ArangoDB conventions (aql_*, collection_*, edge_*, graph_*).\n"
            f"Violations: {violations}"
        )


# ---------------------------------------------------------------------------
# Test 5: No AQL primitives in non-persistence code
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoAqlPrimitives:
    """Shipped state: no AQL primitives in non-persistence code.

    Per AR-3, AQL query syntax must not appear outside persistence:
    ``FOR doc IN``, ``FILTER doc.``, ``RETURN doc.``, ``UPSERT``,
    ``LET doc =``, ``INBOUND``, ``OUTBOUND``. The test fails if any are
    found (excluding pure comment lines).
    """

    def test_no_aql_primitives_in_non_persistence(self):
        """Non-persistence code has no AQL primitive syntax.

        Scans components/, services/, workflows/, interfaces/, helpers/
        for AQL query patterns (FOR...IN, FILTER, RETURN, UPSERT, etc.).
        Excludes pure comment lines; any match fails the test.
        """
        all_violations: list[tuple[str, int, str]] = []

        for pattern in AQL_PATTERNS:
            violations = _scan_files_for_pattern(
                NON_PERSISTENCE_DIRS,
                pattern,
                exclude_comments=True,
            )
            all_violations.extend(violations)

        # Deduplicate (same line may match multiple patterns)
        unique_violations = list(set(all_violations))
        unique_violations.sort(key=lambda x: (x[0], x[1]))

        report = _format_violations(unique_violations)
        assert len(unique_violations) == 0, (
            f"AR-3 violation: AQL primitives found in non-persistence code.\n"
            f"AQL syntax (FOR...IN, FILTER, RETURN, UPSERT, etc.) should not appear outside persistence.\n{report}"
        )
