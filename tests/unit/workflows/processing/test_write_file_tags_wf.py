"""Unit tests for ``write_file_tags_wf`` — tag filtering and path resolution."""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.workflows.processing.write_file_tags_wf import _filter_tags_for_mode


@pytest.mark.unit
class TestFilterTagsForMode:
    """Tests for ``_filter_tags_for_mode`` mode filtering logic."""

    @staticmethod
    def _make_tags(*keys: str) -> Tags:
        """Build a Tags DTO from tag key strings."""
        return Tags(items=tuple(Tag(name=k, values=("v",)) for k in keys))

    def test_none_mode_returns_none(self) -> None:
        """target_mode='none' always returns None (clear the namespace)."""
        tags = self._make_tags("mood-strict", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "none", has_calibration=True)
        assert result is None

    def test_full_mode_with_calibration_returns_all_tags(self) -> None:
        """target_mode='full' + has_calibration returns all tags."""
        tags = self._make_tags("mood-strict", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "full", has_calibration=True)
        assert len(result.items) == 3
        keys = {t.name for t in result.items}
        assert keys == {"mood-strict", "genre", "tempo"}

    def test_full_mode_without_calibration_filters_mood_tags(self) -> None:
        """target_mode='full' + no calibration filters out mood-prefixed tags."""
        tags = self._make_tags("mood-strict", "genre", "tempo", "mood-loose")
        result = _filter_tags_for_mode(tags, "full", has_calibration=False)
        assert len(result.items) == 2
        keys = {t.name for t in result.items}
        assert keys == {"genre", "tempo"}

    def test_minimal_mode_with_calibration_returns_only_mood_tags(self) -> None:
        """target_mode='minimal' + has_calibration returns only mood-prefixed tags."""
        tags = self._make_tags("mood-strict", "mood-regular", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=True)
        assert len(result.items) == 2
        keys = {t.name for t in result.items}
        assert keys == {"mood-strict", "mood-regular"}

    def test_minimal_mode_without_calibration_returns_none(self) -> None:
        """target_mode='minimal' + no calibration: mood tags filtered, then mood filter finds nothing -> None."""
        tags = self._make_tags("mood-strict", "mood-regular", "genre")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=False)
        assert result is None

    def test_minimal_mode_ignores_non_mood_tags_even_with_calibration(self) -> None:
        """Only mood-prefixed tags pass minimal mode, regardless of calibration."""
        tags = self._make_tags("mood-strict", "nom-valence", "effnet_genre")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=True)
        keys = {t.name for t in result.items}
        assert keys == {"mood-strict"}

    def test_none_input_tags_returns_none(self) -> None:
        """None input Tags yield None (clear) in all modes."""
        tags: Tags | None = None
        for mode in ("none", "minimal", "full"):
            for calib in (True, False):
                result = _filter_tags_for_mode(tags, mode, has_calibration=calib)
                assert result is None
