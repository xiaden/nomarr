"""
Unit tests for nomarr.components.tagging.tag_normalization_comp module.

Tests tag normalization functions for different audio formats.
"""

import pytest

from nomarr.components.tagging.tag_normalization_comp import (
    CANONICAL_TAGS,
    ID3_TAG_MAP,
    ID3_TXXX_MAP,
    MP4_FREEFORM_BLOCKLIST,
    MP4_FREEFORM_MAP,
    MP4_TAG_MAP,
    VORBIS_TAG_MAP,
)


class TestCanonicalTags:
    """Tests for CANONICAL_TAGS constant."""

    @pytest.mark.unit
    def test_canonical_tags_is_set(self) -> None:
        """CANONICAL_TAGS should be a set."""
        assert isinstance(CANONICAL_TAGS, set)

    @pytest.mark.unit
    def test_canonical_tags_contains_core_metadata(self) -> None:
        """CANONICAL_TAGS should contain core metadata fields."""
        core_fields = {"title", "artist", "album", "genre", "date", "tracknumber"}
        assert core_fields.issubset(CANONICAL_TAGS)

    @pytest.mark.unit
    def test_canonical_tags_contains_extended_metadata(self) -> None:
        """CANONICAL_TAGS should contain extended metadata fields."""
        extended_fields = {"album_artist", "composer", "bpm", "discnumber"}
        assert extended_fields.issubset(CANONICAL_TAGS)

    @pytest.mark.unit
    def test_canonical_tags_does_not_contain_cover_art(self) -> None:
        """CANONICAL_TAGS should not contain cover art or binary data fields."""
        assert "cover" not in CANONICAL_TAGS
        assert "covr" not in CANONICAL_TAGS
        assert "picture" not in CANONICAL_TAGS


class TestMp4TagMap:
    """Tests for MP4_TAG_MAP constant."""

    @pytest.mark.unit
    def test_mp4_tag_map_is_dict(self) -> None:
        """MP4_TAG_MAP should be a dict."""
        assert isinstance(MP4_TAG_MAP, dict)

    @pytest.mark.unit
    def test_mp4_tag_map_maps_title(self) -> None:
        """MP4_TAG_MAP should map ©nam to title."""
        assert MP4_TAG_MAP.get("\xa9nam") == "title"

    @pytest.mark.unit
    def test_mp4_tag_map_maps_artist(self) -> None:
        """MP4_TAG_MAP should map ©ART to artist."""
        assert MP4_TAG_MAP.get("\xa9ART") == "artist"

    @pytest.mark.unit
    def test_mp4_tag_map_maps_album(self) -> None:
        """MP4_TAG_MAP should map ©alb to album."""
        assert MP4_TAG_MAP.get("\xa9alb") == "album"

    @pytest.mark.unit
    def test_mp4_tag_map_values_are_canonical(self) -> None:
        """All MP4_TAG_MAP values should be canonical tags."""
        for value in MP4_TAG_MAP.values():
            assert value in CANONICAL_TAGS, f"{value} is not a canonical tag"


class TestMp4FreeformMap:
    """Tests for MP4_FREEFORM_MAP constant."""

    @pytest.mark.unit
    def test_mp4_freeform_map_is_dict(self) -> None:
        """MP4_FREEFORM_MAP should be a dict."""
        assert isinstance(MP4_FREEFORM_MAP, dict)

    @pytest.mark.unit
    def test_mp4_freeform_map_maps_artists(self) -> None:
        """MP4_FREEFORM_MAP should map ARTISTS to artists."""
        assert MP4_FREEFORM_MAP.get("ARTISTS") == "artists"

    @pytest.mark.unit
    def test_mp4_freeform_map_maps_label(self) -> None:
        """MP4_FREEFORM_MAP should map LABEL to label."""
        assert MP4_FREEFORM_MAP.get("LABEL") == "label"


