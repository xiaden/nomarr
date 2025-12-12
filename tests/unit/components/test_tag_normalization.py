"""
Unit tests for tag normalization component.

Tests that format-specific tags (MP4, ID3, Vorbis) are correctly
normalized to canonical format, especially for namespaced tags.
"""

from nomarr.components.tagging.tag_normalization_comp import (
    normalize_id3_tags,
    normalize_mp4_tags,
    normalize_vorbis_tags,
)


class TestVorbisTagNormalization:
    """Test Vorbis comment normalization (FLAC, Ogg, Opus)."""

    def test_converts_nom_underscore_tags_to_colon_format(self):
        """Test that NOM_MOOD_STRICT converts to nom:mood-strict."""
        vorbis_tags = {
            "TITLE": ["Test Track"],
            "ARTIST": ["Test Artist"],
            "NOM_MOOD_STRICT": ["happy", "energetic"],
            "NOM_MOOD_REGULAR": ["upbeat", "bright"],
            "NOM_MOOD_LOOSE": ["positive"],
        }

        result = normalize_vorbis_tags(vorbis_tags)

        # Check canonical tags (single-element lists are now JSON arrays)
        assert result["title"] == '["Test Track"]'
        assert result["artist"] == '["Test Artist"]'

        # Check namespace tags are converted to colon format
        assert "nom:mood-strict" in result
        assert "nom:mood-regular" in result
        assert "nom:mood-loose" in result

        # Verify values are preserved as JSON arrays
        assert result["nom:mood-strict"] == '["happy", "energetic"]'
        assert result["nom:mood-regular"] == '["upbeat", "bright"]'
        assert result["nom:mood-loose"] == '["positive"]'

    def test_converts_mixed_case_nom_tags(self):
        """Test that mixed case NOM tags are normalized."""
        vorbis_tags = {
            "nom_mood_strict": ['["calm"]'],
            "NOM_MOOD_STRICT": ['["happy"]'],
            "Nom_Mood_Regular": ['["bright"]'],
        }

        result = normalize_vorbis_tags(vorbis_tags)

        # All should be converted to lowercase with colons
        assert "nom:mood-strict" in result

    def test_preserves_nom_colon_format_if_present(self):
        """Test that nom:* tags with colons are preserved."""
        vorbis_tags = {
            "nom:mood-strict": ["happy"],
            "nom:custom-tag": ["value"],
        }

        result = normalize_vorbis_tags(vorbis_tags)

        assert result["nom:mood-strict"] == '["happy"]'
        assert result["nom:custom-tag"] == '["value"]'

    def test_handles_numeric_nom_tags(self):
        """Test that numeric namespace tags are converted correctly."""
        vorbis_tags = {
            "NOM_DANCEABILITY_TIER": ["high"],
            "NOM_ENERGY_SCORE": ["0.85"],
            "NOM_TEMPO": ["120"],
        }

        result = normalize_vorbis_tags(vorbis_tags)

        assert result["nom:danceability-tier"] == '["high"]'
        assert result["nom:energy-score"] == '["0.85"]'
        assert result["nom:tempo"] == '["120"]'

    def test_drops_cover_art_and_binary_fields(self):
        """Test that binary fields are dropped."""
        vorbis_tags = {
            "TITLE": ["Test"],
            "METADATA_BLOCK_PICTURE": ["<binary data>"],
            "COVERART": ["<binary>"],
            "NOM_MOOD_STRICT": ['["happy"]'],
        }

        result = normalize_vorbis_tags(vorbis_tags)

        assert "title" in result
        assert "nom:mood-strict" in result
        assert "METADATA_BLOCK_PICTURE" not in result
        assert "COVERART" not in result


class TestMP4TagNormalization:
    """Test MP4/M4A tag normalization."""

    def test_keeps_nom_colon_format_in_freeform_tags(self):
        """Test that nom:* tags in freeform format are preserved."""
        mp4_tags = {
            "\xa9nam": ["Test Track"],
            "\xa9ART": ["Test Artist"],
            "----:com.apple.iTunes:nom:mood-strict": [b'["happy", "energetic"]'],
            "----:com.apple.iTunes:nom:mood-regular": [b'["upbeat"]'],
            "----:com.apple.iTunes:nom:danceability": [b"0.75"],
        }

        result = normalize_mp4_tags(mp4_tags)

        # Check canonical tags (lists serialize to JSON arrays)
        assert result["title"] == '["Test Track"]'
        assert result["artist"] == '["Test Artist"]'

        # Check namespace tags preserve colon format
        assert "nom:mood-strict" in result
        assert "nom:mood-regular" in result
        assert "nom:danceability" in result

    def test_handles_mp4_track_and_disc_numbers(self):
        """Test that MP4 track/disc tuples are serialized."""
        mp4_tags = {
            "\xa9nam": ["Test"],
            "trkn": [(5, 12)],  # Track 5 of 12
            "disk": [(1, 2)],  # Disc 1 of 2
        }

        result = normalize_mp4_tags(mp4_tags)

        assert "tracknumber" in result
        assert "discnumber" in result

    def test_drops_blocklisted_freeform_tags(self):
        """Test that blocklisted tags are dropped."""
        mp4_tags = {
            "\xa9nam": ["Test"],
            "----:com.apple.iTunes:Acoustid Fingerprint": [b"fingerprint"],
            "----:com.apple.iTunes:iTunNORM": [b"normalization"],
            "----:com.apple.iTunes:nom:mood-strict": [b'["happy"]'],
        }

        result = normalize_mp4_tags(mp4_tags)

        assert "title" in result
        assert "nom:mood-strict" in result
        assert "Acoustid Fingerprint" not in result
        assert "iTunNORM" not in result

    def test_drops_cover_art(self):
        """Test that cover art is dropped."""
        mp4_tags = {
            "\xa9nam": ["Test"],
            "covr": [b"<image data>"],
            "----:com.apple.iTunes:nom:mood-strict": [b"happy"],
        }

        result = normalize_mp4_tags(mp4_tags)

        assert "title" in result
        assert "nom:mood-strict" in result
        assert "covr" not in result


