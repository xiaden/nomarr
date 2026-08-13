"""Tests for ``nomarr.components.library.library_song_state_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from nomarr.components.library.library_song_state_comp import (
    bulk_set_not_calibrated,
    bulk_set_not_vectors_extracted,
    bulk_set_tags_not_fresh,
    clear_all_states,
    clear_all_states_batch,
    count_errored_songs,
    count_pending_tag_writes,
    count_untagged_files,
    discover_next_untagged_file,
    get_calibration_status_by_library,
    get_errored_song_ids,
    get_songs_with_incomplete_tags,
    get_stale_song_ids,
    get_uncalibrated_tagged_song_ids,
    initialize_song_states,
    initialize_song_states_batch,
    library_has_tagged_files,
    mark_song_errored,
    song_has_tagged_state,
    transition_song_state,
)
from nomarr.helpers.constants.file_states import (
    ALL_STATE_VERTICES,
    AXIS_PAIRS,
    STATE_CALIBRATED,
    STATE_ERRORED,
    STATE_NOT_CALIBRATED,
    STATE_NOT_PROCESSED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_NOT_WRITTEN,
    STATE_PROCESSED,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_VECTORS_EXTRACTED,
)
from nomarr.helpers.exceptions import DuplicateEntityError


def _make_mock_db() -> MagicMock:
    mock_db = MagicMock()
    mock_db.app.list_song_docs_in_state.return_value = []
    mock_db.app.count_songs_in_state.return_value = 0
    mock_db.app.get_song_state.return_value = None
    mock_db.app.get_song_states_for_songs.return_value = {}
    mock_db.app.list_claims.return_value = []
    mock_db.library.list_songs.return_value = []
    mock_db.library.list_libraries.return_value = []
    mock_db.library.list_song_tags_for_songs.return_value = {}
    return mock_db


def _negative_state_vertices() -> list[str]:
    """Return the 8 negative poles in canonical ``ALL_STATE_VERTICES`` order.

    Derived from ``AXIS_PAIRS`` (the second element of each pair) so that the
    ``tags_not_fresh`` negative pole — the only one not ``not_``-prefixed —
    is included.
    """
    negative_set = {neg for _, neg in AXIS_PAIRS.values()}
    return [state for state in ALL_STATE_VERTICES if state in negative_set]


class TestInitializeFileStates:
    """Tests for ``initialize_song_states()``."""

    @pytest.mark.unit
    def test_inserts_negative_state_edges_for_single_file(self) -> None:
        mock_db = _make_mock_db()
        expected_negative_states = _negative_state_vertices()

        initialize_song_states(mock_db, 1)

        assert mock_db.app.add_song_states.call_args_list == [call([1], state) for state in expected_negative_states]

    @pytest.mark.unit
    def test_tags_not_fresh_is_pinned_as_a_negative_pole(self) -> None:
        """Pin that ``tags_not_fresh`` seeds a negative state edge.

        This negative pole is the second element of its axis pair, and the only
        one not ``not_``-prefixed, so a ``not_``-prefix derivation would miss it;
        it is only captured by the AXIS_PAIRS-derived negative-pole set. Losing
        it would hide stale songs from get_stale_song_ids.
        """
        mock_db = _make_mock_db()

        initialize_song_states(mock_db, 1)

        assert call([1], STATE_TAGS_NOT_FRESH) in mock_db.app.add_song_states.call_args_list

    @pytest.mark.unit
    def test_silently_skips_duplicate_key_error(self) -> None:
        mock_db = _make_mock_db()
        expected_negative_states = _negative_state_vertices()
        mock_db.app.add_song_states.side_effect = DuplicateEntityError()

        initialize_song_states(mock_db, 1)

        assert mock_db.app.add_song_states.call_count == len(expected_negative_states)


class TestInitializeFileStatesBatch:
    """Tests for ``initialize_song_states_batch()``."""

    @pytest.mark.unit
    def test_inserts_negative_state_edges_for_multiple_files(self) -> None:
        mock_db = _make_mock_db()
        expected_negative_states = _negative_state_vertices()
        expected_docs = [{"_from": song_id, "_to": state} for song_id in [1, 2] for state in expected_negative_states]

        initialize_song_states_batch(mock_db, [1, 2])

        assert mock_db.app.add_song_states.call_args_list == [call([doc["_from"]], doc["_to"]) for doc in expected_docs]

    @pytest.mark.unit
    def test_skips_query_when_batch_empty(self) -> None:
        mock_db = _make_mock_db()

        initialize_song_states_batch(mock_db, [])

        mock_db.app.add_song_states.assert_not_called()

    @pytest.mark.unit
    def test_silently_skips_duplicate_key_error(self) -> None:
        mock_db = _make_mock_db()
        expected_negative_states = _negative_state_vertices()
        mock_db.app.add_song_states.side_effect = DuplicateEntityError()

        initialize_song_states_batch(mock_db, [1, 2])

        assert mock_db.app.add_song_states.call_count == 2 * len(expected_negative_states)


class TestClearAllStates:
    """Tests for ``clear_all_states()``."""

    @pytest.mark.unit
    def test_deletes_single_file_edges_via_app_facade(self) -> None:
        mock_db = _make_mock_db()
        states_with_file = {
            STATE_PROCESSED,
            STATE_TAGS_CURRENT,
            STATE_NOT_CALIBRATED,
            STATE_NOT_VECTORS_EXTRACTED,
        }
        mock_db.app.list_song_docs_in_state.side_effect = lambda state: [{"id": 1}] if state in states_with_file else []

        result = clear_all_states(mock_db, 1)

        assert result == 4
        mock_db.app.remove_song_states.assert_called_once_with([1])


class TestClearAllStatesBatch:
    """Tests for ``clear_all_states_batch()``."""

    @pytest.mark.unit
    def test_deletes_file_batch_edges_via_app_facade(self) -> None:
        mock_db = _make_mock_db()
        docs_by_state = {
            STATE_PROCESSED: [
                {"id": 1},
                {"id": 2},
            ],
            STATE_TAGS_CURRENT: [{"id": 1}],
            STATE_NOT_CALIBRATED: [
                {"id": 1},
                {"id": 2},
            ],
            STATE_NOT_VECTORS_EXTRACTED: [
                {"id": 1},
                {"id": 2},
            ],
        }
        mock_db.app.list_song_docs_in_state.side_effect = lambda state: docs_by_state.get(state, [])

        result = clear_all_states_batch(mock_db, [1, 2])

        assert result == 7
        mock_db.app.remove_song_states.assert_called_once_with([1, 2])

    @pytest.mark.unit
    def test_returns_zero_without_query_when_batch_empty(self) -> None:
        mock_db = _make_mock_db()

        result = clear_all_states_batch(mock_db, [])

        assert result == 0


class TestSimpleStateLookups:
    """Tests for the simple constructor-backed state lookups."""

    @pytest.mark.unit
    def test_count_pending_tag_writes_uses_state_edge_counter(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.count_songs_in_state.return_value = 2

        result = count_pending_tag_writes(mock_db)

        assert result == 2
        mock_db.app.count_songs_in_state.assert_called_once_with(STATE_NOT_WRITTEN)

    @pytest.mark.unit
    def test_file_has_tagged_state_uses_library_facade_counter(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.get_song_state.return_value = STATE_PROCESSED

        result = song_has_tagged_state(mock_db, 1)

        assert result is True
        mock_db.app.get_song_state.assert_called_once_with(1)

    @pytest.mark.unit
    def test_library_has_tagged_files_intersects_tagged_and_library_membership(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.return_value = [
            {"id": 1},
            {"id": 9},
        ]
        mock_db.library.list_songs.return_value = [
            {"id": 2},
            {"id": 9},
        ]

        result = library_has_tagged_files(mock_db, 1)

        assert result is True
        mock_db.app.list_song_docs_in_state.assert_called_once_with(STATE_PROCESSED)
        mock_db.library.list_songs.assert_called_once_with(1)

    @pytest.mark.unit
    def test_file_has_tagged_state_returns_false_when_count_is_zero(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.get_song_state.return_value = None

        result = song_has_tagged_state(mock_db, 1)

        assert result is False

    @pytest.mark.unit
    def test_library_has_tagged_files_returns_false_when_no_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.return_value = [{"id": 1}]
        mock_db.library.list_songs.return_value = [{"id": 2}]

        result = library_has_tagged_files(mock_db, 1)

        assert result is False


class TestDiscoverNextUntaggedFile:
    """Tests for ``discover_next_untagged_file()``."""

    @pytest.mark.unit
    def test_returns_first_library_scoped_unclaimed_file_sorted_by_key(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = [
            [
                {"id": 3},
                {"id": 1},
                {"id": 2},
            ],
            [{"id": 2}],
            [],
        ]
        mock_db.library.list_songs.return_value = [
            {"id": 1},
            {"id": 2},
            {"id": 3},
        ]
        mock_db.app.list_claims.return_value = [{"key": "3"}]

        result = discover_next_untagged_file(mock_db, library_id=1)

        assert result == {"id": 1}
        assert mock_db.app.list_song_docs_in_state.call_args_list == [
            call(STATE_NOT_PROCESSED),
            call(STATE_ERRORED),
        ]
        mock_db.app.list_claims.assert_called_once_with()

    @pytest.mark.unit
    def test_returns_none_when_no_candidates_survive_filters(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = [
            [{"id": 1}],
            [{"id": 1}],  # same file is errored, so it's filtered out
        ]

        result = discover_next_untagged_file(mock_db)

        assert result is None

    @pytest.mark.unit
    def test_does_not_exclude_claimed_files_when_flag_is_false(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = [
            [
                {"id": 2},
                {"id": 1},
            ],
            [],
        ]

        result = discover_next_untagged_file(mock_db, exclude_claimed=False)

        assert result == {"id": 1}
        mock_db.app.list_claims.assert_not_called()


class TestLibraryScopedStateQueries:
    """Tests for library-scoped state query helpers."""

    @pytest.mark.unit
    def test_count_untagged_files_excludes_errored_after_library_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = [
            [
                {"id": 1},
                {"id": 2},
                {"id": 3},
            ],
        ]
        mock_db.library.list_songs.return_value = [
            {"id": 2},
            {"id": 3},
        ]

        result = count_untagged_files(mock_db, library_id=1)

        assert result == 2
        assert mock_db.app.list_song_docs_in_state.call_args_list == [
            call(STATE_NOT_PROCESSED),
        ]

    @pytest.mark.unit
    def test_get_errored_song_ids_normalizes_library_id_and_applies_limit_after_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs.return_value = [
            {"id": 2},
            {"id": 3},
        ]
        mock_db.app.list_song_docs_in_state.return_value = [
            {"id": 9},
            {"id": 2},
            {"id": 3},
        ]

        result = get_errored_song_ids(mock_db, 1, limit=1)

        assert result == [2]
        mock_db.library.list_songs.assert_called_once_with(1)
        mock_db.app.list_song_docs_in_state.assert_called_once_with(STATE_ERRORED)

    @pytest.mark.unit
    def test_count_errored_files_counts_full_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs.return_value = [
            {"id": 2},
            {"id": 3},
        ]
        mock_db.app.list_song_docs_in_state.return_value = [
            {"id": 2},
            {"id": 3},
        ]

        result = count_errored_songs(mock_db, 1)

        assert result == 2

    @pytest.mark.unit
    def test_get_errored_song_ids_returns_all_when_limit_is_none(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs.return_value = [
            {"id": 1},
            {"id": 2},
            {"id": 3},
        ]
        mock_db.app.list_song_docs_in_state.return_value = [
            {"id": 1},
            {"id": 2},
            {"id": 3},
        ]

        result = get_errored_song_ids(mock_db, 1, limit=None)

        assert result == [
            1,
            2,
            3,
        ]

    @pytest.mark.unit
    def test_get_stale_song_ids_scopes_to_library_membership(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.return_value = [
            {"id": 1},
            {"id": 2},
        ]
        mock_db.library.list_songs.return_value = [{"id": 2}]

        result = get_stale_song_ids(mock_db, library_id=1)

        assert result == [2]
        mock_db.app.list_song_docs_in_state.assert_called_once_with(STATE_TAGS_NOT_FRESH)
        mock_db.library.list_songs.assert_called_once_with(1)

    @pytest.mark.unit
    def test_count_untagged_files_returns_global_count_when_no_library_id(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = [
            [
                {"id": 1},
                {"id": 2},
                {"id": 3},
            ],
        ]

        result = count_untagged_files(mock_db)

        assert result == 3
        mock_db.library.list_songs.assert_not_called()

    @pytest.mark.unit
    def test_get_stale_song_ids_returns_all_ids_when_no_library_id(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.return_value = [
            {"id": 1},
            {"id": 2},
        ]

        result = get_stale_song_ids(mock_db)

        assert result == [1, 2]
        mock_db.library.list_songs.assert_not_called()

    @pytest.mark.unit
    def test_get_stale_song_ids_scan_drops_raw_rows_without_an_id(self) -> None:
        """The stale-scan boundary only admits raw rows carrying a valid ``id``.

        ``list_song_docs_in_state`` returns raw rows; rows that are not dicts or
        lack an ``id`` key must be excluded from the returned song-ids.
        """
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.return_value = [
            {"id": 1},
            {"name": "no identifier"},
            "not-a-row",
            {"id": 4},
        ]

        result = get_stale_song_ids(mock_db)

        assert result == [1, 4]
        mock_db.app.list_song_docs_in_state.assert_called_once_with(STATE_TAGS_NOT_FRESH)


class TestMarkFileErrored:
    """Tests for ``mark_song_errored()``."""

    @pytest.mark.unit
    def test_returns_without_transition_when_song_holds_only_negative_states(self) -> None:
        """A song whose only state is a negative pole (e.g. ``tags_not_fresh``)
        has no positive state to transition from, so it is left untouched."""
        mock_db = _make_mock_db()
        mock_db.app.get_song_states_for_songs.return_value = {7: {STATE_TAGS_NOT_FRESH}}

        mark_song_errored(mock_db, 7)

        mock_db.app.remove_song_states.assert_not_called()
        mock_db.app.add_song_states.assert_not_called()

    @pytest.mark.unit
    def test_returns_without_transition_when_song_has_no_state_membership(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.get_song_states_for_songs.return_value = {}

        mark_song_errored(mock_db, 7)

        mock_db.app.remove_song_states.assert_not_called()
        mock_db.app.add_song_states.assert_not_called()

    @pytest.mark.unit
    def test_song_in_positive_state_on_other_axis_raises_invalid_transition(self) -> None:
        """A song held in a positive pole on a non-errored axis cannot be moved to
        ``errored``: ``errored`` only pairs with ``not_errored``, so the transition
        is rejected by the axis-pair validator."""
        mock_db = _make_mock_db()
        mock_db.app.get_song_states_for_songs.return_value = {7: {STATE_PROCESSED}}

        with pytest.raises(ValueError):
            mark_song_errored(mock_db, 7)


class TestMultiStateComposition:
    """Tests for multi-state composition helpers."""

    @pytest.mark.unit
    def test_get_uncalibrated_tagged_song_ids_intersects_state_sets_in_library_order(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = [
            [{"id": 1}, {"id": 3}],
            [{"id": 2}, {"id": 3}],
        ]
        mock_db.library.list_songs.return_value = [
            {"id": 2},
            {"id": 3},
            {"id": 1},
        ]

        result = get_uncalibrated_tagged_song_ids(mock_db, 1)

        assert result == [3]

    @pytest.mark.unit
    def test_get_calibration_status_by_library_counts_intersections_per_library(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = [
            [{"id": 1}, {"id": 2}],
            [{"id": 3}, {"id": 4}],
        ]
        mock_db.library.list_libraries.return_value = [
            {"id": 1},
            {"id": 2},
        ]
        mock_db.library.list_songs.side_effect = [
            [{"id": 1}, {"id": 3}],
            [{"id": 2}, {"id": 4}],
        ]

        result = get_calibration_status_by_library(mock_db)

        assert result == [
            {
                "library_id": 1,
                "calibrated_count": 1,
                "not_calibrated_count": 1,
            },
            {
                "library_id": 2,
                "calibrated_count": 1,
                "not_calibrated_count": 1,
            },
        ]
        mock_db.library.list_libraries.assert_called_once_with()

    @pytest.mark.unit
    def test_get_calibration_status_by_library_returns_empty_list_when_no_libraries(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = [[], []]
        mock_db.library.list_libraries.return_value = []

        result = get_calibration_status_by_library(mock_db)

        assert result == []
        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.library.list_songs.assert_not_called()


class TestIncompleteTags:
    """Tests for ``get_songs_with_incomplete_tags()``."""

    @pytest.mark.unit
    def test_preserves_head_matching_logic_for_matching_and_missing_heads(self) -> None:
        mock_db = _make_mock_db()
        expected_heads = [
            {"head_key": "mood", "labels": ["mood"], "model_key_for_tag": "modelA"},
            {"head_key": "energy", "labels": ["energy"], "model_key_for_tag": "modelB"},
        ]
        mock_db.app.list_song_docs_in_state.return_value = [{"id": 1}]
        mock_db.library.list_song_tags_for_songs.return_value = {
            1: [
                {"name": "nom:mood_modelA_happy"},
                {"name": "nom:energy_modelB_high"},
                {"name": "nom:energy_other_model"},
            ]
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
        mock_db.library.list_song_tags_for_songs.assert_called_once_with(
            [1],
            name_starts_with="nom:",
        )

    @pytest.mark.unit
    def test_scopes_incomplete_tag_results_to_library_and_returns_normalized_library_id(self) -> None:
        mock_db = _make_mock_db()
        expected_heads = [
            {"head_key": "mood", "labels": ["mood"], "model_key_for_tag": "modelA"},
            {"head_key": "energy", "labels": ["energy"], "model_key_for_tag": "modelB"},
        ]
        mock_db.app.list_song_docs_in_state.return_value = [
            {"id": 1},
            {"id": 2},
        ]
        mock_db.library.list_songs.return_value = [{"id": 2}]
        mock_db.library.list_song_tags_for_songs.return_value = {
            2: [{"name": "nom:mood_modelA_happy"}],
        }

        result = get_songs_with_incomplete_tags(mock_db, expected_heads, namespace_prefix="nom:", library_id=1)

        assert result == [
            {
                "file_id": 2,
                "file_key": 2,
                "library_id": 1,
                "matched_count": 1,
                "missing_count": 1,
                "missing_heads": ["energy"],
            }
        ]
        mock_db.library.list_songs.assert_called_once_with(1)
        mock_db.library.list_song_tags_for_songs.assert_called_once_with(
            [2],
            name_starts_with="nom:",
        )


class TestTransitionFileState:
    """Tests for ``transition_song_state()``."""

    @pytest.mark.unit
    def test_rewrites_state_membership_via_normalized_file_state_methods_for_valid_axis_pair(self) -> None:
        mock_db = _make_mock_db()
        song_ids = [1, 2]
        from_state = STATE_NOT_PROCESSED
        to_state = STATE_PROCESSED
        mock_db.app.get_song_states_for_songs.return_value = {
            1: {from_state},
            2: {from_state},
        }

        transition_song_state(mock_db, song_ids, from_state, to_state)

        mock_db.app.remove_song_states.assert_called_once_with(song_ids)
        mock_db.app.add_song_states.assert_called_once_with(song_ids, to_state)

    @pytest.mark.unit
    def test_raises_value_error_for_invalid_axis_pair(self) -> None:
        mock_db = _make_mock_db()
        song_ids = [1]

        with pytest.raises(ValueError):
            transition_song_state(mock_db, song_ids, STATE_NOT_PROCESSED, STATE_CALIBRATED)

        mock_db.app.remove_song_states.assert_not_called()
        mock_db.app.add_song_states.assert_not_called()


class TestBulkTransitions:
    """Tests for the bulk state transition helpers."""

    @pytest.mark.unit
    def test_bulk_set_not_calibrated_uses_normalized_state_writes_for_all_calibrated_files(self) -> None:
        mock_db = _make_mock_db()
        calibrated_ids = [1, 2]
        mock_db.app.list_song_docs_in_state.side_effect = lambda state: list(
            [{"id": song_id} for song_id in calibrated_ids] if state == STATE_CALIBRATED else []
        )
        mock_db.app.get_song_states_for_songs.return_value = {
            1: {STATE_CALIBRATED},
            2: {STATE_CALIBRATED},
        }

        result = bulk_set_not_calibrated(mock_db)

        assert result == 2
        mock_db.app.list_song_docs_in_state.assert_any_call(STATE_CALIBRATED)
        mock_db.app.remove_song_states.assert_called_once_with(calibrated_ids)
        mock_db.app.add_song_states.assert_called_once_with(calibrated_ids, STATE_NOT_CALIBRATED)

    @pytest.mark.unit
    def test_bulk_set_tags_not_fresh_filters_to_library_before_transition(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.side_effect = lambda state: list(
            [
                {"id": 1},
                {"id": 2},
            ]
            if state == STATE_TAGS_CURRENT
            else []
        )
        mock_db.library.list_songs.return_value = [{"id": 2}]
        mock_db.app.get_song_states_for_songs.return_value = {
            2: {STATE_TAGS_CURRENT},
        }

        result = bulk_set_tags_not_fresh(mock_db, library_id=1)

        assert result == 1
        mock_db.app.remove_song_states.assert_called_once_with([2])
        mock_db.app.add_song_states.assert_called_once_with([2], STATE_TAGS_NOT_FRESH)
        mock_db.app.list_song_docs_in_state.assert_any_call(STATE_TAGS_CURRENT)
        mock_db.library.list_songs.assert_called_once_with(1)

    @pytest.mark.unit
    def test_bulk_set_not_vectors_extracted_skips_empty_transition(self) -> None:
        mock_db = _make_mock_db()

        result = bulk_set_not_vectors_extracted(mock_db)

        assert result == 0
        mock_db.app.remove_song_states.assert_not_called()
        mock_db.app.add_song_states.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_not_calibrated_returns_zero_and_skips_transition_when_no_calibrated_files(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.return_value = []

        result = bulk_set_not_calibrated(mock_db)

        assert result == 0
        mock_db.app.remove_song_states.assert_not_called()
        mock_db.app.add_song_states.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_tags_not_fresh_transitions_all_tags_current_files_when_no_library_id(self) -> None:
        mock_db = _make_mock_db()
        current_ids = [1, 2]
        mock_db.app.list_song_docs_in_state.side_effect = lambda state: list(
            [{"id": song_id} for song_id in current_ids] if state == STATE_TAGS_CURRENT else []
        )
        mock_db.app.get_song_states_for_songs.return_value = {
            1: {STATE_TAGS_CURRENT},
            2: {STATE_TAGS_CURRENT},
        }

        result = bulk_set_tags_not_fresh(mock_db)

        assert result == 2
        mock_db.app.remove_song_states.assert_called_once_with(current_ids)
        mock_db.app.add_song_states.assert_called_once_with(current_ids, STATE_TAGS_NOT_FRESH)
        mock_db.library.list_songs.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_tags_not_fresh_returns_zero_and_skips_transition_when_no_tags_current_files(self) -> None:
        mock_db = _make_mock_db()
        mock_db.app.list_song_docs_in_state.return_value = []

        result = bulk_set_tags_not_fresh(mock_db)

        assert result == 0
        mock_db.app.remove_song_states.assert_not_called()
        mock_db.app.add_song_states.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_not_vectors_extracted_transitions_all_vector_extracted_files(self) -> None:
        mock_db = _make_mock_db()
        vector_ids = [7]
        mock_db.app.list_song_docs_in_state.side_effect = lambda state: list(
            [{"id": song_id} for song_id in vector_ids] if state == STATE_VECTORS_EXTRACTED else []
        )
        mock_db.app.get_song_states_for_songs.return_value = {
            7: {STATE_VECTORS_EXTRACTED},
        }

        result = bulk_set_not_vectors_extracted(mock_db)

        assert result == 1
        mock_db.app.list_song_docs_in_state.assert_any_call(STATE_VECTORS_EXTRACTED)
        mock_db.app.remove_song_states.assert_called_once_with(vector_ids)
        mock_db.app.add_song_states.assert_called_once_with(vector_ids, STATE_NOT_VECTORS_EXTRACTED)
