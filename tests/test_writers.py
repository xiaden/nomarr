"""
Integration tests for tag writing and reading (models/writers.py)
"""

import pytest


@pytest.fixture
def mp3_file(tmp_path):
    """Create a minimal valid MP3 file for testing."""
    mp3_path = tmp_path / "test.mp3"

    # Minimal MP3 header (ID3v2.3 + LAME encoder frame)
    # This is enough for mutagen to recognize it as MP3
    mp3_data = (
        b"ID3\x03\x00\x00\x00\x00\x00\x00"  # ID3v2.3 header
        b"\xff\xfb\x90\x00"  # MP3 sync + MPEG1 Layer3 header
        b"\x00" * 100  # Padding
    )
    mp3_path.write_bytes(mp3_data)
    return mp3_path


@pytest.fixture
def m4a_file(tmp_path):
    """Create a minimal valid M4A file for testing."""
    m4a_path = tmp_path / "test.m4a"

    # Minimal M4A/MP4 structure (ftyp + moov atoms)
    m4a_data = (
        b"\x00\x00\x00\x20ftyp"  # ftyp atom (32 bytes)
        b"M4A \x00\x00\x00\x00"  # M4A brand
        b"M4A mp42isom\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x08moov"  # moov atom (8 bytes, empty)
    )
    m4a_path.write_bytes(m4a_data)
    return m4a_path


@pytest.mark.integration
class TestTagWriter:
    """Test TagWriter for MP3 and M4A files."""

    def test_write_mp3_tags(self, mp3_file):
        """Test writing tags to MP3 file."""
        from nomarr.ml.models.writers import TagWriter

        writer = TagWriter(namespace="essentia")
        tags = {
            "mood": "happy",
            "genre": "rock",
            "energy": 0.85,
        }

        # Write tags
        writer.write(str(mp3_file), tags)

        # Read back with mutagen
        from mutagen.id3 import ID3

        audio = ID3(str(mp3_file))

        # Check namespace tags were written
        assert "TXXX:essentia:mood" in audio
        assert audio["TXXX:essentia:mood"].text[0] == "happy"

        assert "TXXX:essentia:genre" in audio
        assert audio["TXXX:essentia:genre"].text[0] == "rock"

        assert "TXXX:essentia:energy" in audio
        assert audio["TXXX:essentia:energy"].text[0] == "0.85"

    @pytest.mark.skip(reason="M4A fixture is not a valid MP4 file - needs real audio sample")
    def test_write_m4a_tags(self, m4a_file):
        """Test writing tags to M4A file."""
        from nomarr.ml.models.writers import TagWriter

        writer = TagWriter(namespace="essentia")
        tags = {
            "mood": "calm",
            "danceability": 0.65,
        }

        # Write tags
        writer.write(str(m4a_file), tags)

        # Read back with mutagen
        from mutagen.mp4 import MP4

        audio = MP4(str(m4a_file))

        # Check freeform tags were written
        assert "----:com.apple.iTunes:essentia:mood" in audio
        assert audio["----:com.apple.iTunes:essentia:mood"][0].decode() == "calm"

        assert "----:com.apple.iTunes:essentia:danceability" in audio
        assert audio["----:com.apple.iTunes:essentia:danceability"][0].decode() == "0.65"

    def test_write_multivalue_tags_mp3(self, mp3_file):
        """Test writing multi-value tags to MP3."""
        from nomarr.ml.models.writers import TagWriter

        writer = TagWriter(namespace="essentia")
        tags = {
            "mood-strict": ["happy", "energetic"],
            "genre": "rock",
        }

        writer.write(str(mp3_file), tags)

        from mutagen.id3 import ID3

        audio = ID3(str(mp3_file))

        # Multi-value tag should be written as a list but may be joined with /
        mood_values = audio["TXXX:essentia:mood-strict"].text
        assert isinstance(mood_values, list)
        # Mutagen may join multiple values with / separator in a single string
        mood_str = mood_values[0] if len(mood_values) == 1 else "/".join(mood_values)
        assert "happy" in mood_str
        assert "energetic" in mood_str

    @pytest.mark.skip(reason="M4A fixture is not a valid MP4 file - needs real audio sample")
    def test_write_multivalue_tags_m4a(self, m4a_file):
        """Test writing multi-value tags to M4A."""
        from nomarr.ml.models.writers import TagWriter

        writer = TagWriter(namespace="essentia")
        tags = {
            "mood-regular": ["peaceful", "dreamy"],
        }

        writer.write(str(m4a_file), tags)

        from mutagen.mp4 import MP4

        audio = MP4(str(m4a_file))

        # Multi-value tag should be written as semicolon-separated
        mood_tag = audio["----:com.apple.iTunes:essentia:mood-regular"][0].decode()
        assert "peaceful" in mood_tag
        assert "dreamy" in mood_tag
        assert ";" in mood_tag

    def test_overwrite_existing_tags(self, mp3_file):
        """Test overwriting existing tags."""
        from nomarr.ml.models.writers import TagWriter

        # Write initial tags
        writer = TagWriter(namespace="essentia", overwrite=True)
        writer.write(str(mp3_file), {"mood": "happy"})

        # Overwrite with new value
        writer.write(str(mp3_file), {"mood": "sad"})

        from mutagen.id3 import ID3

        audio = ID3(str(mp3_file))
        assert audio["TXXX:essentia:mood"].text[0] == "sad"

    def test_preserve_existing_tags(self, mp3_file):
        """Test that non-namespace tags are preserved."""
        # Manually write a non-essentia tag
        from mutagen.id3 import ID3
        from mutagen.id3._frames import TIT2

        from nomarr.ml.models.writers import TagWriter

        audio = ID3(str(mp3_file))
        audio.add(TIT2(encoding=3, text="Original Title"))
        audio.save()

        # Write essentia tags
        writer = TagWriter(namespace="essentia")
        writer.write(str(mp3_file), {"mood": "happy"})

        # Verify original tag is preserved
        audio = ID3(str(mp3_file))
        assert "TIT2" in audio
        assert audio["TIT2"].text[0] == "Original Title"
        assert "TXXX:essentia:mood" in audio

    def test_write_numeric_values(self, mp3_file):
        """Test writing numeric tag values."""
        from nomarr.ml.models.writers import TagWriter

        writer = TagWriter(namespace="essentia")
        tags = {
            "energy": 0.876543,
            "valence": 0.5,
            "tempo": 120,
        }

        writer.write(str(mp3_file), tags)

        from mutagen.id3 import ID3

        audio = ID3(str(mp3_file))

        # Numeric values should be stringified
        assert "TXXX:essentia:energy" in audio
        energy_str = audio["TXXX:essentia:energy"].text[0]
        assert "0.87" in energy_str  # Should be rounded/formatted

    def test_custom_namespace(self, mp3_file):
        """Test using a custom namespace."""
        from nomarr.ml.models.writers import TagWriter

        writer = TagWriter(namespace="custom_tagger")
        tags = {"mood": "happy"}

        writer.write(str(mp3_file), tags)

        from mutagen.id3 import ID3

        audio = ID3(str(mp3_file))
        assert "TXXX:custom_tagger:mood" in audio
        assert audio["TXXX:custom_tagger:mood"].text[0] == "happy"

    def test_write_empty_tags_dict(self, mp3_file):
        """Test writing empty tags dict (should not error)."""
        from nomarr.ml.models.writers import TagWriter

        writer = TagWriter(namespace="essentia")
        writer.write(str(mp3_file), {})  # Should not raise

    def test_write_nonexistent_file_raises(self):
        """Test writing to non-existent file raises error."""
        from nomarr.ml.models.writers import TagWriter

        writer = TagWriter(namespace="essentia")

        with pytest.raises(RuntimeError):  # Writers wrap errors in RuntimeError
            writer.write("/nonexistent/file.mp3", {"mood": "happy"})


