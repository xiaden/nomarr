"""Tests for nomarr.components.metadata.entity_seeding_comp module."""

from __future__ import annotations

import pytest

from nomarr.components.metadata.entity_seeding_comp import extract_entity_tag_mapping


class TestExtractEntityTagMapping:
    """Tests for the hydration-ready entity tag mapping derivation."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_builds_mapping_from_raw_metadata(self) -> None:
        """Entity fields are flattened into name → value-list mapping."""
        metadata = {
            "artist": "Canonical Artist",
            "artists": ["Canonical Artist", "Guest Artist"],
            "album": "Selected Ambient Works",
            "label": "Warp",
            "genre": ["Ambient", "Drone"],
            "year": 1994,
        }

        mapping = extract_entity_tag_mapping(metadata)

        assert mapping["artist"] == ["Canonical Artist"]
        assert mapping["artists"] == ["Canonical Artist", "Guest Artist"]
        assert mapping["album"] == ["Selected Ambient Works"]
        assert mapping["label"] == ["Warp"]
        assert mapping["genre"] == ["Ambient", "Drone"]
        assert mapping["year"] == [1994]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_ignores_non_entity_fields(self) -> None:
        """Only entity tag keys are included; other metadata is dropped."""
        metadata = {
            "artist": "Artist",
            "genre": ["Rock"],
            "title": "Some Title",
            "bpm": 120,
            "key": "A",
        }

        mapping = extract_entity_tag_mapping(metadata)

        # ``artist`` derives ``artists`` too, but title/bpm/key are dropped.
        assert set(mapping.keys()) == {"artist", "artists", "genre"}
        assert mapping["artist"] == ["Artist"]
        assert mapping["artists"] == ["Artist"]
        assert mapping["genre"] == ["Rock"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_empty_metadata_returns_empty_mapping(self) -> None:
        """No entity fields → empty dict."""
        assert extract_entity_tag_mapping({}) == {}
