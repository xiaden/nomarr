"""Unit tests for vector_params_helper."""

from __future__ import annotations

import pytest

from nomarr.helpers.vector_params_helper import (
    VectorSearchDescription,
    compute_nlists,
    compute_nprobe,
    describe_search_params,
)

# ---------------------------------------------------------------------------
# compute_nlists
# ---------------------------------------------------------------------------


class TestComputeNlists:
    @pytest.mark.unit
    def test_zero_docs_returns_floor(self) -> None:
        assert compute_nlists(0) == 10

    @pytest.mark.unit
    def test_negative_docs_returns_floor(self) -> None:
        assert compute_nlists(-5) == 10

    @pytest.mark.unit
    def test_small_library_hits_floor(self) -> None:
        # 100 docs / 15 = 6 -> clamped to 10
        assert compute_nlists(100) == 10

    @pytest.mark.unit
    def test_typical_library(self) -> None:
        # 1500 docs / 15 = 100
        assert compute_nlists(1500) == 100

    @pytest.mark.unit
    def test_large_library_hits_ceil(self) -> None:
        # 100_000 docs / 15 = 6666 -> clamped to 4000
        assert compute_nlists(100_000) == 4000

    @pytest.mark.unit
    def test_custom_group_size(self) -> None:
        # 1500 docs / 50 = 30
        assert compute_nlists(1500, group_size=50) == 30

    @pytest.mark.unit
    def test_group_size_one(self) -> None:
        # 500 docs / 1 = 500
        assert compute_nlists(500, group_size=1) == 500

    @pytest.mark.unit
    def test_group_size_larger_than_docs(self) -> None:
        # 10 docs / 100 = 0 -> clamped to 10
        assert compute_nlists(10, group_size=100) == 10


# ---------------------------------------------------------------------------
# compute_nprobe
# ---------------------------------------------------------------------------


class TestComputeNprobe:
    @pytest.mark.unit
    def test_zero_nlists_returns_one(self) -> None:
        assert compute_nprobe(0) == 1

    @pytest.mark.unit
    def test_negative_nlists_returns_one(self) -> None:
        assert compute_nprobe(-5) == 1

    @pytest.mark.unit
    def test_default_thoroughness(self) -> None:
        # 100 nlists * 10% = 10
        assert compute_nprobe(100) == 10

    @pytest.mark.unit
    def test_fifty_pct_thoroughness(self) -> None:
        # 100 nlists * 50% = 50
        assert compute_nprobe(100, thoroughness_pct=50) == 50

    @pytest.mark.unit
    def test_hundred_pct_thoroughness(self) -> None:
        # 100 nlists * 100% = 100 (all cells)
        assert compute_nprobe(100, thoroughness_pct=100) == 100

    @pytest.mark.unit
    def test_one_pct_thoroughness(self) -> None:
        # 200 nlists * 1% = 2
        assert compute_nprobe(200, thoroughness_pct=1) == 2

    @pytest.mark.unit
    def test_small_nlists_clamps_to_one(self) -> None:
        # 5 nlists * 1% = 0 -> clamped to 1
        assert compute_nprobe(5, thoroughness_pct=1) == 1

    @pytest.mark.unit
    def test_nprobe_never_exceeds_nlists(self) -> None:
        assert compute_nprobe(10, thoroughness_pct=100) == 10
        assert compute_nprobe(10, thoroughness_pct=200) <= 10


# ---------------------------------------------------------------------------
# describe_search_params
# ---------------------------------------------------------------------------


class TestDescribeSearchParams:
    @pytest.mark.unit
    def test_typical_case(self) -> None:
        result = describe_search_params(1500, group_size=15, thoroughness_pct=10)
        assert isinstance(result, dict)
        assert result["num_groups"] == 100  # 1500 / 15
        assert result["groups_searched"] == 10  # 100 * 10%
        assert result["songs_per_group"] == 15  # 1500 / 100
        assert result["songs_checked"] == 150  # 10 * 15
        assert result["pct_searched"] == pytest.approx(10.0)

    @pytest.mark.unit
    def test_empty_library(self) -> None:
        result = describe_search_params(0, group_size=15, thoroughness_pct=10)
        assert result["num_groups"] == 10
        assert result["pct_searched"] == 0.0

    @pytest.mark.unit
    def test_pct_searched_capped_at_100(self) -> None:
        result = describe_search_params(100, group_size=5, thoroughness_pct=100)
        assert result["pct_searched"] <= 100.0

    @pytest.mark.unit
    def test_songs_checked_capped_at_doc_count(self) -> None:
        result = describe_search_params(100, group_size=5, thoroughness_pct=100)
        assert result["songs_checked"] <= 100

    @pytest.mark.unit
    def test_return_type_matches_typeddict(self) -> None:
        result = describe_search_params(1000, group_size=15, thoroughness_pct=10)
        expected_keys = set(VectorSearchDescription.__annotations__)
        assert set(result.keys()) == expected_keys
