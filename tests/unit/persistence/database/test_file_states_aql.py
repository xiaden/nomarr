"""Focused tests for canonical ``FileStatesAqlOperations`` helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.helpers.constants.file_states import ALL_STATE_VERTICES, STATE_NOT_TAGGED, STATE_TAGGED, STATE_TAGS_STALE
from nomarr.persistence.database.file_states_aql import FileStatesAqlOperations

_EXPECTED_NEGATIVE_FILE_STATES = tuple(
    state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_") or state == STATE_TAGS_STALE
)


@pytest.mark.unit
@pytest.mark.mocked
def test_bootstrap_file_states_adds_negative_states_for_each_unique_file() -> None:
    db = MagicMock()
    ops = FileStatesAqlOperations(db)
    file_ids = ["library_files/1", "library_files/2"]

    with patch.object(ops, "add_file_state_edge") as add_edge:
        ops.bootstrap_file_states(file_ids)

    assert add_edge.call_args_list == [
        *(call("library_files/1", state) for state in _EXPECTED_NEGATIVE_FILE_STATES),
        *(call("library_files/2", state) for state in _EXPECTED_NEGATIVE_FILE_STATES),
    ]


@pytest.mark.unit
@pytest.mark.mocked
def test_bootstrap_file_states_deduplicates_duplicate_file_ids() -> None:
    db = MagicMock()
    ops = FileStatesAqlOperations(db)

    with patch.object(ops, "add_file_state_edge") as add_edge:
        ops.bootstrap_file_states(["library_files/1", "library_files/1", "library_files/2"])

    processed_file_ids = [mock_call.args[0] for mock_call in add_edge.call_args_list]

    assert processed_file_ids.count("library_files/1") == len(_EXPECTED_NEGATIVE_FILE_STATES)
    assert processed_file_ids.count("library_files/2") == len(_EXPECTED_NEGATIVE_FILE_STATES)
    assert len(add_edge.call_args_list) == 2 * len(_EXPECTED_NEGATIVE_FILE_STATES)


@pytest.mark.unit
@pytest.mark.mocked
def test_mark_files_tagged_returns_early_for_empty_input() -> None:
    db = MagicMock()
    ops = FileStatesAqlOperations(db)

    with patch.object(ops, "transition_file_states") as transition_states:
        ops.mark_files_tagged([])

    transition_states.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_mark_files_tagged_transitions_deduplicated_files_to_tagged() -> None:
    db = MagicMock()
    ops = FileStatesAqlOperations(db)

    with patch.object(ops, "transition_file_states") as transition_states:
        ops.mark_files_tagged(["library_files/1", "library_files/1", "library_files/2"])

    transition_states.assert_called_once_with(
        ["library_files/1", "library_files/2"],
        STATE_NOT_TAGGED,
        STATE_TAGGED,
    )
