"""
Unit tests for metadata extraction component.

Tests metadata extraction from audio files with various formats and tag structures.
"""

from pathlib import Path

import pytest

from nomarr.components.library.metadata_extraction_comp import extract_metadata, resolve_artists
from nomarr.helpers.dto.path_dto import LibraryPath


class TestResolveArtists:
    """Test artist/artists resolution logic."""

    def test_both_exist_keeps_separate(self):
        """When both artist and artists exist, keep them separate."""
        all_tags = {
            "artist": "Lead Artist",
            "artists": "Lead Artist; Featured Artist; Guest",
        }

        artist, artists = resolve_artists(all_tags)

        assert artist == "Lead Artist"
        assert artists == "Lead Artist; Featured Artist; Guest"

    def test_only_artists_extracts_first_as_artist(self):
        """When only artists exists, extract first as artist."""
        all_tags = {
            "artists": "Artist One; Artist Two; Artist Three",
        }

        artist, artists = resolve_artists(all_tags)

        assert artist == "Artist One"
        assert artists == "Artist One; Artist Two; Artist Three"

    def test_only_artist_uses_for_both(self):
        """When only artist exists, use same value for both."""
        all_tags = {
            "artist": "Single Artist",
        }

        artist, artists = resolve_artists(all_tags)

        assert artist == "Single Artist"
        assert artists == "Single Artist"

    def test_neither_returns_none(self):
        """When neither exists, return None for both."""
        all_tags = {
            "title": "Some Song",
            "album": "Some Album",
        }

        artist, artists = resolve_artists(all_tags)

        assert artist is None
        assert artists is None

    def test_deduplicates_artists_semicolon(self):
        """Should deduplicate artists separated by semicolons."""
        all_tags = {
            "artists": "Artist A; Artist B; Artist A; Artist C",
        }

        _, artists = resolve_artists(all_tags)

        assert artists == "Artist A; Artist B; Artist C"

    def test_deduplicates_artists_comma(self):
        """Should deduplicate artists separated by commas."""
        all_tags = {
            "artists": "Artist A, Artist B, Artist A, Artist C",
        }

        _, artists = resolve_artists(all_tags)

        assert artists == "Artist A; Artist B; Artist C"

    def test_deduplicates_artists_slash(self):
        """Should deduplicate artists separated by slashes."""
        all_tags = {
            "artists": "Artist A / Artist B / Artist A",
        }

        _, artists = resolve_artists(all_tags)

        assert artists == "Artist A; Artist B"

    def test_preserves_order_during_deduplication(self):
        """Should preserve order of first occurrence during deduplication."""
        all_tags = {
            "artists": "Z Artist; A Artist; M Artist; A Artist; Z Artist",
        }

        _, artists = resolve_artists(all_tags)

        # Order should be: Z, A, M (first occurrences)
        assert artists == "Z Artist; A Artist; M Artist"


class TestExtractMetadata:
    """Test metadata extraction from audio files."""

    def test_invalid_path_raises_error(self):
        """Should raise ValueError for invalid path."""
        invalid_path = LibraryPath(
            relative="test.mp3",
            absolute=Path("/invalid/test.mp3"),
            library_id=None,
            status="not_found",
            reason="File does not exist",
        )

        with pytest.raises(ValueError, match="Cannot extract metadata from invalid path"):
            extract_metadata(invalid_path)

    def test_returns_default_structure_for_nonexistent_file(self):
        """Should return default metadata structure when file doesn't exist."""
        # Create a valid LibraryPath pointing to a file that doesn't exist
        # This tests the mutagen.File() failure path
        valid_path = LibraryPath(
            relative="nonexistent.mp3",
            absolute=Path("/tmp/nonexistent_test_file_xyz.mp3"),
            library_id=1,
            status="valid",
            reason=None,
        )

        result = extract_metadata(valid_path)

        # Should return default structure
        assert result["duration"] is None
        assert result["artist"] is None
        assert result["album"] is None
        assert result["title"] is None
        assert result["genre"] is None
        assert result["year"] is None
        assert result["track_number"] is None
        assert result["all_tags"] == {}
        assert result["nom_tags"] == {}

    def test_extracts_namespace_tags_without_prefix(self):
        """Namespace tags should be stored without the prefix in nom_tags."""
        # This would need a real audio file with tags
        # For now, we'll test the logic through integration tests
        pass

    def test_removes_namespace_tags_from_all_tags(self):
        """Namespace tags should be removed from all_tags after extraction."""
        # This would need a real audio file with tags
        # For now, we'll test the logic through integration tests
        pass


# Integration tests would go here if we had sample audio files
# For now, unit tests cover the pure logic functions
