"""Regression coverage for the sealed song-tag facade (P6-S4).

Proves replace/add/remove idempotence, duplicate-safe relink and orphan/provenance
cleanup, numeric/tag searches returning domain values, and batched statistics —
all expressed against the ``TagRef``/``SongIdentity``/``SongTagAssignment``
domain surface of ``LibraryTagsDb`` (no raw rows, no integer tag ids, no
deleted legacy method names).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_dataclass import SongTagMatch
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    RelinkResult,
    SongTagAssignment,
    TagCleanupResult,
    TagRef,
    TagUsage,
)
from nomarr.persistence.api.library import LibraryDb
from nomarr.persistence.api.library_tags import LibraryTagsDb

_LIBRARY = LibraryIdentity(name="TestLib", root_path="/music")


def _song(path: str = "a.mp3") -> SongIdentity:
    return SongIdentity(library=_LIBRARY, normalized_path=path)


def _tag(name: str = "artist", value: str = "X", namespace: str = "") -> TagRef:
    return TagRef(name=name, value=value, namespace=namespace)


def _assignment(
    name: str = "artist", value: str = "X", namespace: str = "", confidence: float = 1.0
) -> SongTagAssignment:
    return SongTagAssignment(
        name=name, value=value, namespace=namespace, confidence=confidence, source="nomarr", song=_song()
    )


def _make_tags_db() -> tuple[LibraryTagsDb, MagicMock, MagicMock, MagicMock, MagicMock]:
    tag_repo = MagicMock()
    song_tag_repo = MagicMock()
    song_repo = MagicMock()
    library_repo = MagicMock()
    library_repo.get_library_by_natural_key.return_value = {"id": 1}
    library_repo.get_library_ids_by_natural_keys.return_value = {(_LIBRARY.name, _LIBRARY.root_path): 1}
    song_repo.get_song_by_normalized_path.return_value = {"id": 7}
    song_repo.get_song_ids_by_normalized_paths.return_value = {(1, "a.mp3"): 7}
    db = LibraryTagsDb(
        session=MagicMock(),
        tag_repo=tag_repo,
        song_tag_repo=song_tag_repo,
        song_repo=song_repo,
        library_repo=library_repo,
    )
    return db, tag_repo, song_tag_repo, song_repo, library_repo


@pytest.mark.unit
class TestReplaceIdempotence:
    def test_replace_song_tags_is_deterministic(self) -> None:
        db, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_or_create_tags_batch.return_value = {("default", "artist", "X"): 5}
        assignments = [_assignment()]
        expected = [{"song_id": 7, "tag_id": 5, "confidence": 1.0, "source": "nomarr"}]

        db.replace_song_tags(_song(), assignments)
        db.replace_song_tags(_song(), assignments)

        # Same assignment set twice → identical single batch resolve + edge replace.
        assert tag_repo.get_or_create_tags_batch.call_count == 2
        song_tag_repo.replace_song_tags.assert_called_with(7, expected)
        assert song_tag_repo.replace_song_tags.call_count == 2

    def test_replace_song_tags_resolves_set_based_no_per_tag_loop(self) -> None:
        db, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_or_create_tags_batch.return_value = {
            ("default", "artist", "X"): 5,
            ("default", "genre", "Rock"): 6,
        }

        db.replace_song_tags(
            _song(),
            [_assignment(), _assignment(name="genre", value="Rock")],
        )

        tag_repo.get_or_create_tags_batch.assert_called_once_with(
            [
                {"namespace": "default", "name": "artist", "value": "X"},
                {"namespace": "default", "name": "genre", "value": "Rock"},
            ]
        )
        song_tag_repo.replace_song_tags.assert_called_once()

    def test_replace_song_tags_missing_song_is_noop(self) -> None:
        db, _, song_tag_repo, song_repo, _ = _make_tags_db()
        song_repo.get_song_by_normalized_path.return_value = None

        db.replace_song_tags(_song(), [_assignment()])

        song_tag_repo.replace_song_tags.assert_not_called()


@pytest.mark.unit
class TestRelinkDuplicateSafe:
    def test_maps_moved_skipped_orphaned_counts(self) -> None:
        db, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {("default", "old", "A"): 1}
        tag_repo.get_or_create_tags_batch.return_value = {("default", "new", "B"): 2}
        song_tag_repo.relink_song_tags.return_value = {"moved": 3, "skipped": 2, "source_orphaned": 1}

        result = db.relink_tags(_tag("old", "A"), _tag("new", "B"))

        assert result == RelinkResult(moved=3, skipped=2, source_orphaned=1)
        assert isinstance(result, RelinkResult)
        song_tag_repo.relink_song_tags.assert_called_once_with(1, 2, song_ids=None)

    def test_scoped_relink_resolves_song_ids(self) -> None:
        db, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {("default", "old", "A"): 1}
        tag_repo.get_or_create_tags_batch.return_value = {("default", "new", "B"): 2}
        song_tag_repo.relink_song_tags.return_value = {"moved": 1, "skipped": 0, "source_orphaned": 0}

        db.relink_tags(_tag("old", "A"), _tag("new", "B"), songs=[_song()])

        song_tag_repo.relink_song_tags.assert_called_once_with(1, 2, song_ids=[7])

    def test_missing_source_returns_zero_result_and_no_creates(self) -> None:
        db, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {}

        result = db.relink_tags(_tag("old", "A"), _tag("new", "B"))

        assert result == RelinkResult(moved=0, skipped=0, source_orphaned=0)
        tag_repo.get_or_create_tags_batch.assert_not_called()
        song_tag_repo.relink_song_tags.assert_not_called()


@pytest.mark.unit
class TestRemoveAndOrphanCleanup:
    def test_remove_all_cleans_orphans_and_replaces_with_empty(self) -> None:
        db, tag_repo, song_tag_repo, _, _ = _make_tags_db()

        db.remove_song_tags(_song())

        song_tag_repo.replace_song_tags.assert_called_once_with(7, [])
        tag_repo.cleanup_orphaned_tags.assert_called_once_with()

    def test_remove_specific_identities_resolves_and_cleans(self) -> None:
        db, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {("default", "artist", "X"): 5}

        db.remove_song_tags(_song(), [_tag()])

        song_tag_repo.remove_tags_from_song.assert_called_once_with(7, [5])
        tag_repo.cleanup_orphaned_tags.assert_called_once_with()

    def test_remove_specific_unresolved_skips_edge_but_cleans(self) -> None:
        db, tag_repo, song_tag_repo, _, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {}

        db.remove_song_tags(_song(), [_tag()])

        song_tag_repo.remove_tags_from_song.assert_not_called()
        tag_repo.cleanup_orphaned_tags.assert_called_once_with()

    def test_cleanup_orphaned_tags_reports_typed_counts(self) -> None:
        db, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_orphaned_tag_ids.return_value = [1, 2, 3]
        tag_repo.delete_tags_by_ids.return_value = 3

        result = db.admin_cleanup_orphaned_tags()

        assert isinstance(result, TagCleanupResult)
        assert (result.deleted, result.orphaned) == (3, 3)
        tag_repo.delete_tags_by_ids.assert_called_once_with([1, 2, 3])

    def test_cleanup_no_orphans_skips_delete(self) -> None:
        db, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_orphaned_tag_ids.return_value = []

        result = db.admin_cleanup_orphaned_tags()

        assert result == TagCleanupResult(deleted=0, orphaned=0)
        tag_repo.delete_tags_by_ids.assert_not_called()


@pytest.mark.unit
class TestCountOrphanedTags:
    """Count-only orphan-discovery read intent (dry_run preview)."""

    def test_returns_scalar_count(self) -> None:
        db, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_orphaned_tag_ids.return_value = [1, 2, 3]

        result = db.count_orphaned_tags()

        assert result == 3
        assert isinstance(result, int)
        # count-only: discovers orphans but never deletes
        tag_repo.delete_tags_by_ids.assert_not_called()

    def test_zero_when_no_orphans(self) -> None:
        db, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_orphaned_tag_ids.return_value = []

        assert db.count_orphaned_tags() == 0
        tag_repo.delete_tags_by_ids.assert_not_called()

    def test_never_deletes_any_tag(self) -> None:
        db, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_orphaned_tag_ids.return_value = [7]

        db.count_orphaned_tags()

        tag_repo.delete_tags_by_ids.assert_not_called()


@pytest.mark.unit
class TestLibraryDbCountForwarder:
    """``LibraryDb.count_orphaned_tags`` mirrors the sub-facade exactly."""

    def test_forwards_count_only_and_never_deletes(self) -> None:
        tags = MagicMock(spec=LibraryTagsDb)
        tags.count_orphaned_tags.return_value = 4
        library = LibraryDb(
            session=MagicMock(),
            songs=MagicMock(),
            tags=tags,
            scans=MagicMock(),
            regions=MagicMock(),
        )

        result = library.count_orphaned_tags()

        assert result == 4
        tags.count_orphaned_tags.assert_called_once_with()
        tags.admin_cleanup_orphaned_tags.assert_not_called()


@pytest.mark.unit
class TestSearchesAndStatistics:
    def test_find_songs_with_numeric_tag_returns_domain_matches(self) -> None:
        db, _, song_tag_repo, _, _ = _make_tags_db()
        song_tag_repo.search_songs_by_numeric_tag.return_value = [
            {
                "id": 7,
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
                "matched_tag": "118.0",
                "distance": 2.0,
            }
        ]

        result = db.find_songs_with_numeric_tag(_tag("nom:bpm", "118"), limit=5)

        assert len(result) == 1
        assert isinstance(result[0], SongTagMatch)
        assert result[0].matched_tag == "118.0"
        assert result[0].distance == 2.0
        song_tag_repo.search_songs_by_numeric_tag.assert_called_once_with(
            "nom:bpm", "118", namespace="default", limit=5, offset=0
        )

    def test_list_tags_returns_domain_identities(self) -> None:
        db, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.list_tags.return_value = [{"id": 1, "name": "genre", "value": "Rock", "namespace": ""}]

        result = db.list_tags(name="genre")

        assert result == (_tag("genre", "Rock"),)
        assert isinstance(result[0], TagRef)
        tag_repo.list_tags.assert_called_once_with(name="genre", search=None, limit=None, offset=0)

    def test_list_tags_with_song_count_returns_usage(self) -> None:
        db, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.list_tags_with_song_count.return_value = [
            {"id": 1, "name": "genre", "value": "Rock", "namespace": "", "song_count": 4}
        ]

        result = db.list_tags_with_song_count(name="genre")

        assert result == (TagUsage(identity=_tag("genre", "Rock"), song_count=4),)
        assert isinstance(result[0], TagUsage)

    def test_list_tag_value_frequencies_batched(self) -> None:
        db, tag_repo, _, _, _ = _make_tags_db()
        tag_repo.get_tag_value_frequencies_batch.return_value = {
            "genre": [("default", "Rock", 10), ("default", "Pop", 5)]
        }

        result = db.list_tag_value_frequencies(["genre"], limit=100)

        # The facade reduces the namespace-bearing repo result to (value, count).
        assert result == {"genre": [("Rock", 10), ("Pop", 5)]}
        tag_repo.get_tag_value_frequencies_batch.assert_called_once_with(["genre"], limit=100)
