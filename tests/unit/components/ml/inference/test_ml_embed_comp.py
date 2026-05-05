"""Tests for ``nomarr.components.ml.inference.ml_embed_comp.aggregate_segment_scores_weighted``."""

from __future__ import annotations

import numpy as np
import pytest

from nomarr.components.ml.inference.ml_embed_comp import aggregate_segment_scores_weighted


@pytest.mark.unit
class TestAggregateSegmentScoresWeighted:
    """Tests for aggregate_segment_scores_weighted()."""

    # ------------------------------------------------------------------
    # Basic shape and type contracts
    # ------------------------------------------------------------------

    def test_returns_1d_float32_array(self) -> None:
        scores = np.array([[0.9, 0.1], [0.8, 0.2], [0.85, 0.15]], dtype=np.float32)
        result = aggregate_segment_scores_weighted(scores)
        assert result.ndim == 1
        assert result.dtype == np.float32

    def test_output_length_matches_num_labels(self) -> None:
        rng = np.random.default_rng(seed=42)
        scores = rng.random((10, 4)).astype(np.float32)
        result = aggregate_segment_scores_weighted(scores)
        assert len(result) == 4

    def test_single_segment_returns_that_segment(self) -> None:
        scores = np.array([[0.7, 0.3]], dtype=np.float32)
        result = aggregate_segment_scores_weighted(scores)
        np.testing.assert_allclose(result, [0.7, 0.3], atol=1e-6)

    def test_1d_input_treated_as_single_segment(self) -> None:
        scores = np.array([0.7, 0.3], dtype=np.float32)
        result = aggregate_segment_scores_weighted(scores)
        np.testing.assert_allclose(result, [0.7, 0.3], atol=1e-6)

    # ------------------------------------------------------------------
    # Dominant side selection — the core correctness test
    # ------------------------------------------------------------------

    def test_instrumental_dominant_suppresses_has_vocals(self) -> None:
        """Classical/instrumental song: most segments favour label 0 (instrumental).

        With 70% of segments at (0.9, 0.1) and 30% at (0.1, 0.9), the dominant
        side for label 0 is the 'no-vocals' side.  The result should be close to
        0.9 for label 0, not dragged toward 0.5 by the noisy minority.
        """
        instrumental = np.tile([0.9, 0.1], (7, 1)).astype(np.float32)
        vocal_noise = np.tile([0.1, 0.9], (3, 1)).astype(np.float32)
        scores = np.vstack([instrumental, vocal_noise])
        result = aggregate_segment_scores_weighted(scores)
        # Label 0 dominant side is "no-vocals" (>70% weight), should be ~0.9
        assert result[0] > 0.7, f"Label 0 (instrumental) should dominate: got {result[0]:.3f}"
        # Label 1 (has vocals) dominant side is "no-vocals" — should be low
        assert result[1] < 0.3, f"Label 1 (has vocals) should be suppressed: got {result[1]:.3f}"

    def test_vocal_dominant_produces_high_vocal_score(self) -> None:
        """Song that is primarily vocal should produce a high 'has vocals' score."""
        vocal = np.tile([0.1, 0.9], (8, 1)).astype(np.float32)
        instrumental_noise = np.tile([0.9, 0.1], (2, 1)).astype(np.float32)
        scores = np.vstack([vocal, instrumental_noise])
        result = aggregate_segment_scores_weighted(scores)
        assert result[1] > 0.7, f"Label 1 (has vocals) should dominate: got {result[1]:.3f}"

    # ------------------------------------------------------------------
    # Oscillation suppression
    # ------------------------------------------------------------------

    def test_oscillating_model_suppressed_to_midpoint(self) -> None:
        """A model that constantly switches should output ~0.5 for the label."""
        # Alternating confident yes/no — each "side" gets ~50% of weight
        yes = np.tile([0.9, 0.1], (5, 1)).astype(np.float32)
        no = np.tile([0.1, 0.9], (5, 1)).astype(np.float32)
        # Interleave so the alternation is clear to the rolling-average grouper
        alternating = np.empty((10, 2), dtype=np.float32)
        alternating[0::2] = yes
        alternating[1::2] = no
        result = aggregate_segment_scores_weighted(
            alternating,
            group_change_threshold=0.05,  # tight threshold → many groups
            oscillation_fraction=0.40,
        )
        # Both labels should be near 0.5 (neither side dominates)
        for j in range(2):
            assert abs(result[j] - 0.5) < 0.2, (
                f"Label {j} should be near 0.5 for oscillating model, got {result[j]:.3f}"
            )

    # ------------------------------------------------------------------
    # Silence filtering
    # ------------------------------------------------------------------

    def test_silence_segments_are_excluded(self) -> None:
        """Near-zero segments should not affect the dominant-side decision."""
        # 8 clearly instrumental segments + 2 near-zero (silence) segments
        instrumental = np.tile([0.9, 0.1], (8, 1)).astype(np.float32)
        silence = np.tile([0.01, 0.01], (2, 1)).astype(np.float32)
        scores = np.vstack([instrumental, silence])
        result = aggregate_segment_scores_weighted(scores, silence_threshold=0.05)
        # Silence segments excluded — dominant side is instrumental
        assert result[0] > 0.7

    def test_all_silence_falls_back_to_trimmed_mean(self) -> None:
        """When all segments are below threshold and min_active_fraction kicks in,
        the function must still return a sensible result (no crash, shape correct)."""
        scores = np.tile([0.02, 0.02], (5, 1)).astype(np.float32)
        result = aggregate_segment_scores_weighted(scores, silence_threshold=0.9)
        assert result.shape == (2,)
        assert np.all(np.isfinite(result))

    # ------------------------------------------------------------------
    # Group-based weighting
    # ------------------------------------------------------------------

    def test_large_group_outweighs_small_group(self) -> None:
        """A small high-vocal section should not override a large instrumental section."""
        # 15 segments clearly instrumental, 2 segments clearly vocal
        instrumental = np.tile([0.95, 0.05], (15, 1)).astype(np.float32)
        vocal_section = np.tile([0.05, 0.95], (2, 1)).astype(np.float32)
        scores = np.vstack([instrumental, vocal_section])
        result = aggregate_segment_scores_weighted(scores)
        # Instrumental group far outweighs the vocal section
        assert result[0] > 0.8

    def test_uniform_scores_return_that_value(self) -> None:
        """All segments identical → aggregation should return that value."""
        scores = np.tile([0.8, 0.2], (6, 1)).astype(np.float32)
        result = aggregate_segment_scores_weighted(scores)
        np.testing.assert_allclose(result[0], 0.8, atol=0.05)
        np.testing.assert_allclose(result[1], 0.2, atol=0.05)


