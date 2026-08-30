"""Library domain-boundary enforcement (P5-S3 of TASK-library-domain-facades-A).

Static, no-database scan proving the hard ADR-032/041/043 cut for library
identity. Non-persistence production code (components / services / workflows /
interfaces) must know nothing of the persistence layer:

- it must not import storage row DTOs (``LibraryRow``, ``LibraryFolderRow``,
  ``LibraryScanRow``, ``TagRow``) or the persistence repository namespace;
- it must not reference repository classes directly;
- the removed facade ``list_library_keys`` (generated-id key enumeration) must
  never resurface as a call above persistence;
- all library routes use the mechanism-A natural-name wire identity — no
  integer-id ``{library_id}`` route path segment and no integer decoding of a
  library identity;
- the natural-name wire adapter (``encode_library_name`` / ``decode_library_name``)
  is the sole documented library wire identity mechanism.

These are pure text scans (mirroring ``tests/sabotage/test_sealed_tag_facade_boundary.py``),
so they run without a database. ``HealthRow`` (a non-library health-check DTO) is
deliberately excluded — it is not in the sealed library row list and is outside
this plan's scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Non-persistence layers that must go through the facade, never the storage layer.
CALLER_DIRS = [
    Path("nomarr/components"),
    Path("nomarr/services"),
    Path("nomarr/workflows"),
    Path("nomarr/interfaces"),
]

# Storage row DTOs sealed behind the persistence boundary (ADR-032/041/043).
SEALED_ROW_NAMES = re.compile(r"\b(?:LibraryRow|LibraryFolderRow|LibraryScanRow|TagRow)\b")

# Importing the repository namespace / row DTOs from caller code.
REPO_DTO_IMPORT = re.compile(r"from\s+nomarr\.helpers\.dto\.repo_dto\s+import")
STORAGE_NAMESPACE_IMPORT = re.compile(r"from\s+nomarr\.persistence\.database|import\s+nomarr\.persistence\.database")

# Repository classes are persistence-internal.
REPO_CLASS_NAMES = re.compile(
    r"\b(?:LibraryRepository|FolderRepository|ScanRepository|PipelineRepository"
    r"|TagRepository|SongTagRepository|SongStateRepository)\b"
)

# The removed facade enumeration of generated library keys (P2): must not be
# called above persistence. Docstring mentions (``list_library_keys`` without a
# preceding dot-call) are intentionally not flagged.
LIST_LIBRARY_KEYS_CALL = re.compile(r"\.list_library_keys\s*\(")

# No integer-id library route path segment. All library routes use the
# mechanism-A natural-name segment ``{library_name}``.
INT_LIBRARY_ROUTE_SEGMENT = re.compile(r"@router\.(?:get|post|patch|put|delete).*\{library_id\}")


def _scan_dir(directory: Path, pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
    dir_path = PROJECT_ROOT / directory
    if not dir_path.exists():
        return []
    violations: list[tuple[str, int, str]] = []
    for py_file in dir_path.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                violations.append((str(py_file.relative_to(PROJECT_ROOT)), line_num, line.strip()))
    return violations


def _scan_dir_by_import(directory: Path, names: re.Pattern[str]) -> list[tuple[str, int, str]]:
    """Flag lines that both import from repo_dto AND reference a sealed row name."""
    dir_path = PROJECT_ROOT / directory
    if not dir_path.exists():
        return []
    violations: list[tuple[str, int, str]] = []
    for py_file in dir_path.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), start=1):
            if REPO_DTO_IMPORT.search(line) and names.search(line):
                violations.append((str(py_file.relative_to(PROJECT_ROOT)), line_num, line.strip()))
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


def _assert_clean(pattern: re.Pattern[str], message: str) -> None:
    violations: list[tuple[str, int, str]] = []
    for directory in CALLER_DIRS:
        violations.extend(_scan_dir(directory, pattern))
    assert len(violations) == 0, f"{message}\n{_format(violations)}"


@pytest.mark.sabotage_check
class TestLibraryRowsSealedBehindPersistence:
    """Storage row DTOs never cross into non-persistence production code."""

    def test_no_sealed_row_imports_from_repo_dto(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan_dir_by_import(directory, SEALED_ROW_NAMES))
        assert len(violations) == 0, (
            "LibraryRow/LibraryFolderRow/LibraryScanRow/TagRow are persistence-internal "
            "(ADR-032/041/043); non-persistence code must receive domain values "
            "(Library/LibraryFolder/LibraryScan/TagIdentity), never storage row DTOs.\n"
            f"{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestNoDirectStorageAccess:
    """Callers above persistence never import the repository namespace or its classes."""

    def test_no_storage_namespace_imports(self) -> None:
        _assert_clean(
            STORAGE_NAMESPACE_IMPORT,
            "Components/services/workflows/interfaces must address libraries through the "
            "facade, not by importing nomarr.persistence.database repos/tables directly.",
        )

    def test_no_repository_class_names(self) -> None:
        _assert_clean(
            REPO_CLASS_NAMES,
            "Repository classes (LibraryRepository, FolderRepository, ScanRepository, "
            "PipelineRepository, TagRepository, SongTagRepository, SongStateRepository) are "
            "persistence-internal and must not appear in non-persistence production code.",
        )


@pytest.mark.sabotage_check
class TestNoGeneratedIdKeyEnumeration:
    """The removed facade key enumeration never resurfaced."""

    def test_no_list_library_keys_calls_above_persistence(self) -> None:
        _assert_clean(
            LIST_LIBRARY_KEYS_CALL,
            "list_library_keys (generated library-id enumeration) was removed from the facade "
            "(P2); callers address libraries by natural (name, root_path) identity and must not "
            "reintroduce an id-key enumeration call.",
        )


@pytest.mark.sabotage_check
class TestNaturalNameWireIdentity:
    """All library routes use the mechanism-A natural-name wire identity."""

    def test_no_integer_id_library_route_segment(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan_dir(directory, INT_LIBRARY_ROUTE_SEGMENT))
        assert len(violations) == 0, (
            "Library routes must use the mechanism-A natural-name segment {library_name} "
            "(URL-encoded), never an integer-id {library_id} path segment — no integer library "
            "route decoding / compat path may remain.\n"
            f"{_format(violations)}"
        )

    def test_natural_name_wire_adapter_exists(self) -> None:
        from nomarr.interfaces.api.id_codec import decode_library_name, encode_library_name

        assert callable(encode_library_name) and callable(decode_library_name), (
            "The mechanism-A natural-name wire adapter (encode_library_name/decode_library_name) "
            "is the sole documented library wire identity mechanism."
        )
