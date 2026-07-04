"""Unit tests for ``write_file_tags_wf`` — tag filtering and path resolution."""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.tags_dto import Tag, Tags
from nomarr.workflows.processing.write_file_tags_wf import _filter_tags_for_mode


@pytest.mark.unit
class TestFilterTagsForMode:
    """Tests for ``_filter_tags_for_mode`` mode filtering logic."""

    @staticmethod
    def _make_tags(*keys: str) -> Tags:
        """Build a Tags DTO from tag key strings."""
        return Tags(items=tuple(Tag(key=k, value=None) for k in keys))

    def test_none_mode_returns_empty(self) -> None:
        """target_mode='none' always returns an empty Tags."""
        tags = self._make_tags("mood-strict", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "none", has_calibration=True)
        assert len(result.items) == 0

    def test_full_mode_with_calibration_returns_all_tags(self) -> None:
        """target_mode='full' + has_calibration returns all tags."""
        tags = self._make_tags("mood-strict", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "full", has_calibration=True)
        assert len(result.items) == 3
        keys = {t.key for t in result.items}
        assert keys == {"mood-strict", "genre", "tempo"}

    def test_full_mode_without_calibration_filters_mood_tags(self) -> None:
        """target_mode='full' + no calibration filters out mood-prefixed tags."""
        tags = self._make_tags("mood-strict", "genre", "tempo", "mood-loose")
        result = _filter_tags_for_mode(tags, "full", has_calibration=False)
        assert len(result.items) == 2
        keys = {t.key for t in result.items}
        assert keys == {"genre", "tempo"}

    def test_minimal_mode_with_calibration_returns_only_mood_tags(self) -> None:
        """target_mode='minimal' + has_calibration returns only mood-prefixed tags."""
        tags = self._make_tags("mood-strict", "mood-regular", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=True)
        assert len(result.items) == 2
        keys = {t.key for t in result.items}
        assert keys == {"mood-strict", "mood-regular"}

    def test_minimal_mode_without_calibration_returns_empty(self) -> None:
        """target_mode='minimal' + no calibration: mood tags filtered, then mood filter finds nothing."""
        tags = self._make_tags("mood-strict", "mood-regular", "genre")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=False)
        assert len(result.items) == 0

    def test_minimal_mode_ignores_non_mood_tags_even_with_calibration(self) -> None:
        """Only mood-prefixed tags pass minimal mode, regardless of calibration."""
        tags = self._make_tags("mood-strict", "nom-valence", "effnet_genre")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=True)
        keys = {t.key for t in result.items}
        assert keys == {"mood-strict"}

    def test_empty_input_tags_returns_empty(self) -> None:
        """Empty input Tags stay empty in all modes."""
        tags = Tags(items=())
        for mode in ("none", "minimal", "full"):
            for calib in (True, False):
                result = _filter_tags_for_mode(tags, mode, has_calibration=calib)
                assert len(result.items) == 0