@pytest.mark.integration
class TestTagReading:
    """Test reading back written tags."""

    def test_roundtrip_mp3(self, mp3_file):
        """Test write → read roundtrip for MP3."""
        from nomarr.ml.models.writers import TagWriter

        original_tags = {
            "mood": "happy",
            "energy": 0.85,
            "genre": "rock",
            "mood-strict": ["happy", "energetic"],
        }

        writer = TagWriter(namespace="essentia")
        writer.write(str(mp3_file), original_tags)

        # Read back
        from mutagen.id3 import ID3

        audio = ID3(str(mp3_file))

        # Verify all tags
        assert audio["TXXX:essentia:mood"].text[0] == "happy"
        assert audio["TXXX:essentia:genre"].text[0] == "rock"

        # Multi-value tag - ID3v2.4 returns lists directly, no need to split
        mood_strict = audio["TXXX:essentia:mood-strict"].text
        assert "happy" in mood_strict
        assert "energetic" in mood_strict

    @pytest.mark.skip(reason="M4A fixture is not a valid MP4 file - needs real audio sample")
    def test_roundtrip_m4a(self, m4a_file):
        """Test write → read roundtrip for M4A."""
        from nomarr.ml.models.writers import TagWriter

        original_tags = {
            "mood": "calm",
            "danceability": 0.65,
        }

        writer = TagWriter(namespace="essentia")
        writer.write(str(m4a_file), original_tags)

        # Read back
        from mutagen.mp4 import MP4

        audio = MP4(str(m4a_file))

        assert audio["----:com.apple.iTunes:essentia:mood"][0].decode() == "calm"
        assert audio["----:com.apple.iTunes:essentia:danceability"][0].decode() == "0.65"
