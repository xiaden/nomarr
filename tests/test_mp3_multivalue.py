"""
Test MP3 multi-value tag support with ID3v2.4.
Regression test for mood tags being concatenated with / in ID3v2.3.
"""

import pytest


@pytest.mark.unit
class TestMP3MultiValueTags:
    """Test that MP3 files properly support multi-value tags with ID3v2.4."""

    def test_id3v23_joins_with_slash(self):
        """Test that ID3v2.3 joins multi-value tags (the old bug)."""
        import tempfile
        from pathlib import Path

        from mutagen.id3 import ID3, TXXX

        test_file = Path(tempfile.gettempdir()) / "test_v23.mp3"

        try:
            # Create minimal MP3 with ID3v2.3
            id3 = ID3()
            moods = ["aggressive", "bass-forward", "electronic production"]
            id3.add(TXXX(encoding=3, desc="nom:mood-loose", text=moods))

            # Minimal MP3 data
            test_file.write_bytes(b"\xff\xfb\x90\x00" * 10)
            id3.save(test_file, v2_version=3)

            # Read it back
            id3_read = ID3(test_file)
            frames = list(id3_read.getall("TXXX"))

            assert len(frames) == 1
            frame = frames[0]

            # ID3v2.3 joins with / (or NULL bytes displayed as /)
            assert len(frame.text) == 1
            assert "/" in frame.text[0]  # Values are joined!
            assert "aggressive" in frame.text[0]
            assert "bass-forward" in frame.text[0]

        finally:
            if test_file.exists():
                test_file.unlink()

    def test_id3v24_preserves_multivalue(self):
        """Test that ID3v2.4 preserves multi-value tags (the fix)."""
        import tempfile
        from pathlib import Path

        from mutagen.id3 import ID3, TXXX

        test_file = Path(tempfile.gettempdir()) / "test_v24.mp3"

        try:
            # Create minimal MP3 with ID3v2.4
            id3 = ID3()
            moods = ["aggressive", "bass-forward", "electronic production"]
            id3.add(TXXX(encoding=3, desc="nom:mood-loose", text=moods))

            # Minimal MP3 data
            test_file.write_bytes(b"\xff\xfb\x90\x00" * 10)
            id3.save(test_file, v2_version=4)  # ← ID3v2.4!

            # Read it back
            id3_read = ID3(test_file)
            frames = list(id3_read.getall("TXXX"))

            assert len(frames) == 1
            frame = frames[0]

            # ID3v2.4 preserves separate values!
            assert len(frame.text) == 3
            assert frame.text == moods
            assert frame.text[0] == "aggressive"
            assert frame.text[1] == "bass-forward"
            assert frame.text[2] == "electronic production"

        finally:
            if test_file.exists():
                test_file.unlink()

    def test_writer_uses_id3v24(self):
        """Test that our MP3 writer uses ID3v2.4."""
        import tempfile
        from pathlib import Path

        from mutagen.id3 import ID3

        from nomarr.ml.models.writers import TagWriter

        test_file = Path(tempfile.gettempdir()) / "test_writer.mp3"

        try:
            # Create minimal MP3
            test_file.write_bytes(b"\xff\xfb\x90\x00" * 10)

            # Write multi-value tag using our writer
            writer = TagWriter(overwrite=True, namespace="nom")
            tags = {"mood-loose": ["aggressive", "bass-forward", "electronic production"]}

            writer.write(str(test_file), tags)

            # Read it back with mutagen
            id3 = ID3(test_file)
            frames = list(id3.getall("TXXX"))

            assert len(frames) == 1
            frame = frames[0]

            # Should be preserved as separate values (ID3v2.4 behavior)
            assert frame.desc == "nom:mood-loose"
            assert len(frame.text) == 3
            assert frame.text == ["aggressive", "bass-forward", "electronic production"]

        finally:
            if test_file.exists():
                test_file.unlink()