class TestMp4FreeformBlocklist:
    """Tests for MP4_FREEFORM_BLOCKLIST constant."""

    @pytest.mark.unit
    def test_mp4_freeform_blocklist_is_set(self) -> None:
        """MP4_FREEFORM_BLOCKLIST should be a set."""
        assert isinstance(MP4_FREEFORM_BLOCKLIST, set)

    @pytest.mark.unit
    def test_mp4_freeform_blocklist_contains_acoustid(self) -> None:
        """MP4_FREEFORM_BLOCKLIST should contain Acoustid Fingerprint."""
        assert "Acoustid Fingerprint" in MP4_FREEFORM_BLOCKLIST

    @pytest.mark.unit
    def test_mp4_freeform_blocklist_contains_itunes_noise(self) -> None:
        """MP4_FREEFORM_BLOCKLIST should contain iTunes normalization tags."""
        assert "iTunNORM" in MP4_FREEFORM_BLOCKLIST
        assert "iTunSMPB" in MP4_FREEFORM_BLOCKLIST


class TestId3TagMap:
    """Tests for ID3_TAG_MAP constant."""

    @pytest.mark.unit
    def test_id3_tag_map_is_dict(self) -> None:
        """ID3_TAG_MAP should be a dict."""
        assert isinstance(ID3_TAG_MAP, dict)

    @pytest.mark.unit
    def test_id3_tag_map_maps_title(self) -> None:
        """ID3_TAG_MAP should map TIT2 to title."""
        assert ID3_TAG_MAP.get("TIT2") == "title"

    @pytest.mark.unit
    def test_id3_tag_map_maps_artist(self) -> None:
        """ID3_TAG_MAP should map TPE1 to artist."""
        assert ID3_TAG_MAP.get("TPE1") == "artist"

    @pytest.mark.unit
    def test_id3_tag_map_maps_album(self) -> None:
        """ID3_TAG_MAP should map TALB to album."""
        assert ID3_TAG_MAP.get("TALB") == "album"

    @pytest.mark.unit
    def test_id3_tag_map_values_are_canonical(self) -> None:
        """All ID3_TAG_MAP values should be canonical tags."""
        for value in ID3_TAG_MAP.values():
            assert value in CANONICAL_TAGS, f"{value} is not a canonical tag"


class TestId3TxxxMap:
    """Tests for ID3_TXXX_MAP constant."""

    @pytest.mark.unit
    def test_id3_txxx_map_is_dict(self) -> None:
        """ID3_TXXX_MAP should be a dict."""
        assert isinstance(ID3_TXXX_MAP, dict)

    @pytest.mark.unit
    def test_id3_txxx_map_handles_case_variations(self) -> None:
        """ID3_TXXX_MAP should handle both uppercase and lowercase ARTISTS."""
        assert ID3_TXXX_MAP.get("ARTISTS") == "artists"
        assert ID3_TXXX_MAP.get("artists") == "artists"


class TestVorbisTagMap:
    """Tests for VORBIS_TAG_MAP constant."""

    @pytest.mark.unit
    def test_vorbis_tag_map_is_dict(self) -> None:
        """VORBIS_TAG_MAP should be a dict."""
        assert isinstance(VORBIS_TAG_MAP, dict)

    @pytest.mark.unit
    def test_vorbis_tag_map_uses_uppercase_keys(self) -> None:
        """VORBIS_TAG_MAP keys should be uppercase (Vorbis convention)."""
        for key in VORBIS_TAG_MAP:
            assert key == key.upper(), f"Key {key} should be uppercase"

    @pytest.mark.unit
    def test_vorbis_tag_map_maps_title(self) -> None:
        """VORBIS_TAG_MAP should map TITLE to title."""
        assert VORBIS_TAG_MAP.get("TITLE") == "title"

    @pytest.mark.unit
    def test_vorbis_tag_map_maps_albumartist(self) -> None:
        """VORBIS_TAG_MAP should map ALBUMARTIST to album_artist."""
        assert VORBIS_TAG_MAP.get("ALBUMARTIST") == "album_artist"

    @pytest.mark.unit
    def test_vorbis_tag_map_values_are_canonical(self) -> None:
        """All VORBIS_TAG_MAP values should be canonical tags."""
        for value in VORBIS_TAG_MAP.values():
            assert value in CANONICAL_TAGS, f"{value} is not a canonical tag"
