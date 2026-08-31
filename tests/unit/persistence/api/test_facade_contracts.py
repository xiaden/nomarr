# mypy: disable-error-code=func-returns-value
"""Facade contract tests for the sealed tag surface.

``TASK-song-intent-facade-correction-A`` Phase 6 (P6-S2): prove that the sealed
``LibraryTagsDb`` facade
- converts rows/dicts/IDs/edges to domain values internally (never leaking them),
- resolves the complete tag natural identity set-based (no per-row SQL loops),
- is safe when songs/libraries/tags are missing,
- exposes no transaction context (repositories own transactions / UoW), and
- preserves repository bulk / unit-of-work semantics (one set-based call per
  batch, not a per-identity loop).

The spec-first ``test_facade_domain_boundary.py`` (P2) and ``test_facade_identity_bridge.py``
(P3) pin the read results and the bridge; this module pins the *call* contracts
behind those results.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    RelinkResult,
    SongTagAssignment,
    TagCleanupResult,
    TagRef,
)
from nomarr.persistence.api.library_tags import LibraryTagsDb

_TEST_LIBRARY = LibraryIdentity(name="TestLib", root_path="/music")


def _song(normalized_path: str = "a.mp3") -> SongIdentity:
    return SongIdentity(library=_TEST_LIBRARY, normalized_path=normalized_path)


def _make_tags_db() -> tuple[LibraryTagsDb, MagicMock, MagicMock, MagicMock, MagicMock]:
    tag_repo = MagicMock()
    song_tag_repo = MagicMock()
    song_repo = MagicMock()
    library_repo = MagicMock()
    library_repo.get_library_by_natural_key.return_value = {"id": 1}
    library_repo.get_library_ids_by_natural_keys.return_value = {("TestLib", "/music"): 1}
    song_repo.get_song_by_normalized_path.return_value = {"id": 7}
    song_repo.get_song_ids_by_normalized_paths.return_value = {(1, "a.mp3"): 7}
    tags = LibraryTagsDb(
        session=MagicMock(),
        tag_repo=tag_repo,
        song_tag_repo=song_tag_repo,
        song_repo=song_repo,
        library_repo=library_repo,
    )
    return tags, tag_repo, song_tag_repo, song_repo, library_repo


@pytest.mark.unit
class TestCompleteTagRefResolved:
    def test_get_tag_matches_complete_identity_value(self) -> None:
        # get_tag resolves the full (name, value, namespace) natural key exactly.
        tags, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {("default", "artist", "X"): 11}
        tag_repo.get_tags_by_ids.return_value = [{"name": "artist", "value": "X", "namespace": ""}]
        assert tags.get_tag(TagRef(name="artist", value="X")) == TagRef("artist", "X")
        assert tags.get_tag(TagRef(name="artist", value="Z")) is None

    def test_get_tag_resolves_exact_value_for_shared_name_namespace(self) -> None:
        """get_tag returns the exact tag per value of a shared (name, namespace)."""
        tags, tag_repo, _, _, _ = _make_tags_db()
        rows = {
            11: {"name": "artist", "value": "X", "namespace": ""},
            12: {"name": "artist", "value": "Y", "namespace": ""},
        }
        tag_repo.get_tag_ids_by_identities.return_value = {
            ("default", "artist", "X"): 11,
            ("default", "artist", "Y"): 12,
        }
        tag_repo.get_tags_by_ids.side_effect = lambda ids: [rows[i] for i in ids]
        assert tags.get_tag(TagRef(name="artist", value="X")) == TagRef("artist", "X")
        assert tags.get_tag(TagRef(name="artist", value="Y")) == TagRef("artist", "Y")
        assert tags.get_tag(TagRef(name="artist", value="Z")) is None

    def test_ensure_tag_returns_identity_never_id(self) -> None:
        tags, tag_repo, _, _, _ = _make_tags_db()
        identity = TagRef(name="artist", value="X", namespace="nom")
        result = tags.ensure_tag(identity)
        assert result == identity
        tag_repo.get_or_create_tag.assert_called_once_with("artist", "X", "nom")


@pytest.mark.unit
class TestMissingTargetsAreSafe:
    def test_list_tags_for_song_empty_when_song_missing(self) -> None:
        tags, _, song_tag_repo, song_repo, library_repo = _make_tags_db()
        library_repo.get_library_by_natural_key.return_value = None
        assert tags.list_tags_for_song(_song()) == ()
        song_tag_repo.get_tags_for_song.assert_not_called()
        song_repo.get_song_by_normalized_path.assert_not_called()

    def test_list_tags_for_song_empty_when_song_resolves_but_no_tags(self) -> None:
        tags, _, song_tag_repo, _, _ = _make_tags_db()
        song_tag_repo.get_tags_for_song.return_value = []
        assert tags.list_tags_for_song(_song()) == ()

    def test_list_song_tags_for_songs_empty_when_no_songs_resolve(self) -> None:
        tags, _, song_tag_repo, _, library_repo = _make_tags_db()
        library_repo.get_library_ids_by_natural_keys.return_value = {}
        assert tags.list_song_tags_for_songs([_song("missing.mp3")]) == {}
        # No edge batch is fetched for unresolved songs.
        song_tag_repo.get_tags_for_songs_batch.assert_not_called()

    def test_list_genre_tags_empty_when_no_songs_resolve(self) -> None:
        tags, _, song_tag_repo, _, library_repo = _make_tags_db()
        library_repo.get_library_ids_by_natural_keys.return_value = {}
        assert tags.list_genre_tags_for_songs([_song()]) == ()
        song_tag_repo.get_genre_tags_for_songs.assert_not_called()

    def test_replace_song_tags_noop_when_song_missing(self) -> None:
        tags, tag_repo, song_tag_repo, song_repo, library_repo = _make_tags_db()
        library_repo.get_library_by_natural_key.return_value = None
        tags.replace_song_tags(_song(), [SongTagAssignment(name="artist", value="X")])
        song_tag_repo.replace_song_tags.assert_not_called()
        tag_repo.get_or_create_tags_batch.assert_not_called()
        song_repo.get_song_by_normalized_path.assert_not_called()

    def test_remove_song_tags_noop_when_song_missing(self) -> None:
        tags, _tag_repo, song_tag_repo, song_repo, library_repo = _make_tags_db()
        library_repo.get_library_by_natural_key.return_value = None
        tags.remove_song_tags(_song(), [TagRef(name="artist", value="X")])
        song_tag_repo.remove_tags_from_song.assert_not_called()
        song_tag_repo.replace_song_tags.assert_not_called()
        song_repo.get_song_by_normalized_path.assert_not_called()

    def test_get_tag_returns_none_when_tag_missing(self) -> None:
        tags, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {}
        assert tags.get_tag(TagRef(name="artist", value="X")) is None

    def test_relink_returns_zero_when_source_tag_missing(self) -> None:
        tags, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {}
        result = tags.relink_tags(
            TagRef("old", "A"),
            TagRef("new", "B"),
        )
        assert result == RelinkResult(moved=0, skipped=0, source_orphaned=0)
        song_tag_repo.relink_song_tags.assert_not_called()


@pytest.mark.unit
class TestSetBasedResolution:
    def test_replace_song_tags_resolves_all_tags_in_one_batch(self) -> None:
        tags, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        assignments = [
            SongTagAssignment(name="artist", value="X"),
            SongTagAssignment(name="genre", value="Jazz", namespace="nom"),
            SongTagAssignment(name="year", value=1999),
        ]
        tag_repo.get_or_create_tags_batch.return_value = {
            ("default", "artist", "X"): 1,
            ("nom", "genre", "Jazz"): 2,
            ("default", "year", "1999"): 3,
        }
        tags.replace_song_tags(_song(), assignments)
        # One set-based call for the whole batch — never a per-tag loop.
        tag_repo.get_or_create_tags_batch.assert_called_once()
        call_rows = tag_repo.get_or_create_tags_batch.call_args[0][0]
        assert len(call_rows) == 3
        assert {"namespace": "default", "name": "artist", "value": "X"} in call_rows
        # Edges reference the resolved tag ids + provenance.
        edges = song_tag_repo.replace_song_tags.call_args[0][1]
        assert len(edges) == 3
        assert {"song_id": 7, "tag_id": 1, "confidence": 1.0, "source": "nomarr"} in edges

    def test_remove_song_tags_resolves_identities_in_one_batch(self) -> None:
        tags, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {("default", "artist", "X"): 1}
        tags.remove_song_tags(_song(), [TagRef("artist", "X"), TagRef("missing", "Y")])
        # One set-based lookup; unresolved identities are skipped.
        tag_repo.get_tag_ids_by_identities.assert_called_once()
        song_tag_repo.remove_tags_from_song.assert_called_once_with(7, [1])

    def test_relink_resolves_songs_set_based(self) -> None:
        tags, tag_repo, song_tag_repo, song_repo, library_repo = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {("default", "old", "A"): 1}
        tag_repo.get_or_create_tags_batch.return_value = {("default", "new", "B"): 2}
        library_repo.get_library_ids_by_natural_keys.return_value = {("TestLib", "/music"): 1}
        song_repo.get_song_ids_by_normalized_paths.return_value = {(1, "a.mp3"): 7}
        song_tag_repo.relink_song_tags.return_value = {"moved": 2, "skipped": 1, "source_orphaned": 1}
        result = tags.relink_tags(
            TagRef("old", "A"),
            TagRef("new", "B"),
            songs=[_song()],
        )
        assert result == RelinkResult(moved=2, skipped=1, source_orphaned=1)
        # set-based: one batch song resolution query, one relink call
        song_repo.get_song_ids_by_normalized_paths.assert_called_once()
        song_tag_repo.relink_song_tags.assert_called_once_with(1, 2, song_ids=[7])


@pytest.mark.unit
class TestTypedResultsAndUoW:
    def test_cleanup_orphaned_tags_returns_domain_result(self) -> None:
        tags, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_orphaned_tag_ids.return_value = [3, 4]
        tag_repo.delete_tags_by_ids.return_value = 2
        result = tags.admin_cleanup_orphaned_tags()
        assert isinstance(result, TagCleanupResult)
        assert (result.deleted, result.orphaned) == (2, 2)

    def test_count_orphaned_tags_is_count_only_read_intent(self) -> None:
        """count_orphaned_tags returns a plain int and never deletes (dry_run)."""
        tags, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_orphaned_tag_ids.return_value = [3, 4]

        result = tags.count_orphaned_tags()

        assert result == 2
        assert isinstance(result, int)
        # non-destructive: no deletion, no storage-id/row/edge leak to caller
        tag_repo.delete_tags_by_ids.assert_not_called()

    def test_find_songs_with_tag_returns_domain_songs(self) -> None:
        tags, _, song_tag_repo, _, _ = _make_tags_db()
        song_tag_repo.search_songs_by_tag.return_value = [
            {
                "id": 10,
                "library_id": 1,
                "folder_id": None,
                "path": "/music/a.mp3",
                "normalized_path": "a.mp3",
                "file_size": 100,
                "modified_time": 1000,
                "duration_seconds": None,
                "chromaprint": None,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 1,
                "calibration_hash": None,
                "write_claimed_by": None,
                "last_tagged_at": None,
                "scanned_at": 1000,
                "created_at": 1000,
            }
        ]
        result = tags.find_songs_with_tag(TagRef("artist", "X"))
        assert isinstance(result[0], Song)
        assert not isinstance(result[0], dict)


@pytest.mark.unit
class TestNoFacadeTransactionContext:
    """AR-SDR-4: the sealed tag facade exposes no transaction context."""

    def test_tags_db_exposes_no_transaction_api(self) -> None:
        tags, _, _, _, _ = _make_tags_db()
        assert not hasattr(tags, "transaction")
        assert not hasattr(tags, "_require_transaction")
        assert not hasattr(tags, "begin_transaction")


@pytest.mark.unit
class TestIdempotenceAndEmptySemantics:
    """P6-S4 regression: replace/add/remove idempotence and empty semantics.

    A repeated ``replace_song_tags`` must produce identical edges, and an empty
    assignment list must replace all edges (no leftover edges).
    """

    def test_repeated_replace_produces_identical_edges(self) -> None:
        tags, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_or_create_tags_batch.return_value = {("default", "artist", "X"): 1}
        assignments = [SongTagAssignment(name="artist", value="X", confidence=0.9)]

        tags.replace_song_tags(_song(), assignments)
        tags.replace_song_tags(_song(), assignments)

        assert song_tag_repo.replace_song_tags.call_count == 2
        first_edges = song_tag_repo.replace_song_tags.call_args_list[0][0][1]
        second_edges = song_tag_repo.replace_song_tags.call_args_list[1][0][1]
        assert first_edges == second_edges
        assert first_edges == [{"song_id": 7, "tag_id": 1, "confidence": 0.9, "source": "nomarr"}]

    def test_empty_assignments_replace_all_edges(self) -> None:
        """Calling replace with no assignments removes every edge for the song."""
        tags, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_or_create_tags_batch.return_value = {}

        tags.replace_song_tags(_song(), [])

        song_tag_repo.replace_song_tags.assert_called_once_with(7, [])

    def test_remove_all_tags_uses_empty_edge_replacement(self) -> None:
        """remove_song_tags with no identities delegates to empty edge replacement."""
        tags, tag_repo, song_tag_repo, _, _ = _make_tags_db()

        tags.remove_song_tags(_song())

        song_tag_repo.replace_song_tags.assert_called_once_with(7, [])
        tag_repo.get_tag_ids_by_identities.assert_not_called()
