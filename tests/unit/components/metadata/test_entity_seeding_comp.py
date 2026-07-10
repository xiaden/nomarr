"""Tests for nomarr.components.metadata.entity_seeding_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.metadata.entity_seeding_comp import seed_entities_for_scan_batch
from nomarr.persistence.schema import CollectionNames

MODULE = "nomarr.components.metadata.entity_seeding_comp"


class TestSeedEntitiesForScanBatch:
    """Regression coverage for scan-time tag persistence."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_persists_full_source_tags_nom_tags_and_cache_updates(self) -> None:
        """Scanner batch sync should retain raw source tags, not only Nomarr tags."""
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
            [f"{CollectionNames.LIBRARY_FILES.value}/1"],
            {f"{CollectionNames.LIBRARY_FILES.value}/1": metadata},
        )

        assert result == 1
        mock_db.tags.set_song_tags_batch.assert_called_once()
        persisted_entries = mock_db.tags.set_song_tags_batch.call_args.args[0]
        persisted_map = {
            entry["rel"]: entry["values"]
            for entry in persisted_entries
            if entry["song_id"] == f"{CollectionNames.LIBRARY_FILES.value}/1"
        }

        assert persisted_map["label"] == ["Warp"]
        assert persisted_map["genre"] == ["Ambient", "Drone"]
        assert persisted_map["year"] == [1994]
        assert persisted_map["artist"] == ["Canonical Artist"]
        assert persisted_map["artists"] == ["Canonical Artist", "Guest Artist"]
        assert persisted_map["album"] == ["Selected Ambient Works"]
