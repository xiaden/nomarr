"""Tests for ``nomarr.components.library.library_song_state_comp``.

Every state read/write is exercised through the typed locator boundary:
``db.library.list_songs_with_state(...) -> list[SongStateCandidate]``,
``db.app.song_state_membership(s)``, ``db.app.transition_song_states``,
``db.app.set_song_state`` and ``db.app.initialize_song_states``. No test
pins a generated ``songs.id``, a raw row/dict ``Song``, or a resolver.
"""

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
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
from nomarr.helpers.dataclasses.worker_claim_dataclass import WorkerClaim, WorkerClaimIdentity

LIBRARY_UUID = "6313b0d3-d270-57a8-9e0d-21e8255107e3"


def _library(name: str = "Music", root_path: str = "/music", **overrides: object) -> Library:
    """Build a persisted ``Library`` carrying its immutable ``library_uuid``."""
    base: dict = {"name": name, "root_path": root_path, "library_uuid": LIBRARY_UUID}
    base.update(overrides)
    return Library(**base)


def _lib_identity(library: Library | None = None) -> LibraryIdentity:
    """Return the ``LibraryIdentity`` a state read scopes by."""
    lib = library or _library()
    return LibraryIdentity(lib.library_uuid, lib.name, lib.root_path)


def _song(normalized_path: str = "song.mp3", **overrides: object) -> Song:
    """Build a minimal semantic ``Song`` (no generated id/library_id/folder_id)."""
    base: dict = {
        "path": f"/music/{normalized_path}",
        "normalized_path": normalized_path,
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


def _candidate(
    normalized_path: str = "song.mp3",
    *,
    library: Library | None = None,
    states: tuple[str, ...] = ("hydrated", "processed"),
) -> SongStateCandidate:
    """Build a typed ``SongStateCandidate`` whose locator and song agree on path."""
    lib = library or _library()
    song = _song(normalized_path)
    return SongStateCandidate(
        identity=SongIdentity(library=_lib_identity(lib), normalized_path=song.normalized_path),
        song=song,
        states=tuple(sorted(set(states))),
    )


def _claim(normalized_path: str) -> WorkerClaim:
    """Build an untyped domain claim addressed by a semantic locator."""
    return WorkerClaim(
        identity=WorkerClaimIdentity(
            song=SongIdentity(library=_lib_identity(), normalized_path=normalized_path),
            worker_id="worker",
            claim_type=None,
        ),
        claimed_at_ms=0,
    )


def _make_mock_db() -> MagicMock:
    """Wire a ``MagicMock`` to the typed state-read/intent boundaries."""
    mock_db = MagicMock()
    mock_db.library.list_songs_with_state.return_value = []
    mock_db.library.list_songs.return_value = []
    mock_db.library.list_libraries.return_value = []
    mock_db.library.list_song_tags_for_songs.return_value = {}
    mock_db.app.song_state_membership.return_value = set()
    mock_db.app.song_state_memberships.return_value = {}
    mock_db.app.list_claims.return_value = []
    mock_db.app.count_songs_with_state.return_value = 0
    return mock_db


class TestInitializeFileStatesBatchEmpty:
    """Empty-input guard for ``initialize_song_states_batch()``."""

    @pytest.mark.unit
    def test_batch_empty_avoids_persistence_call(self) -> None:
        mock_db = _make_mock_db()

        initialize_song_states_batch(mock_db, [])

        mock_db.app.initialize_song_states.assert_not_called()


class TestSimpleStateLookups:
    """Tests for the simple constructor-backed state lookups."""

    @pytest.mark.unit
    def test_song_has_tagged_state_uses_locator_membership(self) -> None:
        """A song is 'tagged' exactly when its membership contains ``processed``."""
        mock_db = _make_mock_db()
        identity = _candidate().identity
        mock_db.app.song_state_membership.return_value = {STATE_PROCESSED}

        result = song_has_tagged_state(mock_db, identity)

        assert result is True
        mock_db.app.song_state_membership.assert_called_once_with(identity)

    @pytest.mark.unit
    def test_song_has_tagged_state_returns_false_when_not_processed(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.song_state_membership.return_value = {STATE_CALIBRATED}

        result = song_has_tagged_state(mock_db, _candidate().identity)

        assert result is False

    @pytest.mark.unit
    def test_library_has_tagged_files_uses_scoped_typed_read(self) -> None:
        """Library is tagged when its scoped ``processed`` candidate list is non-empty."""
        mock_db = _make_mock_db()
        library = _library()
        mock_db.library.list_songs_with_state.return_value = [_candidate("song.mp3", library=library)]

        result = library_has_tagged_files(mock_db, library)

        assert result is True
        mock_db.library.list_songs_with_state.assert_called_once_with(STATE_PROCESSED, library=_lib_identity(library))

    @pytest.mark.unit
    def test_library_has_tagged_files_returns_false_when_empty(self) -> None:
        mock_db = _make_mock_db()

        result = library_has_tagged_files(mock_db, _library())

        assert result is False


class TestDiscoverNextUntaggedFile:
    """Tests for ``discover_next_untagged_file()``."""

    @pytest.mark.unit
    def test_excludes_errored_and_claimed_candidates(self) -> None:
        """Candidates are errored-filtered, claim-filtered, and returned in facade order."""
        mock_db = _make_mock_db()
        library = _library()
        candidates = [_candidate("c.mp3", library=library), _candidate("a.mp3", library=library)]
        mock_db.library.list_songs_with_state.side_effect = [candidates, [_candidate("b.mp3", library=library)]]
        mock_db.app.list_claims.return_value = [_claim("a.mp3")]

        result = discover_next_untagged_file(mock_db, library=library)

        assert result == candidates[0]
        assert mock_db.library.list_songs_with_state.call_args_list == [
            call(STATE_NOT_PROCESSED, library=_lib_identity(library)),
            call(STATE_ERRORED, library=_lib_identity(library)),
        ]
        mock_db.app.list_claims.assert_called_once_with()

    @pytest.mark.unit
    def test_returns_none_when_no_candidates_survive_filters(self) -> None:
        """An errored-only candidate set yields no claimable candidate."""
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.side_effect = [
            [_candidate("a.mp3")],
            [_candidate("a.mp3")],  # same candidate is errored, so it is filtered out
        ]

        result = discover_next_untagged_file(mock_db)

        assert result is None

    @pytest.mark.unit
    def test_does_not_exclude_claimed_files_when_flag_is_false(self) -> None:
        """``exclude_claimed=False`` skips the claims lookup entirely."""
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.side_effect = [[_candidate("a.mp3")], []]

        result = discover_next_untagged_file(mock_db, exclude_claimed=False)

        assert result == _candidate("a.mp3")
        mock_db.app.list_claims.assert_not_called()


class TestLibraryScopedStateQueries:
    """Tests for library-scoped state query helpers."""

    @pytest.mark.unit
    def test_count_untagged_files_uses_scoped_typed_read(self) -> None:
        mock_db = _make_mock_db()
        library = _library()
        mock_db.library.list_songs_with_state.return_value = [_candidate("a.mp3"), _candidate("b.mp3")]

        result = count_untagged_files(mock_db, library=library)

        assert result == 2
        mock_db.library.list_songs_with_state.assert_called_once_with(
            STATE_NOT_PROCESSED, library=_lib_identity(library)
        )

    @pytest.mark.unit
    def test_count_untagged_files_returns_global_count_without_library(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.return_value = [
            _candidate("a.mp3"),
            _candidate("b.mp3"),
            _candidate("c.mp3"),
        ]

        result = count_untagged_files(mock_db)

        assert result == 3
        mock_db.library.list_songs_with_state.assert_called_once_with(STATE_NOT_PROCESSED, library=None)

    @pytest.mark.unit
    def test_get_errored_song_ids_applies_limit_after_scoped_read(self) -> None:
        mock_db = _make_mock_db()
        library = _library()
        candidates = [_candidate("a.mp3"), _candidate("b.mp3"), _candidate("c.mp3")]
        mock_db.library.list_songs_with_state.return_value = candidates

        result = get_errored_song_ids(mock_db, library, limit=1)

        assert result == [candidates[0].identity]
        mock_db.library.list_songs_with_state.assert_called_once_with(STATE_ERRORED, library=_lib_identity(library))

    @pytest.mark.unit
    def test_count_errored_songs_counts_full_scoped_read(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.return_value = [_candidate("a.mp3"), _candidate("b.mp3")]

        result = count_errored_songs(mock_db, _library())

        assert result == 2

    @pytest.mark.unit
    def test_get_errored_song_ids_returns_all_when_limit_is_none(self) -> None:
        mock_db = _make_mock_db()
        candidates = [_candidate("a.mp3"), _candidate("b.mp3"), _candidate("c.mp3")]
        mock_db.library.list_songs_with_state.return_value = candidates

        result = get_errored_song_ids(mock_db, _library(), limit=None)

        assert result == [candidate.identity for candidate in candidates]

    @pytest.mark.unit
    def test_get_stale_song_ids_scopes_to_library(self) -> None:
        mock_db = _make_mock_db()
        library = _library()
        mock_db.library.list_songs_with_state.return_value = [_candidate("b.mp3")]

        result = get_stale_song_ids(mock_db, library=library)

        assert result == [_candidate("b.mp3").identity]
        mock_db.library.list_songs_with_state.assert_called_once_with(
            STATE_TAGS_NOT_FRESH, library=_lib_identity(library)
        )

    @pytest.mark.unit
    def test_get_stale_song_ids_returns_all_when_no_library(self) -> None:
        """Stale locators with no library scope are the full tags-not-fresh set."""
        mock_db = _make_mock_db()
        candidates = [_candidate("a.mp3"), _candidate("b.mp3")]
        mock_db.library.list_songs_with_state.return_value = candidates

        result = get_stale_song_ids(mock_db)

        assert result == [candidate.identity for candidate in candidates]
        mock_db.library.list_songs_with_state.assert_called_once_with(STATE_TAGS_NOT_FRESH, library=None)


class TestMultiStateComposition:
    """Tests for multi-state composition helpers."""

    @pytest.mark.unit
    def test_get_uncalibrated_tagged_song_ids_intersects_state_sets(self) -> None:
        """Tagged-but-uncalibrated locators are intersected and returned in facade order."""
        mock_db = _make_mock_db()
        library = _library()
        processed = [_candidate("a.mp3", library=library), _candidate("b.mp3", library=library)]
        not_calibrated = [_candidate("b.mp3", library=library), _candidate("c.mp3", library=library)]
        mock_db.library.list_songs_with_state.side_effect = [processed, not_calibrated]

        result = get_uncalibrated_tagged_song_ids(mock_db, library)

        assert result == [processed[1].identity]

    @pytest.mark.unit
    def test_get_calibration_status_by_library_counts_intersections_per_library(self) -> None:
        mock_db = _make_mock_db()
        lib_a = _library(name="A")
        lib_b = _library(name="B")
        calibrated = [_candidate("a1.mp3", library=lib_a), _candidate("b1.mp3", library=lib_b)]
        not_calibrated = [_candidate("a2.mp3", library=lib_a), _candidate("b2.mp3", library=lib_b)]
        mock_db.library.list_songs_with_state.side_effect = [calibrated, not_calibrated]
        mock_db.library.list_libraries.return_value = [lib_a, lib_b]
        mock_db.library.list_songs.side_effect = [
            [_song("a1.mp3"), _song("a2.mp3")],
            [_song("b1.mp3"), _song("b2.mp3")],
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
        mock_db.library.list_songs_with_state.return_value = []

        result = get_calibration_status_by_library(mock_db)

        assert result == []
        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.library.list_songs.assert_not_called()


class TestIncompleteTags:
    """Tests for ``get_songs_with_incomplete_tags()``."""

    @staticmethod
    def _assignment(name: str) -> SongTagAssignment:
        return SongTagAssignment(name=name, value="x", namespace="nom")

    @pytest.mark.unit
    def test_returns_typed_candidate_for_missing_heads(self) -> None:
        mock_db = _make_mock_db()
        expected_heads = [
            {"head_key": "mood", "labels": ["mood"], "model_key_for_tag": "modelA"},
            {"head_key": "energy", "labels": ["energy"], "model_key_for_tag": "modelB"},
        ]
        candidate = _candidate("song1.mp3", states=(STATE_WRITTEN,))
        mock_db.library.list_songs_with_state.return_value = [candidate]
        mock_db.library.list_song_tags_for_songs.return_value = {
            candidate.identity: (self._assignment("nom:mood_modelA_happy"),)
        }

        result = get_songs_with_incomplete_tags(mock_db, expected_heads, namespace_prefix="nom:")

        assert len(result) == 1
        assert result[0].identity == candidate.identity
        assert result[0].song == candidate.song
        assert result[0].matched_count == 1
        assert result[0].missing_count == 1
        assert result[0].missing_heads == ("energy",)
        mock_db.library.list_songs_with_state.assert_called_once_with(STATE_WRITTEN, library=None)
        mock_db.library.list_song_tags_for_songs.assert_called_once_with(
            [candidate.identity],
            name_starts_with="nom:",
        )

    @pytest.mark.unit
    def test_scopes_results_to_library(self) -> None:
        mock_db = _make_mock_db()
        library = _library()
        candidate = _candidate("song2.mp3", library=library, states=(STATE_WRITTEN,))
        mock_db.library.list_songs_with_state.return_value = [candidate]
        mock_db.library.list_song_tags_for_songs.return_value = {}

        result = get_songs_with_incomplete_tags(
            mock_db,
            [{"head_key": "mood", "labels": ["mood"], "model_key_for_tag": "modelA"}],
            namespace_prefix="nom:",
            library=library,
        )

        assert len(result) == 1
        assert result[0].missing_heads == ("mood",)
        mock_db.library.list_songs_with_state.assert_called_once_with(STATE_WRITTEN, library=_lib_identity(library))

    @pytest.mark.unit
    def test_empty_candidates_returns_empty_without_tag_facade(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.return_value = []

        result = get_songs_with_incomplete_tags(mock_db, [], namespace_prefix="nom:")

        assert result == []
        mock_db.library.list_song_tags_for_songs.assert_not_called()


class TestTransitionFileState:
    """Tests for ``transition_song_state()``."""

    @pytest.mark.unit
    def test_delegates_valid_axis_pair_with_locators(self) -> None:
        """A valid axis pair is forwarded (deduplicated) to the sealed transition."""
        mock_db = _make_mock_db()
        first = _candidate("a.mp3").identity
        second = _candidate("b.mp3").identity

        transition_song_state(mock_db, [first, second], STATE_NOT_PROCESSED, STATE_PROCESSED)

        mock_db.app.transition_song_states.assert_called_once_with(
            [first, second], STATE_NOT_PROCESSED, STATE_PROCESSED
        )

    @pytest.mark.unit
    def test_deduplicates_repeated_locators(self) -> None:
        mock_db = _make_mock_db()
        first = _candidate("a.mp3").identity
        second = _candidate("b.mp3").identity

        transition_song_state(mock_db, [first, first, second], STATE_NOT_HYDRATED, STATE_HYDRATED)

        mock_db.app.transition_song_states.assert_called_once_with([first, second], STATE_NOT_HYDRATED, STATE_HYDRATED)

    @pytest.mark.unit
    def test_raises_value_error_for_invalid_axis_pair_without_touching_facade(self) -> None:
        mock_db = _make_mock_db()

        with pytest.raises(ValueError):
            transition_song_state(mock_db, [_candidate("a.mp3").identity], STATE_NOT_PROCESSED, STATE_CALIBRATED)

        mock_db.app.transition_song_states.assert_not_called()


class TestBulkTransitions:
    """Tests for the bulk state transition helpers."""

    @pytest.mark.unit
    def test_bulk_set_not_hydrated_repairs_missing_hydration_and_error_edges(self) -> None:
        """A no-hydration, errored locator gets a not_hydrated edge and recovers errored."""
        mock_db = _make_mock_db()
        library = _library()
        identity = SongIdentity(library=_lib_identity(library), normalized_path="a.mp3")
        mock_db.library.list_libraries.return_value = [library]
        mock_db.library.list_songs.return_value = [_song("a.mp3")]
        mock_db.app.song_state_memberships.return_value = {identity: {STATE_ERRORED}}

        result = bulk_set_not_hydrated(mock_db)

        assert result == 1
        mock_db.app.set_song_state.assert_called_once_with([identity], STATE_NOT_HYDRATED)
        mock_db.app.transition_song_states.assert_called_once_with([identity], STATE_ERRORED, STATE_NOT_ERRORED)

    @pytest.mark.unit
    def test_bulk_set_not_hydrated_transitions_hydrated_locators(self) -> None:
        mock_db = _make_mock_db()
        library = _library()
        identity = SongIdentity(library=_lib_identity(library), normalized_path="a.mp3")
        mock_db.library.list_libraries.return_value = [library]
        mock_db.library.list_songs.return_value = [_song("a.mp3")]
        mock_db.app.song_state_memberships.return_value = {identity: {STATE_HYDRATED}}

        result = bulk_set_not_hydrated(mock_db)

        assert result == 1
        mock_db.app.transition_song_states.assert_called_once_with([identity], STATE_HYDRATED, STATE_NOT_HYDRATED)
        mock_db.app.set_song_state.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_not_calibrated_transitions_all_calibrated_candidates(self) -> None:
        mock_db = _make_mock_db()
        candidates = [
            _candidate("a.mp3", states=(STATE_CALIBRATED,)),
            _candidate("b.mp3", states=(STATE_CALIBRATED,)),
        ]
        mock_db.library.list_songs_with_state.return_value = candidates

        result = bulk_set_not_calibrated(mock_db)

        assert result == 2
        mock_db.app.transition_song_states.assert_called_once_with(
            [candidate.identity for candidate in candidates], STATE_CALIBRATED, STATE_NOT_CALIBRATED
        )

    @pytest.mark.unit
    def test_bulk_set_not_calibrated_returns_zero_and_skips_transition_when_empty(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.return_value = []

        result = bulk_set_not_calibrated(mock_db)

        assert result == 0
        mock_db.app.transition_song_states.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_tags_not_fresh_scopes_to_library_before_transition(self) -> None:
        mock_db = _make_mock_db()
        library = _library()
        candidate = _candidate("b.mp3", library=library, states=(STATE_TAGS_CURRENT,))
        mock_db.library.list_songs_with_state.return_value = [candidate]

        result = bulk_set_tags_not_fresh(mock_db, library=library)

        assert result == 1
        mock_db.app.transition_song_states.assert_called_once_with(
            [candidate.identity], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH
        )
        mock_db.library.list_songs_with_state.assert_called_once_with(
            STATE_TAGS_CURRENT, library=_lib_identity(library)
        )

    @pytest.mark.unit
    def test_bulk_set_tags_not_fresh_transitions_all_when_no_library(self) -> None:
        mock_db = _make_mock_db()
        candidates = [
            _candidate("a.mp3", states=(STATE_TAGS_CURRENT,)),
            _candidate("b.mp3", states=(STATE_TAGS_CURRENT,)),
        ]
        mock_db.library.list_songs_with_state.return_value = candidates

        result = bulk_set_tags_not_fresh(mock_db)

        assert result == 2
        mock_db.app.transition_song_states.assert_called_once_with(
            [candidate.identity for candidate in candidates], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH
        )
        mock_db.library.list_songs_with_state.assert_called_once_with(STATE_TAGS_CURRENT, library=None)

    @pytest.mark.unit
    def test_bulk_set_not_vectors_extracted_transitions_all_vector_extracted_candidates(self) -> None:
        mock_db = _make_mock_db()
        candidate = _candidate("a.mp3", states=(STATE_VECTORS_EXTRACTED,))
        mock_db.library.list_songs_with_state.return_value = [candidate]

        result = bulk_set_not_vectors_extracted(mock_db)

        assert result == 1
        mock_db.app.transition_song_states.assert_called_once_with(
            [candidate.identity], STATE_VECTORS_EXTRACTED, STATE_NOT_VECTORS_EXTRACTED
        )

    @pytest.mark.unit
    def test_bulk_set_not_vectors_extracted_skips_empty_transition(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.return_value = []

        result = bulk_set_not_vectors_extracted(mock_db)

        assert result == 0
        mock_db.app.transition_song_states.assert_not_called()
