"""Tests for ``nomarr.components.library.library_song_state_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from nomarr.components.library.library_song_state_comp import (
    bulk_set_not_calibrated,
    bulk_set_not_hydrated,
    bulk_set_not_vectors_extracted,
    bulk_set_tags_not_fresh,
    count_errored_songs,
    count_untagged_files,
    discover_next_untagged_file,
    get_calibration_status_by_library,
    get_errored_song_ids,
    get_songs_with_incomplete_tags,
    get_stale_song_ids,
    get_uncalibrated_tagged_song_ids,
    initialize_song_states_batch,
    library_has_tagged_files,
    song_has_tagged_state,
    transition_song_state,
)
from nomarr.helpers.constants.file_states import (
    STATE_CALIBRATED,
    STATE_ERRORED,
    STATE_HYDRATED,
    STATE_NOT_CALIBRATED,
    STATE_NOT_ERRORED,
    STATE_NOT_HYDRATED,
    STATE_NOT_PROCESSED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_PROCESSED,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_VECTORS_EXTRACTED,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
from nomarr.helpers.dataclasses.worker_claim_dataclass import WorkerClaim, WorkerClaimIdentity


def _claim_identity(song_id: int) -> SongIdentity:
    """Build a natural song identity matching ``_song(song_id)``."""
    return SongIdentity(
        library=LibraryIdentity(name="Music", root_path="/music"),
        normalized_path=f"song{song_id}.mp3",
    )


def _claim(song_id: int) -> WorkerClaim:
    """Build an untyped domain claim on ``song_id``."""
    return WorkerClaim(
        identity=WorkerClaimIdentity(song=_claim_identity(song_id), worker_id="worker", claim_type=None),
        claimed_at_ms=0,
    )


def _song(**overrides: object) -> Song:
    """Build a minimal ``Song`` for mocking persistence-facade returns."""
    base: dict = {
        "song_id": 1,
        "library_id": 1,
        "folder_id": None,
        "path": "/music/song.mp3",
        "normalized_path": "song.mp3",
        "file_size": 100,
        "modified_time": 1000,
        "duration_seconds": None,
        "chromaprint": None,
        "needs_tagging": False,
        "is_valid": True,
        "tagged": False,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": None,
        "created_at": 1000,
    }
    base.update(overrides)
    return Song(**base)


def _library(**overrides: object) -> Library:
    """Build a minimal ``Library`` for mocking persistence-facade returns."""
    base: dict = {
        "name": "Music",
        "root_path": "/music",
        "is_enabled": True,
        "watch_mode": "off",
        "file_write_mode": "full",
        "library_auto_write": False,
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return Library(**base)


def _make_mock_db() -> MagicMock:
    """Build a ``MagicMock`` pre-wired to the current app/library facades.

    Song-state reads are served by ``app.songs_with_state`` (returning domain
    ``Song`` objects); membership by ``app.song_state_membership*``; transition
    by ``app.transition_song_states``; and claim/introspection by ``list_claims``
    / ``count_songs_with_state`` / ``song_ids_with_state``.
    """
    mock_db = MagicMock()
    mock_db.app.songs_with_state.return_value = []
    mock_db.app.count_songs_with_state.return_value = 0
    mock_db.app.song_state_membership.return_value = set()
    mock_db.app.song_state_memberships.return_value = {}
    mock_db.app.song_ids_with_state.return_value = []
    mock_db.app.list_claims.return_value = []
    mock_db.library.list_songs.return_value = []
    mock_db.library.list_libraries.return_value = []
    mock_db.library.list_song_tags_for_songs.return_value = {}
    mock_db.library.resolve_song_identities.return_value = {}
    return mock_db


class TestInitializeFileStatesBatchEmpty:
    """Empty-input guard for ``initialize_song_states_batch()``.

    The helper wires canonical negative-pole membership through the sealed
    ``app.initialize_song_states`` persistence intent, so the only component
    behavior worth pinning here is that an empty batch avoids a persistence
    call entirely.
    """

    @pytest.mark.unit
    def test_batch_empty_avoids_persistence_call(self) -> None:
        mock_db = _make_mock_db()

        initialize_song_states_batch(mock_db, [])

        mock_db.app.initialize_song_states.assert_not_called()


class TestSimpleStateLookups:
    """Tests for the simple constructor-backed state lookups."""

    @pytest.mark.unit
    def test_file_has_tagged_state_uses_state_membership(self) -> None:
        """A song is 'tagged' exactly when its membership contains ``processed``."""
        mock_db = _make_mock_db()
        mock_db.app.song_state_membership.return_value = {STATE_PROCESSED}

        result = song_has_tagged_state(mock_db, 1)

        assert result is True
        mock_db.app.song_state_membership.assert_called_once_with(1)

    @pytest.mark.unit
    def test_file_has_tagged_state_returns_false_when_not_processed(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.song_state_membership.return_value = {"calibrated"}

        result = song_has_tagged_state(mock_db, 1)

        assert result is False

    @pytest.mark.unit
    def test_library_has_tagged_files_intersects_tagged_and_library_membership(self) -> None:
        """Library is tagged when the processed set intersects its song ids."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1), _song(song_id=9)]
        mock_db.library.list_songs.return_value = [_song(song_id=2), _song(song_id=9)]

        result = library_has_tagged_files(mock_db, _library())

        assert result is True
        mock_db.app.songs_with_state.assert_called_once_with(STATE_PROCESSED)
        mock_db.library.list_songs.assert_called_once_with(_library())

    @pytest.mark.unit
    def test_library_has_tagged_files_returns_false_when_no_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1)]
        mock_db.library.list_songs.return_value = [_song(song_id=2)]

        result = library_has_tagged_files(mock_db, _library())

        assert result is False


