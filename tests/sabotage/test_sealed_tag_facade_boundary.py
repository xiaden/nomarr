"""Sabotage checks: sealed song-tag facade boundary (P6-S5).

Enforces the sealed ``LibraryTagsDb`` surface from
``TASK-song-intent-facade-correction-A``:

- Facade results are domain objects (``TagRef`` / ``SongTagAssignment`` /
  ``TagUsage`` / ``RelinkResult`` / ``TagCleanupResult`` / ``Song`` /
  ``SongTagMatch``) — never raw rows, dict edges, or integer tag ids.
- ``SongTagAssignment`` carries a domain ``SongIdentity`` handle, never a
  storage ``song_id``.
- Callers above persistence address tags/songs by natural identity and never
  import the storage repos directly.
- Legacy edge/ID facade method names (``search_songs_by_tag*``,
  ``list_song_ids_for_tag_id``, ``list_song_tag_edges``, ``list_tags_by_name``,
  ``delete_tags_by_ids``, ``list_orphaned_tag_ids``, ``replace_tag_references*``,
  ``find_or_create_tag``) do not resurface as object-attribute calls in
  non-persistence code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Directories that must go through the facade (not the storage repos / tables).
CALLER_DIRS = [
    Path("nomarr/components"),
    Path("nomarr/services"),
    Path("nomarr/workflows"),
    Path("nomarr/interfaces"),
]

# Layers that hold direct facade (db) references and would call a reverted/deleted
# facade method. The web/interface layer is excluded: it legitimately calls SERVICE
# methods whose public API deliberately preserves the endpoint-aligned name (e.g.
# ``TaggingService.search_songs_by_tag``) while delegating to the facade's new
# ``find_songs_with_tag`` internally.
LEGACY_CALLER_DIRS = [
    Path("nomarr/components"),
    Path("nomarr/services"),
    Path("nomarr/workflows"),
]

# The sealed facade and its repos legitimately reference these repo-level names
# internally (e.g. ``self._song_tag_repo.search_songs_by_tag``), so we scan only
# non-persistence caller code for their (re)appearance as object-attribute calls.
LEGACY_FACADE_METHOD_PATTERN = re.compile(
    r"\.(?:"
    r"search_songs_by_tag(?:_contains|_pattern)?"
    r"|list_song_ids_for_tag_id"
    r"|list_song_tag_edges"
    r"|list_tags_by_name"
    r"|delete_tags_by_ids"
    r"|list_orphaned_tag_ids"
    r"|replace_tag_references|replace_selected_tag_references"
    r"|find_or_create_tag"
    r")\b"
)

# Direct import of the storage layer (repos / database/) from caller code.
STORAGE_IMPORT_PATTERN = re.compile(
    r"^\s*from\s+nomarr\.persistence\.database|^\s*import\s+nomarr\.persistence\.database"
)


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


def _format(violations: list[tuple[str, int, str]], limit: int = 20) -> str:
    if not violations:
        return "No violations found."
    lines = [f"Found {len(violations)} violation(s):"]
    for filepath, line_num, line_text in violations[:limit]:
        lines.append(f"  {filepath}:{line_num}: {line_text}")
    if len(violations) > limit:
        lines.append(f"  ... and {len(violations) - limit} more")
    return "\n".join(lines)


@pytest.mark.sabotage_check
class TestNoLegacyFacadeMethodCalls:
    """Legacy edge/ID facade method names never resurface as attribute calls."""

    def test_no_legacy_method_calls_in_caller_code(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in LEGACY_CALLER_DIRS:
            violations.extend(_scan_dir(directory, LEGACY_FACADE_METHOD_PATTERN))
        assert len(violations) == 0, (
            "Callers must use the sealed domain facade (TagRef/SongIdentity); "
            "legacy edge/ID method names (search_songs_by_tag*, list_song_ids_for_tag_id, "
            "list_song_tag_edges, list_tags_by_name, delete_tags_by_ids, "
            "list_orphaned_tag_ids, replace_tag_references*, find_or_create_tag) "
            "must not reappear as object calls above persistence.\n"
            f"{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestNoDirectStorageImports:
    """Callers above persistence never import the storage repos directly."""

    def test_components_services_workflows_interfaces_do_not_import_storage(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan_dir(directory, STORAGE_IMPORT_PATTERN))
        assert len(violations) == 0, (
            "Components/services/workflows/interfaces must address tags/songs through "
            "the sealed facade, not by importing nomarr.persistence.database repos/tables "
            "directly.\n"
            f"{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestSongTagAssignmentHasNoSongId:
    """SongTagAssignment exposes a domain SongIdentity handle, never storage song_id."""

    def test_assignment_has_no_storage_song_id_field(self) -> None:
        import dataclasses

        from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment

        assert "song_id" not in {f.name for f in dataclasses.fields(SongTagAssignment)}, (
            "SongTagAssignment must carry the domain song handle (SongIdentity), not a "
            "storage integer song_id crossing the facade."
        )
        assert "song" in {f.name for f in dataclasses.fields(SongTagAssignment)}

    def test_sealed_facade_has_no_transaction_context(self) -> None:
        """The tag facade exposes no transaction context to callers."""
        from nomarr.persistence.api.library_tags import LibraryTagsDb

        assert not any(
            name in ("transaction", "begin_transaction", "require_transaction") for name in dir(LibraryTagsDb)
        ), "LibraryTagsDb must not expose a transaction context (UoW lives in the repos)."
