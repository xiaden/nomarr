"""Tests for nomarr.components.metadata.entity_seeding_comp module."""

from __future__ import annotations

import pytest

from nomarr.components.metadata.entity_seeding_comp import (
    build_song_tag_assignments,
    extract_entity_tag_mapping,
)


class TestBuildSongTagAssignments:
    """Tests for the locator-addressed assignment command derivation."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_flattens_name_and_value_from_entity_tags(self) -> None:
        """Entity tags flatten into ``(name, value)`` assignment commands."""
        assignments = build_song_tag_assignments(
            {
                "artist": "Canonical Artist",
                "artists": ["Canonical Artist", "Guest Artist"],
                "album": "Selected Ambient Works",
                "title": "Xtal",
                "label": "Warp",
                "genre": ["Ambient", "Drone"],
                "year": 1994,
            }
        )

        assert [(a.name, a.value) for a in assignments] == [
            ("artist", "Canonical Artist"),
            ("artists", "Canonical Artist"),
            ("artists", "Guest Artist"),
            ("album", "Selected Ambient Works"),
            ("title", "Xtal"),
            ("label", "Warp"),
            ("genre", "Ambient"),
            ("genre", "Drone"),
            ("year", 1994),
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_empty_tags_returns_empty_list(self) -> None:
        """No entity fields → no assignment commands."""
        assert build_song_tag_assignments({}) == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_non_entity_fields_are_ignored(self) -> None:
        """Unrelated metadata does not produce assignments."""
        assignments = build_song_tag_assignments({"bpm": 120, "key": "A"})

        assert assignments == []


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
            "title": "Xtal",
            "label": "Warp",
            "genre": ["Ambient", "Drone"],
            "year": 1994,
        }

        mapping = extract_entity_tag_mapping(metadata)

        assert mapping["artist"] == ["Canonical Artist"]
        assert mapping["artists"] == ["Canonical Artist", "Guest Artist"]
        assert mapping["album"] == ["Selected Ambient Works"]
        assert mapping["title"] == ["Xtal"]
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

        # ``artist`` derives ``artists`` too, while unrelated fields are dropped.
        assert set(mapping.keys()) == {"artist", "artists", "title", "genre"}
        assert mapping["title"] == ["Some Title"]
        assert mapping["artist"] == ["Artist"]
        assert mapping["artists"] == ["Artist"]
        assert mapping["genre"] == ["Rock"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_empty_metadata_returns_empty_mapping(self) -> None:
        """No entity fields → empty dict."""
        assert extract_entity_tag_mapping({}) == {}
