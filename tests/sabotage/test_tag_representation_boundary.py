"""Sabotage tests: tag representation boundary (TASK-tag-boundary-A).

Ownership rules (per artifacts/designs/parts/tag-boundary/CONTRACTS.md):
- ``nomarr/helpers/dataclasses/tags_dataclass.py`` is the canonical domain
  ``Tag``/``Tags`` — it must NOT expose DB-row factories or persistence fields.
- ``TagRow`` (``nomarr/helpers/dto/repo_dto.py``) + ``nomarr/persistence/``
  own the storage shape; row-to-domain conversion is the persistence mapper
  ``nomarr/persistence/mappers/tag_mapper.py``.
- ``FileTag`` (``nomarr/helpers/dto/library_dto.py``) is the library/API
  contract (key/value/tag_type/is_nomarr); the single row-to-``FileTag``
  projection is ``nomarr/components/library/tag_mapping_comp.py``.
- The API/frontend wire field is ``tag_type`` — never a ``type``/``tag_type``
  split.

The tests scan source code at test time and report violations. The scan scope
is clean — all violations here were resolved in TASK-tag-boundary-A, plus the
Plan C P1-S5 extension ``TestTagPersistenceOwnership`` (identity-only ORM /
DTO / repository static gates):
- ``tags`` is identity-only: the ORM model, repo_dto ``TagRow``, and tag_mapper
  projections expose no removed metadata columns/keys (source/confidence/tier/
  created_at/parent_tag_id); edge metadata lives only on ``song_tags``.
- No persistence code persists an empty/NULL ordinary namespace (blank->
  ``default`` normalization only) and the namespace-free ``tags_from_tag_rows``
  projection stays a documented physical/API boundary, never imported on
  assignment resolution/persistence paths.

Green claim is scoped to this file's scans. (Sibling
``test_no_facades_begin_transactions.py`` has 6 pre-existing Docker-gated env
errors unrelated to this suite.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOMAIN_TAGS_FILE = Path("nomarr/helpers/dataclasses/tags_dataclass.py")
PERSISTENCE_DIR = Path("nomarr/persistence")
COMPONENT_DIRS = [Path("nomarr/components/library"), Path("nomarr/components/tagging")]
DTO_DIR = Path("nomarr/helpers/dto")
SERVICE_DIRS = [Path("nomarr/services/domain/tagging_svc"), Path("nomarr/services/domain/library_svc")]
API_TYPES_DIR = Path("nomarr/interfaces/api/types")
API_WEB_DIR = Path("nomarr/interfaces/api/web")

# (TASK-tag-persistence-ownership-B Phase 3) Active persistence files that own
# tags identity reads/writes — the static-scan targets for namespace and
# identity-only ownership drift guards.
TAG_MAPPER_FILE = Path("nomarr/persistence/mappers/tag_mapper.py")
TAG_DB_FILES = [
    Path("nomarr/persistence/database/tag_repo.py"),
    Path("nomarr/persistence/database/song_tag_repo.py"),
    Path("nomarr/persistence/database/song_hydration_repo.py"),
]

# Removed ``tags`` metadata columns: ``tags`` is identity-only (id, namespace,
# name, value). Edge metadata (confidence/source) lives on ``song_tags`` and is
# the only sanctioned home — never on tag identity rows.
REMOVED_TAG_METADATA_KEYS = ("source", "confidence", "tier", "created_at", "parent_tag_id")

# A removed tag-metadata name referenced as a ``tags``-table column (a read of a
# column that no longer exists on the identity-only table).
TAGS_REMOVED_COLUMN_READ_PATTERN = re.compile(r"_T\.c\.(source|confidence|tier|created_at|parent_tag_id)\b")

# A removed tag-metadata name used as a dict key literal in a row/projection.
REMOVED_META_KEY_LITERAL_PATTERN = re.compile(r"""["'](source|confidence|tier|created_at|parent_tag_id)["']\s*:""")

# Persisting an empty/NULL ordinary namespace literal. Only the canonical
# blank -> "default" normalization is allowed (TagRef/SongTagAssignment
# __post_init__, mapper ``_row_namespace`` / ``_normalize_namespace``); a raw
# ``namespace=""`` / ``namespace=None`` fallback is a NULL-as-ordinary bug.
EMPTY_NAMESPACE_LITERAL_PATTERN = re.compile(r"""namespace\s*[:=]\s*["']{2}|namespace\s*[:=]\s*None\b""")

# Persistence-only field names that must never appear in the domain dataclass.
PERSISTENCE_FIELD_PATTERN = re.compile(
    r"\bnamespace\b|\bprovenance\b|\bconfidence\b|\btier\b|\bcreated_at\b|\bupdated_at\b"
)

# Domain dataclass must not import persistence modules.
PERSISTENCE_IMPORT_PATTERN = re.compile(r"^\s*from\s+nomarr\.persistence|^\s*import\s+nomarr\.persistence")

# No DB-row factory on the domain dataclass.
FROM_DB_ROWS_PATTERN = re.compile(r"\bfrom_db_rows\b")

# TagRow (repo_dto) must not leak into API types or non-persistence DTOs used by services.
REPO_DTO_IMPORT_PATTERN = re.compile(
    r"^\s*from\s+nomarr\.helpers\.dto\.repo_dto|^\s*import\s+nomarr\.helpers\.dto\.repo_dto"
)

# Duplicated row-to-FileTag projections (old dict-shape helpers) must not reappear.
# ``_tags_for_song`` is the sanctioned call-site wrapper that delegates to
# ``file_tag_from_tag_row`` — it is not a duplicated projection.
PROJECT_TAG_ROW_PATTERN = re.compile(r"\b_project_tag_row\b|\b_FileTagItem\b")

# Pydantic/API FileTag responses must use tag_type, not the old 'type' field.
API_TYPE_FIELD_PATTERN = re.compile(r"^\s*type\s*:\s*str")

# Generic row-to-dict tag projection: any component still hand-building
# {'key', 'value', 'type'/'tag_type'...} dicts instead of using the mapper
# would count as a drift point only if it materializes dict rows — the
# canonical mapper lives in tag_mapping_comp; scan for direct construction
# of the type field with a literal key in the library components.
TYPE_KEY_LITERAL_PATTERN = re.compile(r"""["']type["']\s*:\s*["'](string|float)["']""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(rel_path: Path) -> str:
    project_root = Path(__file__).parent.parent.parent
    return (project_root / rel_path).read_text(encoding="utf-8")


def _scan_dir(directory: Path, pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
    """Scan .py files under a directory (relative to project root) for a regex."""
    project_root = Path(__file__).parent.parent.parent
    dir_path = project_root / directory
    if not dir_path.exists():
        return []
    violations: list[tuple[str, int, str]] = []
    for py_file in dir_path.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                violations.append((str(py_file.relative_to(project_root)), line_num, line.strip()))
    return violations


def _format(violations: list[tuple[str, int, str]], limit: int = 20) -> str:
    if not violations:
        return "No violations found."
    lines = [f"Found {len(violations)} violation(s):"]
    for filepath, line_num, line_text in violations[:limit]:
        lines.append(f"  {filepath}:{line_num}: {line_text}")
    if len(violations) > limit:
        lines.append(f"  ... and {len(violations) - limit} more")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Test 1: Domain Tags/Tag stays canonical — no persistence leakage
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestDomainTagsBoundary:
    """Domain ``Tag``/``Tags`` must not expose DB rows or persistence fields."""

    def test_domain_tags_has_no_from_db_rows_factory(self) -> None:
        """The canonical domain dataclass no longer exposes a DB-row factory."""
        content = _read(DOMAIN_TAGS_FILE)
        violations = [
            (str(DOMAIN_TAGS_FILE), i, line.strip())
            for i, line in enumerate(content.splitlines(), start=1)
            if FROM_DB_ROWS_PATTERN.search(line) and not line.lstrip().startswith("#") and '"""' not in line
        ]
        assert len(violations) == 0, (
            "Domain Tags must not expose a DB-row factory; use the persistence "
            f"mapper nomarr.persistence.mappers.tag_mapper.tags_from_tag_rows.\n"
            f"{_format(violations)}"
        )

    def test_domain_tags_does_not_import_persistence(self) -> None:
        """Domain dataclass does not import persistence-layer modules."""
        content = _read(DOMAIN_TAGS_FILE)
        violations = [
            (str(DOMAIN_TAGS_FILE), i, line.strip())
            for i, line in enumerate(content.splitlines(), start=1)
            if PERSISTENCE_IMPORT_PATTERN.search(line)
        ]
        assert len(violations) == 0, f"Domain dataclass must not import persistence modules.\n{_format(violations)}"

    def test_domain_tags_has_no_persistence_only_fields(self) -> None:
        """Domain dataclass has no persistence-only field definitions."""
        content = _read(DOMAIN_TAGS_FILE)
        violations = [
            (str(DOMAIN_TAGS_FILE), i, line.strip())
            for i, line in enumerate(content.splitlines(), start=1)
            if re.search(r"^\s*(namespace|provenance|confidence|tier|created_at|updated_at)\s*[:=]", line)
        ]
        assert len(violations) == 0, (
            f"Domain Tag/Tags carries only name/value — no persistence fields.\n{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 2: TagRow stays in repo_dto + persistence — no API/domain leakage
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestTagRowBoundary:
    """``TagRow`` stays a persistence/DTO storage shape, not imported by API types."""

    def test_api_types_do_not_import_repo_dto(self) -> None:
        """API type modules never import the persistence row DTO module."""
        violations = _scan_dir(API_TYPES_DIR, REPO_DTO_IMPORT_PATTERN)
        violations.extend(_scan_dir(API_WEB_DIR, REPO_DTO_IMPORT_PATTERN))
        assert len(violations) == 0, (
            f"API types must not import repo_dto (TagRow is persistence-owned).\n{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 3: Library FileTag projection is centralized in tag_mapping_comp
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestLibraryProjectionBoundary:
    """Row-to-``FileTag`` projection lives only in tag_mapping_comp."""

    def test_no_duplicated_row_projection_helpers(self) -> None:
        """No duplicated row-to-FileTag dict projection helpers remain."""
        violations: list[tuple[str, int, str]] = []
        for directory in COMPONENT_DIRS:
            violations.extend(_scan_dir(directory, PROJECT_TAG_ROW_PATTERN))
        assert len(violations) == 0, (
            "Row-to-FileTag projection must be centralized in "
            "nomarr/components/library/tag_mapping_comp.py — no duplicated "
            "helpers (_project_tag_row / _FileTagItem) allowed.\n"
            f"{_format(violations)}"
        )

    def test_no_type_key_literal_in_tag_projection(self) -> None:
        """No hand-built {'type': 'string'|'float'} dict keys in library components."""
        violations: list[tuple[str, int, str]] = []
        for directory in COMPONENT_DIRS:
            violations.extend(_scan_dir(directory, TYPE_KEY_LITERAL_PATTERN))
        assert len(violations) == 0, (
            "Library tag projections must use FileTag objects with tag_type, "
            "not raw dict rows with a 'type' key.\n"
            f"{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 4: API/frontend use tag_type, never a type/tag_type split
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestApiTagTypeBoundary:
    """Wire field for FileTag responses is ``tag_type`` everywhere."""

    def test_api_web_uses_tag_type_not_type(self) -> None:
        """API web response models use ``tag_type`` (never a bare ``type`` str)."""
        violations = _scan_dir(API_WEB_DIR, API_TYPE_FIELD_PATTERN)
        assert len(violations) == 0, (
            "API FileTag response models must declare tag_type, not a bare "
            "'type' field (would split the wire contract).\n"
            f"{_format(violations)}"
        )

    def test_service_tag_payloads_use_tag_type(self) -> None:
        """Tag payloads built in services use the 'tag_type' key, not 'type'."""
        violations: list[tuple[str, int, str]] = []
        for directory in SERVICE_DIRS:
            violations.extend(_scan_dir(directory, TYPE_KEY_LITERAL_PATTERN))
        assert len(violations) == 0, (
            "Service tag payload dicts must use the 'tag_type' key to match "
            "the FileTag contract.\n"
            f"{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 5: No raw from_db_rows usage remains anywhere in nomarr/ or tests/
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoFromDbRowsAnywhere:
    """The ``from_db_rows`` factory is fully removed from the codebase."""

    def test_no_from_db_rows_in_nomarr_python(self) -> None:
        """No ``from_db_rows`` symbol references in nomarr/ source or tests."""
        project_root = Path(__file__).parent.parent.parent
        dirs = [
            Path("nomarr"),
            Path("tests/unit"),
            Path("tests/characterization"),
        ]
        this_file = "tests/sabotage/test_tag_representation_boundary.py"
        violations: list[tuple[str, int, str]] = []
        for directory in dirs:
            dir_path = project_root / directory
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                if str(py_file.relative_to(project_root)) == this_file:
                    continue
                content = py_file.read_text(encoding="utf-8")
                for line_num, line in enumerate(content.splitlines(), start=1):
                    if FROM_DB_ROWS_PATTERN.search(line):
                        violations.append((str(py_file.relative_to(project_root)), line_num, line.strip()))
        assert len(violations) == 0, (
            f"from_db_rows must be gone — row-to-domain conversion is the persistence mapper.\n{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 6 (TASK-tag-persistence-ownership-B Phase 3): namespace + identity-only
# ownership in active persistence reads/writes
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestTagPersistenceOwnership:
    """``tags`` is identity-only and ordinary namespaces are never NULL/empty.

    Phase 3 ownership rules:
    - No active persistence read/write touches removed ``tags`` metadata columns
      (source/confidence/tier/created_at/parent_tag_id) on the identity-only
      table; edge metadata lives only on ``song_tags``.
    - No persistence code persists an empty/NULL ordinary namespace; the only
      sanctioned rule is blank -> ``default`` normalization.
    - The namespace-free ``Tags`` projection stays a documented physical/API
      boundary and is never used to resolve or persist assignments.
    """

    def test_no_tags_table_read_of_removed_metadata(self) -> None:
        """No read of a removed column from the identity-only ``tags`` table."""
        violations: list[tuple[str, int, str]] = []
        for rel in TAG_DB_FILES:
            for line_num, line in enumerate(_read(rel).splitlines(), start=1):
                if TAGS_REMOVED_COLUMN_READ_PATTERN.search(line):
                    violations.append((str(rel), line_num, line.strip()))
        assert len(violations) == 0, (
            "tags is identity-only; removed metadata columns (source/confidence/"
            "tier/created_at/parent_tag_id) must never be read from the tags "
            "table in active persistence code. Edge metadata comes only from "
            f"song_tags.\n{_format(violations)}"
        )

    def test_tag_mapper_emits_identity_only_rows(self) -> None:
        """tag_mapper row/projection payloads never include removed metadata keys."""
        content = _read(TAG_MAPPER_FILE)
        violations = [
            (str(TAG_MAPPER_FILE), line_num, line.strip())
            for line_num, line in enumerate(content.splitlines(), start=1)
            if REMOVED_META_KEY_LITERAL_PATTERN.search(line)
        ]
        assert len(violations) == 0, (
            "tag_mapper must emit identity-only rows shaped {name, value, "
            "namespace}; no removed tag-metadata dict keys "
            f"(source/confidence/tier/created_at/parent_tag_id).\n{_format(violations)}"
        )

    def test_no_empty_or_null_ordinary_namespace_in_persistence(self) -> None:
        """No persistence code persists an empty/NULL ordinary namespace."""
        violations = _scan_dir(PERSISTENCE_DIR, EMPTY_NAMESPACE_LITERAL_PATTERN)
        assert len(violations) == 0, (
            "Persistence code must never persist an empty/NULL ordinary "
            "namespace; only the canonical blank -> 'default' normalization "
            f"is allowed.\n{_format(violations)}"
        )

    def test_namespace_free_tags_projection_is_documented(self) -> None:
        """tags_from_tag_rows stays the documented namespace-free physical boundary."""
        content = _read(TAG_MAPPER_FILE)
        assert "namespace-free physical-file projection boundary" in content, (
            "tags_from_tag_rows must remain the documented namespace-free physical/analytics projection boundary."
        )
        # The projection body maps only name/value and never reads namespace.
        assert 'row["namespace"]' not in content, (
            "tags_from_tag_rows is the name/value-only physical projection; it must not read namespace from rows."
        )

    def test_facade_value_frequency_reduction_documented(self) -> None:
        """LibraryTagsDb value-only frequency reduction is a documented display boundary."""
        content = _read(Path("nomarr/persistence/api/library_tags.py"))
        assert "list_tag_value_frequencies" in content
        # The repo grouping is namespace-bearing; the facade may drop namespace
        # only at a documented display boundary, never merging distinct
        # namespaces into one (value, count) row.
        assert "display boundary" in content, (
            "The facade value-only frequency reduction must document its display "
            "boundary so namespace is not silently merged."
        )

    # ── (a) removed metadata absent from tag ORM / DTO / repository projections ─

    def test_tag_orm_model_is_identity_only(self) -> None:
        """The ``tags`` ORM model declares no removed metadata columns/attributes."""
        orm_file = Path("nomarr/persistence/models/tag.py")
        content = _read(orm_file)
        column_pattern = re.compile(r"^\s*(source|confidence|tier|created_at|parent_tag_id)\s*[:=]")
        violations = [
            (str(orm_file), i, line.strip())
            for i, line in enumerate(content.splitlines(), start=1)
            if column_pattern.search(line)
        ]
        assert len(violations) == 0, (
            "tags is identity-only; the ORM model must define only id/namespace/name/"
            "value and no removed metadata columns "
            f"(source/confidence/tier/created_at/parent_tag_id).\n{_format(violations)}"
        )

    def test_tag_row_dto_is_identity_only(self) -> None:
        """repo_dto ``TagRow`` declares only id/namespace/name/value."""
        dto_file = Path("nomarr/helpers/dto/repo_dto.py")
        content = _read(dto_file)
        assert "class TagRow" in content, "TagRow must remain defined in repo_dto."
        body = content.split("class TagRow", 1)[1].split("\nclass ", 1)[0]
        field_pattern = re.compile(r"^\s*(source|confidence|tier|created_at|parent_tag_id)\s*:")
        violations = [
            (str(dto_file), i, line.strip())
            for i, line in enumerate(body.splitlines(), start=1)
            if field_pattern.match(line)
        ]
        assert len(violations) == 0, (
            "TagRow is the tags storage shape and must expose only id/namespace/name/"
            "value — no removed metadata fields "
            f"(source/confidence/tier/created_at/parent_tag_id).\n{_format(violations)}"
        )

    def test_tag_repo_projection_dicts_have_no_removed_metadata(self) -> None:
        """tag_repo/tag_mapper projections never include removed tag-metadata dict keys."""
        violations: list[tuple[str, int, str]] = []
        for rel in (Path("nomarr/persistence/database/tag_repo.py"), TAG_MAPPER_FILE):
            for line_num, line in enumerate(_read(rel).splitlines(), start=1):
                if REMOVED_META_KEY_LITERAL_PATTERN.search(line):
                    violations.append((str(rel), line_num, line.strip()))
        assert len(violations) == 0, (
            "tags identity projections must not emit removed tag-metadata dict keys "
            f"(source/confidence/tier/created_at/parent_tag_id).\n{_format(violations)}"
        )

    # ── (b) namespace-dropping projection absent from assignment paths ─────────

    def test_assignment_paths_never_import_namespace_free_projection(self) -> None:
        """Assignment mappers/facades never import ``tags_from_tag_rows`` (namespace-free)."""
        namespace_dropping_import = re.compile(
            r"\btags_from_tag_rows\b|from\s+nomarr\.persistence\.mappers\.tag_mapper\s+import"
        )
        violations: list[tuple[str, int, str]] = []
        for rel in (
            Path("nomarr/persistence/mappers/song_tag_mapper.py"),
            Path("nomarr/persistence/api/library_tags.py"),
        ):
            for line_num, line in enumerate(_read(rel).splitlines(), start=1):
                if namespace_dropping_import.search(line) and not line.lstrip().startswith("#"):
                    violations.append((str(rel), line_num, line.strip()))
        assert len(violations) == 0, (
            "Assignments must be mapped via the namespace-bearing song_tag_mapper "
            "paths (TagRef/SongTagAssignment); the namespace-free tags_from_tag_rows "
            "projection must not be imported/used to resolve or persist "
            f"assignments.\n{_format(violations)}"
        )

    # ── (c) documented physical/API/analytics projections remain allowed ───────

    def test_documented_projections_still_exist(self) -> None:
        """The sanctioned namespace-free and physical-file projections remain defined."""
        mapper = _read(TAG_MAPPER_FILE)
        assert "def tags_from_tag_rows" in mapper
        assert "def tag_rows_from_tags" in mapper
        mapping_comp = _read(Path("nomarr/components/library/tag_mapping_comp.py"))
        assert "def file_tag_from_tag_row" in mapping_comp, (
            "The physical/API row-to-FileTag projection must remain defined "
            "(tags_from_tag_rows / file_tag_from_tag_row are the documented "
            "namespace-free projection boundary)."
        )