class TestID3TagNormalization:
    """Test ID3 tag normalization (MP3)."""

    def test_keeps_nom_colon_format_in_txxx_frames(self):
        """Test that nom:* tags in TXXX frames are preserved."""
        # Simulate ID3 tags with TXXX frames
        id3_tags = {
            "TIT2": "Test Track",
            "TPE1": "Test Artist",
            "TXXX:nom:mood-strict": '["happy", "energetic"]',
            "TXXX:nom:mood-regular": '["upbeat"]',
            "TXXX:nom:energy": "0.85",
        }

        result = normalize_id3_tags(id3_tags)

        # Check canonical tags (all values are JSON arrays now)
        assert result["title"] == '["Test Track"]'
        assert result["artist"] == '["Test Artist"]'

        # Check namespace tags preserve colon format
        assert "nom:mood-strict" in result
        assert "nom:mood-regular" in result
        assert "nom:energy" in result

    def test_maps_standard_id3_frames(self):
        """Test that standard ID3 frames are mapped correctly."""
        id3_tags = {
            "TIT2": "Title",
            "TPE1": "Artist",
            "TALB": "Album",
            "TCON": "Rock",
            "TDRC": "2024",
            "TRCK": "5/12",
            "TBPM": "120",
        }

        result = normalize_id3_tags(id3_tags)

        assert result["title"] == '["Title"]'
        assert result["artist"] == '["Artist"]'
        assert result["album"] == '["Album"]'
        assert result["genre"] == '["Rock"]'
        assert result["date"] == '["2024"]'
        assert result["tracknumber"] == '["5/12"]'
        assert result["bpm"] == '["120"]'

    def test_drops_binary_frames(self):
        """Test that binary/picture frames are dropped."""
        id3_tags = {
            "TIT2": "Test",
            "APIC": b"<image data>",
            "GEOB": b"<object>",
            "TXXX:nom:mood-strict": "happy",
        }

        result = normalize_id3_tags(id3_tags)

        assert "title" in result
        assert "nom:mood-strict" in result
        assert "APIC" not in result
        assert "GEOB" not in result


class TestCrossFormatConsistency:
    """Test that all formats produce consistent normalized output."""

    def test_all_formats_produce_nom_colon_format(self):
        """Test that all formats normalize namespace tags to nom:* format."""
        # Vorbis format
        vorbis_tags = {"NOM_MOOD_STRICT": ['["happy"]']}
        vorbis_result = normalize_vorbis_tags(vorbis_tags)

        # MP4 format
        mp4_tags = {"----:com.apple.iTunes:nom:mood-strict": [b'["happy"]']}
        mp4_result = normalize_mp4_tags(mp4_tags)

        # ID3 format
        id3_tags = {"TXXX:nom:mood-strict": '["happy"]'}
        id3_result = normalize_id3_tags(id3_tags)

        # All should produce the same key format
        assert "nom:mood-strict" in vorbis_result
        assert "nom:mood-strict" in mp4_result
        assert "nom:mood-strict" in id3_result

    def test_all_formats_preserve_canonical_tags(self):
        """Test that all formats preserve standard tags."""
        # Vorbis
        vorbis = {"TITLE": ["Test"], "ARTIST": ["Artist"], "GENRE": ["Rock"]}
        vorbis_result = normalize_vorbis_tags(vorbis)

        # MP4
        mp4 = {"\xa9nam": ["Test"], "\xa9ART": ["Artist"], "\xa9gen": ["Rock"]}
        mp4_result = normalize_mp4_tags(mp4)

        # ID3
        id3 = {"TIT2": "Test", "TPE1": "Artist", "TCON": "Rock"}
        id3_result = normalize_id3_tags(id3)

        # All should have same canonical keys
        for result in [vorbis_result, mp4_result, id3_result]:
            assert "title" in result
            assert "artist" in result
            assert "genre" in result

        # All formats now consistently return JSON arrays
        assert vorbis_result["title"] == '["Test"]'
        assert mp4_result["title"] == '["Test"]'
        assert id3_result["title"] == '["Test"]'
        assert vorbis_result["artist"] == '["Artist"]'
        assert vorbis_result["genre"] == '["Rock"]'


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_tags_dict(self):
        """Test that empty tag dicts return empty results."""
        assert normalize_vorbis_tags({}) == {}
        assert normalize_mp4_tags({}) == {}
        assert normalize_id3_tags({}) == {}

    def test_tags_with_only_non_canonical_fields(self):
        """Test that non-canonical tags are filtered out."""
        vorbis_tags = {
            "COMMENT": ["Some comment"],
            "DESCRIPTION": ["Description"],
            "COPYRIGHT": ["2024"],
        }
        result = normalize_vorbis_tags(vorbis_tags)
        assert result == {}

    def test_nom_tags_with_special_characters(self):
        """Test namespace tags with underscores and numbers."""
        vorbis_tags = {
            "NOM_MOOD_STRICT_V2": ["value"],
            "NOM_TAG_WITH_NUMBERS_123": ["value"],
        }
        result = normalize_vorbis_tags(vorbis_tags)

        assert "nom:mood-strict-v2" in result
        assert "nom:tag-with-numbers-123" in result
