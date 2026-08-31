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


# ── Worker-claims sealed facade boundary (Phase 3) ────────────────────────────
# The canonical claims intent surface is add_claim / remove_claim / remove_claims /
# list_claims / count_claims (plus the all-claims reset under maintenance). The
# legacy claim persistence names below must never resurface as object-attribute
# calls in caller code. Component-level thin helpers that WRAP the facade (e.g.
# ``release_claim(db, ...)`` calling ``db.app.remove_claim``) are permitted under
# ADR-046; scoping the pattern to attribute access (``\.name``) therefore targets
# the facade/repository surface without false-flagging bare component helper calls.
CLAIM_FACADE_METHOD_PATTERN = re.compile(
    r"\.(?:"
    r"insert_worker_claim|claim_file|release_claim|release_claim_by_song"
    r"|delete_claims_for_workers|delete_claims_for_songs|delete_claims"
    r"|steal_claim|aggregate_worker_claims|count_worker_claims"
    r"|truncate_worker_claims|claim_song|try_insert_or_steal_claim|remove_claim_by_song"
    r")\b"
)

# WorkerClaimRow is a persistence-internal storage shape that must never cross the
# boundary into caller code.
CLAIM_ROW_PATTERN = re.compile(r"\bWorkerClaimRow\b")

# Encoded claim-key construction/parsing (``claim_{song_id}`` /
# ``claim_{claim_type}_{song_id}``) is owned solely by the persistence repo
# (``app_repo.py``); no higher layer constructs, parses, or compares these strings.
CLAIM_KEY_ENCODING_PATTERN = re.compile(r"_claim_key\s*\(|_parse_claim_key\s*\(|f[\"']claim_")


@pytest.mark.sabotage_check
class TestNoLegacyClaimFacadeCalls:
    """Legacy claim names never resurface as facade/repo attribute calls."""

    def test_no_legacy_claim_facade_calls_in_caller_code(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in LEGACY_CALLER_DIRS:
            violations.extend(_scan_dir(directory, CLAIM_FACADE_METHOD_PATTERN))
        assert len(violations) == 0, (
            "Callers must use the canonical claims intent facade (db.app.add_claim / "
            "remove_claim / remove_claims / list_claims / count_claims). Legacy claim "
            "persistence names (insert_worker_claim, claim_file, release_claim, "
            "release_claim_by_song, delete_claims*, steal_claim, aggregate_worker_claims, "
            "count_worker_claims, truncate_worker_claims, claim_song, "
            "try_insert_or_steal_claim, remove_claim_by_song) must not reappear as "
            "object-attribute calls above persistence (CONTRACTS.md).\n"
            f"{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestNoClaimStorageMechanicsInCallers:
    """WorkerClaimRow and encoded claim keys never appear in caller code."""

    def test_no_worker_claim_row_in_callers(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan_dir(directory, CLAIM_ROW_PATTERN))
        assert len(violations) == 0, (
            "WorkerClaimRow is a persistence-internal storage shape and must not be "
            "imported, referenced, or returned in components/services/workflows/"
            "interfaces (CONTRACTS.md).\n"
            f"{_format(violations)}"
        )

    def test_no_encoded_claim_key_in_callers(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan_dir(directory, CLAIM_KEY_ENCODING_PATTERN))
        assert len(violations) == 0, (
            "Encoded claim-key construction/parsing (claim_{song_id} / "
            "claim_{claim_type}_{song_id}) is owned solely by the persistence repo "
            "(app_repo.py); no higher layer may construct, parse, or compare these "
            "strings (CONTRACTS.md).\n"
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