class TestDiscoverNextUntaggedFile:
    """Tests for ``discover_next_untagged_file()``."""

    @pytest.mark.unit
    def test_returns_first_library_scoped_unclaimed_file_sorted_by_key(self) -> None:
        """Untagged candidates are errored- and library-filtered, claimed file
        ids excluded, and the lowest ``id`` wins."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.side_effect = [
            [_song(song_id=3), _song(song_id=1), _song(song_id=2)],  # not_processed
            [_song(song_id=2)],  # errored
            [],  # no further state reads
        ]
        mock_db.library.list_songs.return_value = [_song(song_id=1), _song(song_id=2), _song(song_id=3)]
        mock_db.app.list_claims.return_value = [_claim(3)]
        mock_db.library.resolve_song_identities.return_value = {
            1: _claim_identity(1),
            2: _claim_identity(2),
            3: _claim_identity(3),
        }

        result = discover_next_untagged_file(mock_db, library=_library())

        assert result == _song(song_id=1).to_dict()
        assert mock_db.app.songs_with_state.call_args_list == [
            call(STATE_NOT_PROCESSED),
            call(STATE_ERRORED),
        ]
        mock_db.app.list_claims.assert_called_once_with()

    @pytest.mark.unit
    def test_returns_none_when_no_candidates_survive_filters(self) -> None:
        """An errored-only candidate set yields no claimable file."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.side_effect = [
            [_song(song_id=1)],
            [_song(song_id=1)],  # same file is errored, so it is filtered out
            [],
        ]

        result = discover_next_untagged_file(mock_db)

        assert result is None

    @pytest.mark.unit
    def test_does_not_exclude_claimed_files_when_flag_is_false(self) -> None:
        """``exclude_claimed=False`` skips the claims lookup entirely."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.side_effect = [
            [_song(song_id=2), _song(song_id=1)],
            [
                # errored
            ],
        ]

        result = discover_next_untagged_file(mock_db, exclude_claimed=False)

        assert result == _song(song_id=1).to_dict()
        mock_db.app.list_claims.assert_not_called()


class TestLibraryScopedStateQueries:
    """Tests for library-scoped state query helpers."""

    @pytest.mark.unit
    def test_count_untagged_files_intersects_library_membership(self) -> None:
        """Untagged count is the not-processed set intersected with the library."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1), _song(song_id=2), _song(song_id=3)]
        mock_db.library.list_songs.return_value = [_song(song_id=2), _song(song_id=3)]

        result = count_untagged_files(mock_db, library=_library())

        assert result == 2
        mock_db.app.songs_with_state.assert_called_once_with(STATE_NOT_PROCESSED)
        mock_db.library.list_songs.assert_called_once_with(_library())

    @pytest.mark.unit
    def test_count_untagged_files_returns_global_count_when_no_library_id(self) -> None:
        """Without a library the count is purely the not-processed set size."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1), _song(song_id=2), _song(song_id=3)]

        result = count_untagged_files(mock_db)

        assert result == 3
        mock_db.library.list_songs.assert_not_called()

    @pytest.mark.unit
    def test_get_errored_song_ids_normalizes_library_id_and_applies_limit_after_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs.return_value = [_song(song_id=2), _song(song_id=3)]
        mock_db.app.songs_with_state.return_value = [_song(song_id=9), _song(song_id=2), _song(song_id=3)]

        result = get_errored_song_ids(mock_db, _library(), limit=1)

        assert result == [2]
        mock_db.library.list_songs.assert_called_once_with(_library())
        mock_db.app.songs_with_state.assert_called_once_with(STATE_ERRORED)

    @pytest.mark.unit
    def test_count_errored_files_counts_full_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs.return_value = [_song(song_id=2), _song(song_id=3)]
        mock_db.app.songs_with_state.return_value = [_song(song_id=2), _song(song_id=3)]

        result = count_errored_songs(mock_db, _library())

        assert result == 2

    @pytest.mark.unit
    def test_get_errored_song_ids_returns_all_when_limit_is_none(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs.return_value = [_song(song_id=1), _song(song_id=2), _song(song_id=3)]
        mock_db.app.songs_with_state.return_value = [_song(song_id=1), _song(song_id=2), _song(song_id=3)]

        result = get_errored_song_ids(mock_db, _library(), limit=None)

        assert result == [1, 2, 3]

    @pytest.mark.unit
    def test_get_stale_song_ids_scopes_to_library_membership(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1), _song(song_id=2)]
        mock_db.library.list_songs.return_value = [_song(song_id=2)]

        result = get_stale_song_ids(mock_db, library=_library())

        assert result == [2]
        mock_db.app.songs_with_state.assert_called_once_with(STATE_TAGS_NOT_FRESH)
        mock_db.library.list_songs.assert_called_once_with(_library())

    @pytest.mark.unit
    def test_get_stale_song_ids_returns_all_ids_when_no_library_id(self) -> None:
        """Stale ids with no library scope are the full tags-not-fresh set."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1), _song(song_id=2)]

        result = get_stale_song_ids(mock_db)

        assert result == [1, 2]
        mock_db.library.list_songs.assert_not_called()

    @pytest.mark.unit
    def test_get_stale_song_ids_projects_song_objects_to_ids(self) -> None:
        """The stale read is served by ``songs_with_state`` and each ``Song``
        ``to_dict()``/``id`` projection yields its song id."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1), _song(song_id=4)]

        result = get_stale_song_ids(mock_db)

        assert result == [1, 4]
        mock_db.app.songs_with_state.assert_called_once_with(STATE_TAGS_NOT_FRESH)


class TestMultiStateComposition:
    """Tests for multi-state composition helpers."""

    @pytest.mark.unit
    def test_get_uncalibrated_tagged_song_ids_intersects_state_sets_in_library_order(self) -> None:
        """Tagged-but-uncalibrated ids are intersected and returned in library order."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.side_effect = [
            [_song(song_id=1), _song(song_id=3)],  # processed
            [_song(song_id=2), _song(song_id=3)],  # not_calibrated
        ]
        mock_db.library.list_songs.return_value = [_song(song_id=2), _song(song_id=3), _song(song_id=1)]

        result = get_uncalibrated_tagged_song_ids(mock_db, _library())

        assert result == [3]

    @pytest.mark.unit
    def test_get_calibration_status_by_library_counts_intersections_per_library(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.side_effect = [
            [_song(song_id=1), _song(song_id=2)],  # calibrated
            [_song(song_id=3), _song(song_id=4)],  # not_calibrated
        ]
        mock_db.library.list_libraries.return_value = [_library(name="A"), _library(name="B")]
        mock_db.library.list_songs.side_effect = [
            [_song(song_id=1), _song(song_id=3)],
            [_song(song_id=2), _song(song_id=4)],
        ]

        result = get_calibration_status_by_library(mock_db)

        assert result == [
            {"library_id": "A", "calibrated_count": 1, "not_calibrated_count": 1},
            {"library_id": "B", "calibrated_count": 1, "not_calibrated_count": 1},
        ]
        mock_db.library.list_libraries.assert_called_once_with()

    @pytest.mark.unit
    def test_get_calibration_status_by_library_returns_empty_list_when_no_libraries(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = []
        mock_db.library.list_libraries.return_value = []

        result = get_calibration_status_by_library(mock_db)

        assert result == []
        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.library.list_songs.assert_not_called()


class TestIncompleteTags:
    """Tests for ``get_songs_with_incomplete_tags()``."""

    @staticmethod
    def _identity(song_id: int) -> SongIdentity:
        return SongIdentity(
            library=LibraryIdentity(name="Music", root_path="/music"),
            normalized_path=f"song{song_id}.mp3",
        )

    @staticmethod
    def _assignment(name: str) -> SongTagAssignment:
        return SongTagAssignment(name=name, value="x", namespace="nom")

    @pytest.mark.unit
    def test_preserves_head_matching_logic_for_matching_and_missing_heads(self) -> None:
        mock_db = _make_mock_db()
        expected_heads = [
            {"head_key": "mood", "labels": ["mood"], "model_key_for_tag": "modelA"},
            {"head_key": "energy", "labels": ["energy"], "model_key_for_tag": "modelB"},
        ]
        identity = self._identity(1)
        mock_db.app.songs_with_state.return_value = [_song(song_id=1)]
        mock_db.library.resolve_song_identities.return_value = {1: identity}
        mock_db.library.list_song_tags_for_songs.return_value = {
            identity: (
                self._assignment("nom:mood_modelA_happy"),
                self._assignment("nom:energy_modelB_high"),
                self._assignment("nom:energy_other_model"),
            )
        }

        result = get_songs_with_incomplete_tags(mock_db, expected_heads, namespace_prefix="nom:")

        assert result == [
            {
                "file_id": 1,
                "file_key": 1,
                "library_id": None,
                "matched_count": 2,
                "missing_count": 0,
                "missing_heads": [],
            }
        ]
        mock_db.app.songs_with_state.assert_called_once_with(STATE_WRITTEN)
        mock_db.library.resolve_song_identities.assert_called_once_with([1])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with(
            [identity],
            name_starts_with="nom:",
        )

    @pytest.mark.unit
    def test_scopes_incomplete_tag_results_to_library_and_returns_normalized_library_id(self) -> None:
        mock_db = _make_mock_db()
        expected_heads = [
            {"head_key": "mood", "labels": ["mood"], "model_key_for_tag": "modelA"},
            {"head_key": "energy", "labels": ["energy"], "model_key_for_tag": "modelB"},
        ]
        identity = self._identity(2)
        mock_db.app.songs_with_state.return_value = [
            _song(song_id=1),
            _song(song_id=2),
        ]
        mock_db.library.list_songs.return_value = [_song(song_id=2)]
        mock_db.library.resolve_song_identities.return_value = {2: identity}
        mock_db.library.list_song_tags_for_songs.return_value = {identity: (self._assignment("nom:mood_modelA_happy"),)}

        result = get_songs_with_incomplete_tags(mock_db, expected_heads, namespace_prefix="nom:", library=_library())

        assert result == [
            {
                "file_id": 2,
                "file_key": 2,
                "library_id": _library(),
                "matched_count": 1,
                "missing_count": 1,
                "missing_heads": ["energy"],
            }
        ]
        mock_db.library.list_songs.assert_called_once_with(_library())
        mock_db.library.resolve_song_identities.assert_called_once_with([2])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with(
            [identity],
            name_starts_with="nom:",
        )

    @pytest.mark.unit
    def test_empty_song_ids_returns_empty_without_calling_tag_facade(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = []

        result = get_songs_with_incomplete_tags(mock_db, [], namespace_prefix="nom:")

        assert result == []
        mock_db.library.resolve_song_identities.assert_not_called()
        mock_db.library.list_song_tags_for_songs.assert_not_called()

    @pytest.mark.unit
    def test_unresolved_identities_return_empty_mapping_without_calling_tag_facade(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1)]
        mock_db.library.resolve_song_identities.return_value = {}

        result = get_songs_with_incomplete_tags(mock_db, [], namespace_prefix="nom:")

        assert result == [
            {
                "file_id": 1,
                "file_key": 1,
                "library_id": None,
                "matched_count": 0,
                "missing_count": 0,
                "missing_heads": [],
            }
        ]
        mock_db.library.resolve_song_identities.assert_called_once_with([1])
        mock_db.library.list_song_tags_for_songs.assert_not_called()


class TestTransitionFileState:
    """Tests for ``transition_song_state()``."""

    @pytest.mark.unit
    def test_delegates_valid_axis_pair_to_app_facade(self) -> None:
        """A valid axis pair is forwarded (deduplicated) to the sealed transition."""
        mock_db = _make_mock_db()

        transition_song_state(mock_db, [1, 2], STATE_NOT_PROCESSED, STATE_PROCESSED)

        mock_db.app.transition_song_states.assert_called_once_with([1, 2], STATE_NOT_PROCESSED, STATE_PROCESSED)

    @pytest.mark.unit
    def test_deduplicates_repeated_song_ids(self) -> None:
        """Repeated ids are collapsed before reaching the persistence intent."""
        mock_db = _make_mock_db()

        transition_song_state(mock_db, [1, 1, 2], STATE_NOT_HYDRATED, STATE_HYDRATED)

        mock_db.app.transition_song_states.assert_called_once_with([1, 2], STATE_NOT_HYDRATED, STATE_HYDRATED)

    @pytest.mark.unit
    def test_raises_value_error_for_invalid_axis_pair_without_touching_facade(self) -> None:
        """Cross-axis pairs (e.g. not_processed -> calibrated) are rejected before
        any persistence call, so other-axis membership is never consulted."""
        mock_db = _make_mock_db()

        with pytest.raises(ValueError):
            transition_song_state(mock_db, [1], STATE_NOT_PROCESSED, STATE_CALIBRATED)

        mock_db.app.transition_song_states.assert_not_called()


class TestBulkTransitions:
    """Tests for the bulk state transition helpers."""

    @pytest.mark.unit
    def test_bulk_set_not_hydrated_repairs_missing_hydration_and_error_edges(self) -> None:
        """Not-hydrated repair transitions hydrated -> not_hydrated, sets a
        not_hydrated edge for files with no hydration edge, and recovers
        errored files back to not-errored."""
        mock_db = _make_mock_db()
        mock_db.library.list_libraries.return_value = [_library()]
        mock_db.library.list_songs.return_value = [_song(song_id=7)]
        mock_db.app.songs_with_state.side_effect = lambda state: [_song(song_id=7)] if state == STATE_ERRORED else []

        result = bulk_set_not_hydrated(mock_db)

        assert result == 1
        mock_db.app.set_song_state.assert_called_once_with([7], STATE_NOT_HYDRATED)
        mock_db.app.transition_song_states.assert_called_once_with([7], STATE_ERRORED, STATE_NOT_ERRORED)

    @pytest.mark.unit
    def test_bulk_set_not_calibrated_transitions_all_calibrated_files(self) -> None:
        """All calibrated files are moved to not_calibrated via the sealed intent."""
        mock_db = _make_mock_db()
        calibrated_ids = [1, 2]
        mock_db.app.songs_with_state.return_value = [_song(song_id=sid) for sid in calibrated_ids]

        result = bulk_set_not_calibrated(mock_db)

        assert result == 2
        mock_db.app.transition_song_states.assert_called_once_with(
            calibrated_ids, STATE_CALIBRATED, STATE_NOT_CALIBRATED
        )

    @pytest.mark.unit
    def test_bulk_set_not_calibrated_returns_zero_and_skips_transition_when_no_calibrated_files(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = []

        result = bulk_set_not_calibrated(mock_db)

        assert result == 0
        mock_db.app.transition_song_states.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_tags_not_fresh_filters_to_library_before_transition(self) -> None:
        """Only library members among tags-current files are transitioned."""
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = [_song(song_id=1), _song(song_id=2)]
        mock_db.library.list_songs.return_value = [_song(song_id=2)]

        result = bulk_set_tags_not_fresh(mock_db, library=_library())

        assert result == 1
        mock_db.app.transition_song_states.assert_called_once_with([2], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH)
        mock_db.app.songs_with_state.assert_called_once_with(STATE_TAGS_CURRENT)
        mock_db.library.list_songs.assert_called_once_with(_library())

    @pytest.mark.unit
    def test_bulk_set_tags_not_fresh_transitions_all_tags_current_files_when_no_library_id(self) -> None:
        mock_db = _make_mock_db()
        current_ids = [1, 2]
        mock_db.app.songs_with_state.return_value = [_song(song_id=sid) for sid in current_ids]

        result = bulk_set_tags_not_fresh(mock_db)

        assert result == 2
        mock_db.app.transition_song_states.assert_called_once_with(
            current_ids, STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH
        )
        mock_db.library.list_songs.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_tags_not_fresh_returns_zero_and_skips_transition_when_no_tags_current_files(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = []

        result = bulk_set_tags_not_fresh(mock_db)

        assert result == 0
        mock_db.app.transition_song_states.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_not_vectors_extracted_transitions_all_vector_extracted_files(self) -> None:
        mock_db = _make_mock_db()
        vector_ids = [7]
        mock_db.app.songs_with_state.return_value = [_song(song_id=sid) for sid in vector_ids]

        result = bulk_set_not_vectors_extracted(mock_db)

        assert result == 1
        mock_db.app.transition_song_states.assert_called_once_with(
            vector_ids, STATE_VECTORS_EXTRACTED, STATE_NOT_VECTORS_EXTRACTED
        )

    @pytest.mark.unit
    def test_bulk_set_not_vectors_extracted_skips_empty_transition(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.songs_with_state.return_value = []

        result = bulk_set_not_vectors_extracted(mock_db)

        assert result == 0
        mock_db.app.transition_song_states.assert_not_called()
