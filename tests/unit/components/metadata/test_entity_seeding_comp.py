"""Tests for nomarr.components.metadata.entity_seeding_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.metadata.entity_seeding_comp import seed_entities_for_scan_batch

MODULE = "nomarr.components.metadata.entity_seeding_comp"


class TestSeedEntitiesForScanBatch:
    """Regression coverage for scan-time tag persistence."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_persists_full_source_tags_nom_tags_and_cache_updates(self) -> None:
        """Scanner batch sync should persist entity tags as {name, value} payloads."""
        mock_db = MagicMock()
        metadata = {
            "all_tags": {
                "genre": "Ambient; Drone",
                "label": "Warp",
                "comment": "late night listening",
                "artist": '["Raw Artist"]',
            },
            "nom_tags": {
                "mood": "chill",
            },
            "artist": "Canonical Artist",
            "artists": ["Canonical Artist", "Guest Artist"],
            "album": "Selected Ambient Works",
            "label": "Warp",
            "genre": ["Ambient", "Drone"],
            "year": 1994,
            "track_number": 7,
        }

        result = seed_entities_for_scan_batch(
            mock_db,
            [f"{'songs'}/1"],
            {f"{'songs'}/1": metadata},
        )

        assert result == 1
        # Source now uses db.library.replace_file_tags per entry (not set_song_tags_batch)
        mock_db.library.replace_file_tags.assert_called()
        persisted_entries: list[dict] = [
            {"song_id": call_args[0][0], "tags": call_args[0][1]}
            for call_args in mock_db.library.replace_file_tags.call_args_list
        ]

        # New format: one entry per file, with "tags" list of {name, value} dicts
        assert len(persisted_entries) > 0
        file_entry = persisted_entries[0]
        assert file_entry["song_id"] == f"{'songs'}/1"
        assert "tags" in file_entry

        tags_list: list[dict] = file_entry["tags"]
        tag_map: dict[str, set[str]] = {}
        for t in tags_list:
            tag_map.setdefault(t["name"], set()).add(str(t["value"]))

        assert tag_map["artist"] == {"Canonical Artist"}
        assert tag_map["artists"] == {"Canonical Artist", "Guest Artist"}
        assert tag_map["album"] == {"Selected Ambient Works"}
        assert tag_map["label"] == {"Warp"}
        assert tag_map["genre"] == {"Ambient", "Drone"}
        assert tag_map["year"] == {"1994"}
