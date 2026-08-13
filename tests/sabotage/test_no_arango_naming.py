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

import io
import re
import tokenize
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
# AR-SDR-1 file-domain elimination surface (songs are the sole canonical entity)
# ---------------------------------------------------------------------------
# Directories scanned for the AR-SDR-1 persistence/domain elimination surface:
# persistence plus all non-persistence layers (helpers is already covered by
# NON_PERSISTENCE_DIRS).
FILE_DOMAIN_DIRS = [Path("nomarr/persistence"), *NON_PERSISTENCE_DIRS]

# Eliminated entity/type/facade/transaction surface (hard-zero after Plans A-D).
FILE_ENTITY_PATTERNS = [
    re.compile(r"\blibrary_files\b"),
    re.compile(r"\bLibraryFile\b"),
    re.compile(r"\bLibraryFilesDb\b"),
    re.compile(r"\bFileRepository\b"),
    re.compile(r"\bFileTagRepository\b"),
    re.compile(r"\bFileStateRepository\b"),
    re.compile(r"db\.library\.files"),
    re.compile(r"_require_transaction"),
    re.compile(r"FacadeMisuseError"),
    re.compile(r"\.transaction\("),
]

# Eliminated persistence table/entity names. Scanned as code tokens; prose inside
# docstrings/comments is excluded so prose like "current file_tags" does not count
# as a persistence/domain reference. file_state_assignments is hard-zero.
FILE_TABLE_PATTERNS = [
    re.compile(r"\bfile_tags\b"),
    re.compile(r"\bfile_states\b"),
    re.compile(r"file_state_assignments"),
]

# EXCEPTION ALLOWLIST (AR-SDR-1/6/7): a matching line is NOT a violation.
# (a) Physical audio-file tag-IO layer — writing tags to physical audio files.
# (b) AR-SDR-6 constants seed-source modules (file_states.py / pipeline_states.py);
#     imports of STATE_*/ALL_STATE_VERTICES are sanctioned.
# (c) Wire/API-contract `file_id` in nomarr/interfaces/ + interface DTOs
#     (AR-SDR-7: no frontend/API contract changes). No bare `file_id` pattern is
#     scanned here — it is scoped to the persistence+domain API surface in P3-S3;
#     cosmetic local `file_id` variables in components/services/workflows are out
#     of scope per the AMEND (447 hits verified, zero in persistence).
FILE_ALLOWLIST = [
    # (a) physical audio-file tag-IO layer
    re.compile(r"file_tags_io_wf"),
    re.compile(r"write_file_tags_wf"),
    re.compile(r"read_file_tags_workflow"),
    re.compile(r"remove_file_tags_workflow"),
    re.compile(r"write_file_tags_workflow"),
    re.compile(r"\bread_file_tags\b"),
    re.compile(r"\bremove_file_tags\b"),
    re.compile(r"\bwrite_file_tags\b"),
    re.compile(r"file_write_comp"),
    re.compile(r"\bTagWriter\b"),
    re.compile(r"\bsafe_write\b"),
    # (b) AR-SDR-6 constants seed source
    re.compile(r"file_states import"),
    re.compile(r"pipeline_states import"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docstring_lines(content: str) -> set[int]:
    """Return 1-based line numbers that fall inside triple-quoted docstrings.

    Uses the ``tokenize`` module so prose inside docstrings is excluded from
    scans without hiding genuine string-literal references (e.g. a
    ``__tablename__ = "file_tags"`` line is NOT a docstring and is still
    detected).
    """
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(content).readline):
            if tok.type == tokenize.STRING and (tok.string.startswith('"""') or tok.string.startswith("'''")):
                for ln in range(tok.start[0], tok.end[0] + 1):
                    lines.add(ln)
    except (tokenize.TokenError, IndentationError, UnicodeDecodeError):
        pass
    return lines


def _scan_files_for_pattern(
    directories: list[Path],
    pattern: re.Pattern[str],
    *,
    exclude_comments: bool = False,
    exclude_docstrings: bool = False,
) -> list[tuple[str, int, str]]:
    """Scan Python files in directories for a regex pattern.

    Args:
        directories: Directories to scan (relative to project root).
        pattern: Compiled regex pattern to match.
        exclude_comments: If True, skip lines that are pure comments.
        exclude_docstrings: If True, skip lines inside triple-quoted docstrings.

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
            doc_lines = _docstring_lines(content) if exclude_docstrings else set()
            for line_num, line in enumerate(content.splitlines(), start=1):
                # Skip pure comment lines if requested
                if exclude_comments and line.lstrip().startswith("#"):
                    continue
                # Skip lines inside docstrings if requested
                if exclude_docstrings and line_num in doc_lines:
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


# ---------------------------------------------------------------------------
# Test 6: No AR-SDR-1 file-domain naming in persistence/domain surface
# ---------------------------------------------------------------------------


def _dedupe_violations(
    violations: list[tuple[str, int, str]],
) -> list[tuple[str, int, str]]:
    """Deduplicate and sort (filepath, line, text) violation tuples."""
    unique = list(set(violations))
    unique.sort(key=lambda x: (x[0], x[1]))
    return unique


def _scan_file_domain_entities() -> list[tuple[str, int, str]]:
    """Scan for the eliminated entity/type/facade/transaction surface."""
    violations: list[tuple[str, int, str]] = []
    for pattern in FILE_ENTITY_PATTERNS:
        violations.extend(_scan_files_for_pattern(FILE_DOMAIN_DIRS, pattern, exclude_comments=True))
    return _dedupe_violations(violations)


def _scan_file_domain_tables() -> list[tuple[str, int, str]]:
    """Scan for eliminated persistence table/entity names (prose excluded)."""
    violations: list[tuple[str, int, str]] = []
    for pattern in FILE_TABLE_PATTERNS:
        for filepath, line_num, line in _scan_files_for_pattern(
            FILE_DOMAIN_DIRS,
            pattern,
            exclude_comments=True,
            exclude_docstrings=True,
        ):
            if any(allow.search(line) for allow in FILE_ALLOWLIST):
                continue
            violations.append((filepath, line_num, line))
    return _dedupe_violations(violations)


@pytest.mark.sabotage_check
class TestNoFileDomainNaming:
    """AR-SDR-1: no file-domain persistence/domain vocabulary outside the allowlist.

    Songs are the sole canonical library entity. The file-domain entity, type,
    facade, repository, and transaction surface must not reappear in
    ``nomarr/persistence/`` or non-persistence layers. The physical audio-file
    tag-IO layer, the AR-SDR-6 constants seed-source modules, and the
    wire/API-contract ``file_id`` in interfaces are explicitly allowlisted.
    """

    def test_no_file_domain_entities(self):
        """No eliminated entity/type/facade/transaction vocabulary."""
        violations = _scan_file_domain_entities()
        report = _format_violations(violations)
        assert len(violations) == 0, (
            "AR-SDR-1 violation: file-domain entity/type/facade/transaction "
            "vocabulary found (songs are the sole canonical entity).\n" + report
        )

    def test_no_file_domain_table_names(self):
        """No eliminated persistence table/entity names outside the allowlist."""
        violations = _scan_file_domain_tables()
        report = _format_violations(violations)
        assert len(violations) == 0, (
            "AR-SDR-1 violation: file-domain persistence table/entity name found "
            "outside the AR-SDR-1/6/7 allowlist.\n" + report
        )
