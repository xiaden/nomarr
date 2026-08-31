"""Sabotage tests: song-tag facade boundary (TASK-song-intent-facade-correction-A P6-S5).

Ownership rules (per artifacts/designs/parts/song-domain-repair/CONTRACTS.md and
ADR-032/041):

- The sealed tag facade (``LibraryTagsDb`` + ``LibraryDb`` tag forwarders)
  accepts/returns only domain values (``SongIdentity`` / ``TagRef`` /
  ``SongTagAssignment`` / ``TagUsage`` / typed results). Storage ids, row dicts,
  and junction-edge shapes are persistence-private.
- ``SongTagAssignment`` carries a ``SongIdentity`` natural handle — never a
  storage ``song_id``.
- Legacy edge/ID/row facade names are removed and must never reappear on the
  sealed facade surface: ``list_song_tag_edges``, ``list_song_ids_for_tag_id``,
  ``list_tags_by_name``, ``delete_tags_by_ids``, ``find_or_create_tag``,
  ``search_songs_by_tag``, ``replace_tag_references``,
  ``replace_selected_tag_references``, ``list_orphaned_tag_ids``.
  (``list_tags_by_name`` / ``search_songs_by_tag`` MAY exist as component /
  service / API wrapper *names* — those are the sanctioned higher-layer
  functions wrapping the facade — but never as facade methods.)
- No specific repository/table module is imported above persistence. Components,
  services, and workflows may touch persistence only through the injected public
  ``Database`` intent facades from ``nomarr.persistence.db``; interfaces and
  helpers must not import persistence.
- Allowed int→domain exceptions, which must be preserved:
  - the identity bridge ``resolve_song_identity(song_id)`` (documented conversion
    point at the library boundary),
  - ``HydrateSongInput.song_id`` (hydration handle),
  - ``FileTag`` / ``(file_id, tag_value)`` analytics tuples (interface /
    physical-file projections).

The tests scan source code at test time and report violations. The scan scope is
clean — all violations were resolved by Phase 6, and the suite is GREEN.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FACADE_MODULES = [
    Path("nomarr/persistence/api/library_tags.py"),
    Path("nomarr/persistence/api/library.py"),
    Path("nomarr/persistence/api/library_songs.py"),
]
ASSIGNMENT_FILE = Path("nomarr/helpers/dataclasses/song_tag_dataclass.py")
ABOVE_PERSISTENCE_DIRS = [
    Path("nomarr/components"),
    Path("nomarr/services"),
    Path("nomarr/workflows"),
    Path("nomarr/interfaces"),
]

# Legacy facade method names — must not exist as methods on the sealed facade.
LEGACY_FACADE_METHODS = [
    "list_song_tag_edges",
    "list_song_ids_for_tag_id",
    "list_tags_by_name",
    "delete_tags_by_ids",
    "find_or_create_tag",
    "search_songs_by_tag",
    "replace_tag_references",
    "replace_selected_tag_references",
    "list_orphaned_tag_ids",
]
LEGACY_METHOD_PATTERN = re.compile(r"def\s+(" + "|".join(LEGACY_FACADE_METHODS) + r")\s*\(")

# Specific repository / table modules must not be imported above persistence.
REPO_IMPORT_PATTERN = re.compile(r"^\s*from\s+nomarr\.persistence\.(database|repositories)\b")

# repo_dto (TagRow/SongRow storage shapes) must not be imported by the facade.
REPO_DTO_IMPORT_PATTERN = re.compile(r"^\s*from\s+nomarr\.helpers\.dto\.repo_dto")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(rel_path: Path) -> str:
    project_root = Path(__file__).parent.parent.parent
    return (project_root / rel_path).read_text(encoding="utf-8")


def _scan_dir(directory: Path, pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
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


def _scan_file_lines(rel_path: Path, predicate) -> list[tuple[str, int, str]]:
    content = _read(rel_path)
    return [(str(rel_path), i, line.strip()) for i, line in enumerate(content.splitlines(), start=1) if predicate(line)]


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
# Test 1: Legacy edge/ID/row facade methods never reappear on the sealed facade
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestFacadeLegacyMethodNamesBanned:
    """The sealed tag facade exposes no legacy edge/ID/row methods."""

    def test_no_legacy_method_definitions_on_facade(self) -> None:
        """None of the removed legacy method names exist on the facade surface."""
        violations: list[tuple[str, int, str]] = []
        for module in FACADE_MODULES:
            for filepath, line_num, line_text in _scan_file_lines(
                module,
                LEGACY_METHOD_PATTERN.search,
            ):
                # Skip comments/docstrings that merely describe removed methods.
                if line_text.lstrip().startswith("#") or '"""' in line_text or "``" in line_text:
                    continue
                violations.append((filepath, line_num, line_text))
        assert len(violations) == 0, (
            "Legacy facade method names must never reappear on the sealed tag "
            "facade; higher layers use find_songs_with_*, ensure_tag, "
            "cleanup_orphaned_tags, list_tags(name=...) instead.\n"
            f"{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 2: SongTagAssignment carries a SongIdentity handle, never a song_id
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoStorageSongIdOnAssignment:
    """``SongTagAssignment`` must not carry a storage ``song_id``."""

    def test_assignment_has_no_song_id_field(self) -> None:
        """No ``song_id`` field definition on the assignment dataclass."""
        violations = _scan_file_lines(
            ASSIGNMENT_FILE,
            lambda line: re.match(r"^\s*song_id\s*:", line) is not None,
        )
        assert len(violations) == 0, (
            "SongTagAssignment must carry song: SongIdentity|None (natural "
            "handle), never a storage song_id.\n"
            f"{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 3: No specific repository/table import above persistence
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoRepoImportAbovePersistence:
    """Components/services/workflows/interfaces never import repository modules."""

    def test_no_specific_repo_import_in_higher_layers(self) -> None:
        """Higher layers use the injected public facade, not repository internals."""
        violations: list[tuple[str, int, str]] = []
        for directory in ABOVE_PERSISTENCE_DIRS:
            violations.extend(_scan_dir(directory, REPO_IMPORT_PATTERN))
        assert len(violations) == 0, (
            "Higher layers must not import specific persistence repository/"
            "database modules; they go through the sealed facade.\n"
            f"{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 4: Facade never imports the storage-row DTO module
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestFacadeDoesNotImportRowDto:
    """The facade uses mappers, never raw ``repo_dto`` row shapes."""

    def test_facade_does_not_import_repo_dto(self) -> None:
        """TagRow/SongRow (repo_dto) must not be imported by the facade modules."""
        violations: list[tuple[str, int, str]] = []
        for module in FACADE_MODULES:
            violations.extend(_scan_file_lines(module, REPO_DTO_IMPORT_PATTERN.search))
        assert len(violations) == 0, (
            "The facade converts rows via nomarr.persistence.mappers; it must "
            "not import raw repo_dto row shapes directly.\n"
            f"{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 5 (P1-S5b): Assignment paths never import the namespace-free projection
# ---------------------------------------------------------------------------
# ``tags_from_tag_rows`` is the documented namespace-free physical/analytics
# boundary; resolving/persisting assignments must go through the namespace-
# bearing ``song_tag_mapper`` (TagRef / SongTagAssignment). The facade modules
# must therefore never import that namespace-dropping projection.

NAMESPACE_FREE_IMPORT_PATTERN = re.compile(
    r"\btags_from_tag_rows\b|from\s+nomarr\.persistence\.mappers\.tag_mapper\s+import"
)


@pytest.mark.sabotage_check
class TestFacadeNeverImportsNamespaceFreeProjection:
    """The tag facade never resolves/persists assignments via the namespace-free projection."""

    def test_facade_modules_do_not_import_namespace_free_projection(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for module in FACADE_MODULES:
            for filepath, line_num, line_text in _scan_file_lines(module, NAMESPACE_FREE_IMPORT_PATTERN.search):
                if line_text.lstrip().startswith("#"):
                    continue
                violations.append((filepath, line_num, line_text))
        assert len(violations) == 0, (
            "Assignment resolution/persistence must use the namespace-bearing "
            "song_tag_mapper paths; the namespace-free tags_from_tag_rows "
            f"projection must not be imported by the facade.\n{_format(violations)}"
        )


# ---------------------------------------------------------------------------
# Test 6: Sanctioned int→domain exceptions are preserved
# ---------------------------------------------------------------------------

BRIDGE_SONG_PATTERN = re.compile(r"def\s+resolve_song_identity\s*\(")
BRIDGE_IDENTITIES_PATTERN = re.compile(r"def\s+resolve_song_identities\s*\(")


@pytest.mark.sabotage_check
class TestSanctionedExceptionsPreserved:
    """The documented int→domain exceptions still exist (identity bridge, hydration)."""

    def test_identity_bridge_resolve_song_identity_present(self) -> None:
        """resolve_song_identity(song_id) remains the library-boundary bridge."""
        songs_module = Path("nomarr/persistence/api/library_songs.py")
        content = _read(songs_module)
        assert BRIDGE_SONG_PATTERN.search(content), (
            "The identity bridge resolve_song_identity(song_id) must remain on LibrarySongsDb / LibraryDb."
        )

    def test_identity_bridge_resolve_song_identities_present(self) -> None:
        """Set-based resolve_song_identities(ids) remains for batch conversion."""
        songs_module = Path("nomarr/persistence/api/library_songs.py")
        content = _read(songs_module)
        assert BRIDGE_IDENTITIES_PATTERN.search(content), (
            "resolve_song_identities must remain for batch int->SongIdentity."
        )

    def test_hydrate_song_input_keeps_song_id_handle(self) -> None:
        """HydrateSongInput.song_id is the sole documented narrow semantic handle."""
        assert _has_hydrate_song_input_song_id(), (
            "HydrateSongInput must keep its song_id:int narrow semantic handle (documented ADR-041 exception)."
        )


def _has_hydrate_song_input_song_id() -> bool:
    project_root = Path(__file__).parent.parent.parent
    dto_file = project_root / "nomarr/helpers/dto/hydration_dto.py"
    if not dto_file.exists():
        return False
    content = dto_file.read_text(encoding="utf-8")
    if "class HydrateSongInput" not in content:
        return False
    body = content.split("class HydrateSongInput", 1)[1]
    in_class = body.split("class ", 1)[0] if "class " in body else body
    return re.search(r"^\s*song_id\s*:", in_class, re.MULTILINE) is not None
