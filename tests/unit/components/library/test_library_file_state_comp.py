"""Tests for ``nomarr.components.library.library_file_state_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from arango.exceptions import DocumentInsertError

from nomarr.components.library.library_file_state_comp import (
    bulk_set_not_calibrated,
    bulk_set_not_vectors_extracted,
    bulk_set_tags_stale,
    clear_all_states,
    clear_all_states_batch,
    count_errored_files,
    count_pending_tag_writes,
    count_untagged_files,
    discover_next_untagged_file,
    file_has_tagged_state,
    find_short_files_missing_too_short,
    get_calibration_status_by_library,
    get_errored_file_ids,
    get_files_with_incomplete_tags,
    get_stale_file_ids,
    get_uncalibrated_tagged_file_ids,
    initialize_file_states,
    initialize_file_states_batch,
    library_has_tagged_files,
    transition_file_state,
)
from nomarr.helpers.constants.file_states import (
    ALL_STATE_VERTICES,
    STATE_CALIBRATED,
    STATE_ERRORED,
    STATE_NOT_CALIBRATED,
    STATE_NOT_TAGGED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_TAGGED,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_WRITTEN,
    STATE_TAGS_STALE,
    STATE_TOO_SHORT,
    STATE_VECTORS_EXTRACTED,
)
from nomarr.persistence.query_specs import PaginationSpec, QueryCriterion, QueryOperator, ReadQuerySpec, WriteQuerySpec


def _make_mock_db() -> MagicMock:
    mock_db = MagicMock()
    mock_db.file_states.file_has_state.return_value = []
    mock_db.file_has_state.get.return_value = []
    mock_db.file_has_state.count.return_value = 0
    mock_db.library_contains_file.get.return_value = []
    mock_db.worker_claims.aggregate.return_value = []
    mock_db.worker_claims.count.return_value = 0
    mock_db.libraries.aggregate.return_value = []
    mock_db.library_files.song_has_tags.by_ids.return_value = []
    return mock_db


class TestInitializeFileStates:
    """Tests for ``initialize_file_states()``."""

    @pytest.mark.unit
    def test_inserts_negative_state_edges_for_single_file(self) -> None:
        mock_db = _make_mock_db()
        expected_negative_states = [
            state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_") or state == STATE_TAGS_STALE
        ]

        initialize_file_states(mock_db, "library_files/1")

        assert mock_db.file_has_state.insert.call_args_list == [
            call([{"_from": "library_files/1", "_to": state}]) for state in expected_negative_states
        ]

    @pytest.mark.unit
    def test_silently_skips_duplicate_key_error(self) -> None:
        mock_db = _make_mock_db()
        expected_negative_states = [
            state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_") or state == STATE_TAGS_STALE
        ]
        err = DocumentInsertError.__new__(DocumentInsertError)
        err.error_code = 1210
        mock_db.file_has_state.insert.side_effect = err

        initialize_file_states(mock_db, "library_files/1")

        assert mock_db.file_has_state.insert.call_count == len(expected_negative_states)

    @pytest.mark.unit
    def test_reraises_non_duplicate_insert_error(self) -> None:
        mock_db = _make_mock_db()
        err = DocumentInsertError.__new__(DocumentInsertError)
        err.error_code = 1200
        mock_db.file_has_state.insert.side_effect = err

        with pytest.raises(DocumentInsertError):
            initialize_file_states(mock_db, "library_files/1")


class TestInitializeFileStatesBatch:
    """Tests for ``initialize_file_states_batch()``."""

    @pytest.mark.unit
    def test_inserts_negative_state_edges_for_multiple_files(self) -> None:
        mock_db = _make_mock_db()
        expected_negative_states = [
            state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_") or state == STATE_TAGS_STALE
        ]
        expected_docs = [
            {"_from": file_id, "_to": state}
            for file_id in ["library_files/1", "library_files/2"]
            for state in expected_negative_states
        ]

        initialize_file_states_batch(mock_db, ["library_files/1", "library_files/2"])

        assert mock_db.file_has_state.insert.call_args_list == [call([doc]) for doc in expected_docs]

    @pytest.mark.unit
    def test_skips_query_when_batch_empty(self) -> None:
        mock_db = _make_mock_db()

        initialize_file_states_batch(mock_db, [])

        mock_db.file_has_state.insert.assert_not_called()

    @pytest.mark.unit
    def test_silently_skips_duplicate_key_error(self) -> None:
        mock_db = _make_mock_db()
        expected_negative_states = [
            state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_") or state == STATE_TAGS_STALE
        ]
        err = DocumentInsertError.__new__(DocumentInsertError)
        err.error_code = 1210
        mock_db.file_has_state.insert.side_effect = err

        initialize_file_states_batch(mock_db, ["library_files/1", "library_files/2"])

        assert mock_db.file_has_state.insert.call_count == 2 * len(expected_negative_states)

    @pytest.mark.unit
    def test_reraises_non_duplicate_insert_error(self) -> None:
        mock_db = _make_mock_db()
        err = DocumentInsertError.__new__(DocumentInsertError)
        err.error_code = 1200
        mock_db.file_has_state.insert.side_effect = err

        with pytest.raises(DocumentInsertError):
            initialize_file_states_batch(mock_db, ["library_files/1", "library_files/2"])


class TestClearAllStates:
    """Tests for ``clear_all_states()``."""

    @pytest.mark.unit
    def test_delegates_to_constructor_delete_for_single_file(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.delete.return_value = 4

        result = clear_all_states(mock_db, "library_files/1")

        assert result == 4
        mock_db.file_has_state.delete.assert_called_once_with(_from="library_files/1")


class TestClearAllStatesBatch:
    """Tests for ``clear_all_states_batch()``."""

    @pytest.mark.unit
    def test_sums_constructor_delete_counts_for_file_batch(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.delete.return_value = 7

        result = clear_all_states_batch(mock_db, ["library_files/1", "library_files/2"])

        assert result == 7
        mock_db.file_has_state.delete.assert_called_once_with(
            query_spec=WriteQuerySpec(
                collection_name="file_has_state",
                criteria=(QueryCriterion("_from", QueryOperator.IN, ["library_files/1", "library_files/2"]),),
            )
        )

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
        mock_db.file_has_state.count.return_value = 2

        result = count_pending_tag_writes(mock_db)

        assert result == 2
        mock_db.file_has_state.count.assert_called_once_with(_to=STATE_TAGS_NOT_WRITTEN)

    @pytest.mark.unit
    def test_file_has_tagged_state_uses_count_by_filter(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.count.return_value = 1

        result = file_has_tagged_state(mock_db, "library_files/1")

        assert result is True
        mock_db.file_has_state.count.assert_called_once_with(
            _from="library_files/1",
            _to=STATE_TAGGED,
        )

    @pytest.mark.unit
    def test_library_has_tagged_files_intersects_tagged_and_library_membership(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.return_value = [
            {"_id": "library_files/1"},
            {"_id": "library_files/9"},
        ]
        mock_db.library_contains_file.get.return_value = [
            {"_to": "library_files/2"},
            {"_to": "library_files/9"},
        ]

        result = library_has_tagged_files(mock_db, "libraries/1")

        assert result is True
        mock_db.file_states.file_has_state.assert_called_once_with(STATE_TAGGED, limit=None)
        mock_db.library_contains_file.get.assert_called_once_with(_from="libraries/1", limit=None)

    @pytest.mark.unit
    def test_file_has_tagged_state_returns_false_when_count_is_zero(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.count.return_value = 0

        result = file_has_tagged_state(mock_db, "library_files/1")

        assert result is False

    @pytest.mark.unit
    def test_library_has_tagged_files_returns_false_when_no_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.return_value = [{"_id": "library_files/1"}]
        mock_db.library_contains_file.get.return_value = [{"_to": "library_files/2"}]

        result = library_has_tagged_files(mock_db, "libraries/1")

        assert result is False


class TestDiscoverNextUntaggedFile:
    """Tests for ``discover_next_untagged_file()``."""

    @pytest.mark.unit
    def test_returns_first_library_scoped_unclaimed_file_sorted_by_key(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.side_effect = [
            [
                {"_id": "library_files/3", "_key": "c"},
                {"_id": "library_files/1", "_key": "a"},
                {"_id": "library_files/2", "_key": "b"},
            ],
            [{"_id": "library_files/2"}],
            [],
        ]
        mock_db.library_contains_file.get.return_value = [
            {"_to": "library_files/1"},
            {"_to": "library_files/2"},
            {"_to": "library_files/3"},
        ]
        mock_db.worker_claims.count.return_value = 1
        mock_db.worker_claims.aggregate.return_value = [{"value": "library_files/3"}]

        result = discover_next_untagged_file(mock_db, library_id="libraries/1")

        assert result == {"_id": "library_files/1", "_key": "a"}
        assert mock_db.file_states.file_has_state.call_args_list == [
            call(STATE_NOT_TAGGED, limit=None),
            call(STATE_TOO_SHORT, limit=None),
            call(STATE_ERRORED, limit=None),
        ]
        mock_db.worker_claims.aggregate.assert_called_once_with("file_id", limit=1)

    @pytest.mark.unit
    def test_returns_none_when_no_candidates_survive_filters(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.side_effect = [
            [{"_id": "library_files/1", "_key": "a"}],
            [{"_id": "library_files/1"}],
            [],
        ]

        result = discover_next_untagged_file(mock_db)

        assert result is None

    @pytest.mark.unit
    def test_does_not_exclude_claimed_files_when_flag_is_false(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.side_effect = [
            [
                {"_id": "library_files/2", "_key": "b"},
                {"_id": "library_files/1", "_key": "a"},
            ],
            [],
            [],
        ]

        result = discover_next_untagged_file(mock_db, exclude_claimed=False)

        assert result == {"_id": "library_files/1", "_key": "a"}
        mock_db.worker_claims.aggregate.assert_not_called()


class TestLibraryScopedStateQueries:
    """Tests for library-scoped state query helpers."""

    @pytest.mark.unit
    def test_count_untagged_files_excludes_too_short_after_library_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.side_effect = [
            [
                {"_id": "library_files/1"},
                {"_id": "library_files/2"},
                {"_id": "library_files/3"},
            ],
            [{"_id": "library_files/3"}],
        ]
        mock_db.library_contains_file.get.return_value = [
            {"_to": "library_files/2"},
            {"_to": "library_files/3"},
        ]

        result = count_untagged_files(mock_db, library_id="libraries/1")

        assert result == 1
        assert mock_db.file_states.file_has_state.call_args_list == [
            call(STATE_NOT_TAGGED, limit=None),
            call(STATE_TOO_SHORT, limit=None),
        ]

    @pytest.mark.unit
    def test_get_errored_file_ids_normalizes_library_id_and_applies_limit_after_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library_contains_file.get.return_value = [
            {"_to": "library_files/2"},
            {"_to": "library_files/3"},
        ]
        mock_db.file_has_state.get.return_value = [
            {"_from": "library_files/9"},
            {"_from": "library_files/2"},
            {"_from": "library_files/3"},
        ]

        result = get_errored_file_ids(mock_db, "main", limit=1)

        assert result == ["library_files/2"]
        mock_db.library_contains_file.get.assert_called_once_with(_from="libraries/main", limit=None)
        mock_db.file_has_state.get.assert_called_once_with(_to=STATE_ERRORED, limit=None)

    @pytest.mark.unit
    def test_count_errored_files_counts_full_intersection(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library_contains_file.get.return_value = [
            {"_to": "library_files/2"},
            {"_to": "library_files/3"},
        ]
        mock_db.file_has_state.get.return_value = [
            {"_from": "library_files/2"},
            {"_from": "library_files/3"},
        ]

        result = count_errored_files(mock_db, "main")

        assert result == 2

    @pytest.mark.unit
    def test_get_errored_file_ids_returns_all_when_limit_is_none(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library_contains_file.get.return_value = [
            {"_to": "library_files/1"},
            {"_to": "library_files/2"},
            {"_to": "library_files/3"},
        ]
        mock_db.file_has_state.get.return_value = [
            {"_from": "library_files/1"},
            {"_from": "library_files/2"},
            {"_from": "library_files/3"},
        ]

        result = get_errored_file_ids(mock_db, "libraries/main", limit=None)

        assert result == ["library_files/1", "library_files/2", "library_files/3"]

    @pytest.mark.unit
    def test_get_stale_file_ids_scopes_to_library_membership(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.return_value = [
            {"_id": "library_files/1"},
            {"_id": "library_files/2"},
        ]
        mock_db.library_contains_file.get.return_value = [{"_to": "library_files/2"}]

        result = get_stale_file_ids(mock_db, library_id="libraries/1")

        assert result == ["library_files/2"]
        mock_db.file_states.file_has_state.assert_called_once_with(STATE_TAGS_STALE, limit=None)
        mock_db.library_contains_file.get.assert_called_once_with(_from="libraries/1", limit=None)

    @pytest.mark.unit
    def test_count_untagged_files_returns_global_count_when_no_library_id(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.side_effect = [
            [
                {"_id": "library_files/1"},
                {"_id": "library_files/2"},
                {"_id": "library_files/3"},
            ],
            [{"_id": "library_files/2"}],
        ]

        result = count_untagged_files(mock_db)

        assert result == 2
        mock_db.library_contains_file.get.assert_not_called()

    @pytest.mark.unit
    def test_get_stale_file_ids_returns_all_ids_when_no_library_id(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.return_value = [
            {"_id": "library_files/1"},
            {"_id": "library_files/2"},
        ]

        result = get_stale_file_ids(mock_db)

        assert result == ["library_files/1", "library_files/2"]
        mock_db.library_contains_file.get.assert_not_called()


class TestMultiStateComposition:
    """Tests for multi-state composition helpers."""

    @pytest.mark.unit
    def test_get_uncalibrated_tagged_file_ids_intersects_state_sets_in_library_order(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.side_effect = [
            [{"_id": "library_files/1"}, {"_id": "library_files/3"}],
            [{"_id": "library_files/2"}, {"_id": "library_files/3"}],
        ]
        mock_db.library_contains_file.get.return_value = [
            {"_to": "library_files/2"},
            {"_to": "library_files/3"},
            {"_to": "library_files/1"},
        ]

        result = get_uncalibrated_tagged_file_ids(mock_db, "libraries/1")

        assert result == ["library_files/3"]

    @pytest.mark.unit
    def test_get_calibration_status_by_library_counts_intersections_per_library(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.side_effect = [
            [{"_id": "library_files/1"}, {"_id": "library_files/2"}],
            [{"_id": "library_files/3"}, {"_id": "library_files/4"}],
        ]
        mock_db.libraries.count.return_value = 2
        mock_db.libraries.aggregate.return_value = [
            {"value": "libraries/alpha"},
            {"value": "libraries/beta"},
        ]
        mock_db.libraries.get.return_value = [
            {"_id": "libraries/alpha"},
            {"_id": "libraries/beta"},
        ]
        mock_db.library_contains_file.get.side_effect = [
            [{"_to": "library_files/1"}, {"_to": "library_files/3"}],
            [{"_to": "library_files/2"}, {"_to": "library_files/4"}],
        ]

        result = get_calibration_status_by_library(mock_db)

        assert result == [
            {
                "library_id": "libraries/alpha",
                "calibrated_count": 1,
                "not_calibrated_count": 1,
            },
            {
                "library_id": "libraries/beta",
                "calibrated_count": 1,
                "not_calibrated_count": 1,
            },
        ]
        mock_db.libraries.aggregate.assert_called_once_with("_id", limit=2)
        mock_db.libraries.get.assert_called_once_with(
            query_spec=ReadQuerySpec(
                collection_name="libraries",
                criteria=(QueryCriterion("_id", QueryOperator.IN, ["libraries/alpha", "libraries/beta"]),),
                pagination=PaginationSpec(limit=2),
            )
        )

    @pytest.mark.unit
    def test_get_calibration_status_by_library_returns_empty_list_when_no_libraries(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_states.file_has_state.side_effect = [[], []]
        mock_db.libraries.count.return_value = 0
        mock_db.libraries.aggregate.return_value = []

        result = get_calibration_status_by_library(mock_db)

        assert result == []
        mock_db.libraries.get.assert_not_called()
        mock_db.library_contains_file.get.assert_not_called()


class TestShortFileValidation:
    """Tests for short-file state validation helpers."""

    @pytest.mark.unit
    def test_find_short_files_missing_too_short_filters_duration_and_existing_state(self) -> None:
        mock_db = _make_mock_db()
        mock_db.libraries.library_contains_file.return_value = [
            {"_id": "library_files/1", "duration_seconds": 15},
            {"_id": "library_files/2", "duration_seconds": 45},
            {"_id": "library_files/3", "duration_seconds": 12},
            {"_id": "library_files/4", "duration_seconds": None},
        ]
        mock_db.file_has_state.get.return_value = [{"_from": "library_files/3"}]

        result = find_short_files_missing_too_short(mock_db, "main", min_duration_s=30)

        assert result == ["library_files/1"]
        mock_db.libraries.library_contains_file.assert_called_once_with("libraries/main", limit=None)
        mock_db.file_has_state.get.assert_called_once_with(_to=STATE_TOO_SHORT, limit=None)


class TestIncompleteTags:
    """Tests for ``get_files_with_incomplete_tags()``."""

    @pytest.mark.unit
    def test_preserves_head_matching_logic_for_matching_and_missing_heads(self) -> None:
        mock_db = _make_mock_db()
        expected_heads = [
            {"head_key": "mood", "labels": ["mood"], "model_key_for_tag": "modelA"},
            {"head_key": "energy", "labels": ["energy"], "model_key_for_tag": "modelB"},
        ]
        mock_db.file_states.file_has_state.return_value = [{"_id": "library_files/1", "_key": "1"}]
        mock_db.library_files.song_has_tags.by_ids.return_value = [
            {"start_id": "library_files/1", "v": {"name": "nom:mood_modelA_happy"}},
            {"start_id": "library_files/1", "v": {"name": "nom:energy_modelB_high"}},
            {"start_id": "library_files/1", "v": {"name": "nom:energy_other_model"}},
        ]

        result = get_files_with_incomplete_tags(mock_db, expected_heads, namespace_prefix="nom:")

        assert result == [
            {
                "file_id": "library_files/1",
                "file_key": "1",
                "library_id": None,
                "matched_count": 2,
                "missing_count": 0,
                "missing_heads": [],
            }
        ]
        mock_db.library_files.song_has_tags.by_ids.assert_called_once_with(
            ["library_files/1"],
            name_starts_with="nom:",
        )

    @pytest.mark.unit
    def test_scopes_incomplete_tag_results_to_library_and_returns_normalized_library_id(self) -> None:
        mock_db = _make_mock_db()
        expected_heads = [
            {"head_key": "mood", "labels": ["mood"], "model_key_for_tag": "modelA"},
            {"head_key": "energy", "labels": ["energy"], "model_key_for_tag": "modelB"},
        ]
        mock_db.file_states.file_has_state.return_value = [
            {"_id": "library_files/1", "_key": "1"},
            {"_id": "library_files/2", "_key": "2"},
        ]
        mock_db.library_contains_file.get.return_value = [{"_to": "library_files/2"}]
        mock_db.library_files.song_has_tags.by_ids.return_value = [
            {"start_id": "library_files/2", "v": {"name": "nom:mood_modelA_happy"}},
        ]

        result = get_files_with_incomplete_tags(mock_db, expected_heads, namespace_prefix="nom:", library_id="main")

        assert result == [
            {
                "file_id": "library_files/2",
                "file_key": "2",
                "library_id": "libraries/main",
                "matched_count": 1,
                "missing_count": 1,
                "missing_heads": ["energy"],
            }
        ]
        mock_db.library_contains_file.get.assert_called_once_with(_from="libraries/main", limit=None)
        mock_db.library_files.song_has_tags.by_ids.assert_called_once_with(
            ["library_files/2"],
            name_starts_with="nom:",
        )


class TestTransitionFileState:
    """Tests for ``transition_file_state()``."""

    @pytest.mark.unit
    def test_delegates_to_file_states_transition_for_valid_axis_pair(self) -> None:
        mock_db = _make_mock_db()
        file_ids = ["library_files/1", "library_files/2"]
        from_state = STATE_NOT_TAGGED
        to_state = STATE_TAGGED

        transition_file_state(mock_db, file_ids, from_state, to_state)

        mock_db.file_states.transition.assert_called_once_with(file_ids, from_state, to_state)
        mock_db.file_has_state.insert.assert_not_called()
        mock_db.file_has_state.delete.assert_not_called()
        mock_db.file_has_state.replace_targets.assert_not_called()

    @pytest.mark.unit
    def test_raises_value_error_for_invalid_axis_pair(self) -> None:
        mock_db = _make_mock_db()
        file_ids = ["library_files/1"]

        with pytest.raises(ValueError):
            transition_file_state(mock_db, file_ids, STATE_NOT_TAGGED, STATE_CALIBRATED)

        mock_db.file_states.transition.assert_not_called()


class TestBulkTransitions:
    """Tests for the bulk state transition helpers."""

    @pytest.mark.unit
    def test_bulk_set_not_calibrated_uses_transition_for_all_calibrated_files(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.get.return_value = [
            {"_from": "library_files/1"},
            {"_from": "library_files/2"},
        ]

        result = bulk_set_not_calibrated(mock_db)

        assert result == 2
        mock_db.file_has_state.get.assert_called_once_with(_to=STATE_CALIBRATED, limit=None)
        mock_db.file_states.transition.assert_called_once_with(
            ["library_files/1", "library_files/2"],
            STATE_CALIBRATED,
            STATE_NOT_CALIBRATED,
        )

    @pytest.mark.unit
    def test_bulk_set_tags_stale_filters_to_library_before_transition(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.get.return_value = [
            {"_from": "library_files/1"},
            {"_from": "library_files/2"},
        ]
        mock_db.library_contains_file.get.return_value = [{"_to": "library_files/2"}]

        result = bulk_set_tags_stale(mock_db, library_id="libraries/1")

        assert result == 1
        mock_db.file_states.transition.assert_called_once_with(
            ["library_files/2"],
            STATE_TAGS_CURRENT,
            STATE_TAGS_STALE,
        )
        mock_db.library_contains_file.get.assert_called_once_with(_from="libraries/1", limit=None)

    @pytest.mark.unit
    def test_bulk_set_not_vectors_extracted_skips_empty_transition(self) -> None:
        mock_db = _make_mock_db()

        result = bulk_set_not_vectors_extracted(mock_db)

        assert result == 0
        mock_db.file_states.transition.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_not_calibrated_returns_zero_and_skips_transition_when_no_calibrated_files(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.get.return_value = []

        result = bulk_set_not_calibrated(mock_db)

        assert result == 0
        mock_db.file_states.transition.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_tags_stale_transitions_all_tags_current_files_when_no_library_id(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.get.return_value = [
            {"_from": "library_files/1"},
            {"_from": "library_files/2"},
        ]

        result = bulk_set_tags_stale(mock_db)

        assert result == 2
        mock_db.file_states.transition.assert_called_once_with(
            ["library_files/1", "library_files/2"],
            STATE_TAGS_CURRENT,
            STATE_TAGS_STALE,
        )
        mock_db.library_contains_file.get.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_tags_stale_returns_zero_and_skips_transition_when_no_tags_current_files(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.get.return_value = []

        result = bulk_set_tags_stale(mock_db)

        assert result == 0
        mock_db.file_states.transition.assert_not_called()

    @pytest.mark.unit
    def test_bulk_set_not_vectors_extracted_transitions_all_vector_extracted_files(self) -> None:
        mock_db = _make_mock_db()
        mock_db.file_has_state.get.return_value = [{"_from": "library_files/7"}]

        result = bulk_set_not_vectors_extracted(mock_db)

        assert result == 1
        mock_db.file_states.transition.assert_called_once_with(
            ["library_files/7"],
            STATE_VECTORS_EXTRACTED,
            STATE_NOT_VECTORS_EXTRACTED,
        )