@pytest.mark.unit
class TestAggregateSegmentScoresWeightedRegressionMode:
    """Tests for aggregate_segment_scores_weighted with decision_midpoint=None (regression mode)."""

    def test_regression_mode_dominant_side_uses_data_mean_as_boundary(self) -> None:
        """When decision_midpoint=None, boundary = per-label mean of active segments.

        A signal that is mostly high (0.7) with a brief low episode (0.2) should
        return a score near the high section's value since the high section dominates
        relative to the data mean.
        """
        high = np.tile([[0.7]], (8, 1)).astype(np.float32)
        low = np.tile([[0.2]], (2, 1)).astype(np.float32)
        scores = np.vstack([high, low])
        result = aggregate_segment_scores_weighted(scores, decision_midpoint=None)
        # mean ≈ 0.62; high side (0.7 > 0.62) dominates → result near 0.7
        assert result[0] > 0.6, f"Expected high side to dominate, got {result[0]:.3f}"

    def test_regression_mode_oscillation_suppresses_to_data_mean(self) -> None:
        """Constant oscillation in regression mode suppresses to the data mean, not 0.5."""
        high = np.tile([[0.8]], (5, 1)).astype(np.float32)
        low = np.tile([[0.2]], (5, 1)).astype(np.float32)
        # Interleave so the grouper sees many group boundaries
        alternating = np.empty((10, 1), dtype=np.float32)
        alternating[0::2] = high
        alternating[1::2] = low
        expected_mean = float(np.mean(alternating))  # ~0.5
        result = aggregate_segment_scores_weighted(
            alternating,
            decision_midpoint=None,
            group_change_threshold=0.05,
            oscillation_fraction=0.40,
        )
        # Suppressed to boundary (≈ data mean ≈ 0.5)
        assert abs(result[0] - expected_mean) < 0.15, (
            f"Expected result near data mean {expected_mean:.3f}, got {result[0]:.3f}"
        )

    def test_regression_mode_boundary_is_independent_of_fixed_0_5(self) -> None:
        """Regression mode uses data mean, not 0.5.

        A signal hovering around 0.8 should have its dominant side computed
        relative to ~0.8, not 0.5.  Both groups are above 0.5, so a fixed-0.5
        decision would give the wrong dominant side (all "yes"), whereas the
        data-mean boundary correctly separates the small dip from the main body.
        """
        main = np.tile([[0.85]], (8, 1)).astype(np.float32)
        dip = np.tile([[0.65]], (2, 1)).astype(np.float32)
        scores = np.vstack([main, dip])
        # data mean ≈ 0.81; main (0.85) is above boundary; dip (0.65) is below
        result_regression = aggregate_segment_scores_weighted(scores, decision_midpoint=None)
        result_fixed = aggregate_segment_scores_weighted(scores, decision_midpoint=0.5)
        # Regression: dominant side is "main" (0.85), result ≈ 0.85
        assert result_regression[0] > 0.80, (
            f"Regression should use main section (0.85), got {result_regression[0]:.3f}"
        )
        # Fixed-0.5: both sections are above 0.5, so all weight is on "yes" side
        # weighted mean of [0.85*8 + 0.65*2] / 10 ≈ 0.81 → also dominates, but
        # the score is the weighted mean of ALL groups (all on the same side)
        assert result_fixed[0] > 0.75, (
            f"Fixed-0.5 should also be high (all groups above 0.5), got {result_fixed[0]:.3f}"
        )

    def test_regression_mode_shape_matches_fixed_mode(self) -> None:
        """Both modes must return the same output shape."""
        scores = np.random.default_rng(seed=7).random((12, 3)).astype(np.float32)
        r_fixed = aggregate_segment_scores_weighted(scores, decision_midpoint=0.5)
        r_auto = aggregate_segment_scores_weighted(scores, decision_midpoint=None)
        assert r_fixed.shape == r_auto.shape == (3,)
        assert r_fixed.dtype == r_auto.dtype == np.float32
