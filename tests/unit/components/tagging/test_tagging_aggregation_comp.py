"""Tests for nomarr.components.tagging.tagging_aggregation_comp module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from nomarr.components.tagging.tagging_aggregation_comp import aggregate_mood_tags
from nomarr.helpers.dto.ml_dto import HeadOutput


def _head_output(*, label: str, value: float, tier: str | None) -> HeadOutput:
    """Build a minimal HeadOutput for aggregation tests."""
    return HeadOutput(
        head=cast("Any", SimpleNamespace()),
        model_key=f"model:test:{label}:none:0",
        label=label,
        value=value,
        tier=tier,
        calibration_id=None,
    )


class TestAggregateMoodTags:
    """Tests for ``aggregate_mood_tags()``."""

    @pytest.mark.unit
    def test_returns_none_when_no_head_outputs(self) -> None:
        assert aggregate_mood_tags([]) is None

    @pytest.mark.unit
    def test_returns_none_when_no_tiered_mood_outputs(self) -> None:
        # Untiered outputs never form mood tags.
        result = aggregate_mood_tags([_head_output(label="happy", value=0.8, tier=None)])
        assert result is None

    @pytest.mark.unit
    def test_returns_tags_for_tiered_mood_outputs(self) -> None:
        result = aggregate_mood_tags([_head_output(label="happy", value=0.8, tier="high")])
        assert result is not None
        assert result.to_dict() == {
            "mood-strict": ("happy",),
            "mood-regular": ("happy",),
            "mood-loose": ("happy",),
        }

    @pytest.mark.unit
    def test_builds_inclusive_tiers_across_strict_and_regular(self) -> None:
        result = aggregate_mood_tags(
            [
                _head_output(label="happy", value=0.8, tier="high"),
                _head_output(label="calm", value=0.6, tier="medium"),
            ]
        )
        assert result is not None
        assert result.to_dict() == {
            "mood-strict": ("happy",),
            "mood-regular": ("calm", "happy"),
            "mood-loose": ("calm", "happy"),
        }
