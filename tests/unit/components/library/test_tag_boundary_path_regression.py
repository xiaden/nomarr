"""Regression: both song-tag query paths produce identical FileTag data.

Pins the CONTRACTS.md invariant that the two library projection paths
(``song_tags_comp.get_song_tags_with_path`` and the ``_tags_for_song`` /
``_hydrate_files_with_tags`` projection in ``library_song_query_comp``) produce
identical ``FileTag`` objects — including ``tag_type`` — from the same
row-shaped input, because both delegate to the shared
``nomarr.components.library.tag_mapping_comp`` mapper.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_song_query_comp import _tags_for_song
from nomarr.components.library.song_tags_comp import get_song_tags_with_path


class TestSongTagPathsProduceIdenticalFileTags:
    """Both projection paths yield the same FileTag data for the same rows."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_both_paths_emit_identical_file_tags(self) -> None:
        rows = [
            {"name": "genre", "value": "rock", "namespace": ""},
            {"name": "nom:mood", "value": "calm", "namespace": "nom"},
            {"name": "tempo", "value": 120, "namespace": ""},
        ]

        db_a = MagicMock()
        db_a.library.get_song.return_value = {"path": "D:/Music/song.flac"}
        db_a.library.list_tags_for_song.return_value = rows
        from_path = get_song_tags_with_path(db_a, 1)
        assert from_path is not None

        db_b = MagicMock()
        db_b.library.list_tags_for_song.return_value = rows
        via_internal = _tags_for_song(db_b, 1)

        assert list(from_path["tags"]) == via_internal
        # Every produced tag carries the required tag_type field.
        for tag in via_internal:
            assert tag.tag_type in ("string", "float")
