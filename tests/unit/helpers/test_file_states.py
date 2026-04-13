"""Unit tests for nomarr.helpers.constants.file_states module."""

from __future__ import annotations

import pytest

from nomarr.helpers.constants.file_states import (
    ALL_STATE_VERTICES,
    AXIS_PAIRS,
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_TAGGED,
    STATE_TAGGED,
)


class TestFileStateConstants:
    """Tests for canonical file-state vertex constants."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_all_state_vertices_contains_expected_count(self) -> None:
        assert len(ALL_STATE_VERTICES) == 16

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_all_state_vertices_are_file_states_ids(self) -> None:
        assert all(vertex.startswith("file_states/") for vertex in ALL_STATE_VERTICES)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_no_duplicates_in_all_state_vertices(self) -> None:
        assert len(ALL_STATE_VERTICES) == len(set(ALL_STATE_VERTICES))


class TestAxisPairs:
    """Tests for AXIS_PAIRS."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_axis_pairs_has_eight_axes(self) -> None:
        assert len(AXIS_PAIRS) == 8

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_each_axis_pair_contains_two_items(self) -> None:
        assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in AXIS_PAIRS.values())

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_axis_pairs_reference_valid_state_vertices(self) -> None:
        all_vertices = set(ALL_STATE_VERTICES)

        assert all(first in all_vertices and second in all_vertices for first, second in AXIS_PAIRS.values())

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_axis_pairs_poles_are_opposites(self) -> None:
        assert AXIS_PAIRS["tagged"] == (STATE_TAGGED, STATE_NOT_TAGGED)
        assert AXIS_PAIRS["errored"] == (STATE_ERRORED, STATE_NOT_ERRORED)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_errored_axis_exists(self) -> None:
        assert "errored" in AXIS_PAIRS
