"""Tests for nomarr.components.tagging.tagging_reader_comp module."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import mutagen
import pytest

from nomarr.components.tagging.tagging_reader_comp import read_tags_from_file
from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.path_dto import LibraryPath

_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests/fixtures/library/good/AllFormats/SameTrack"


def _real_library_path(target: Path) -> LibraryPath:
    return LibraryPath(relative=target.name, absolute=target, library_id=1, status="valid")


class _FakeFrame:
    """Minimal stand-in for a mutagen frame exposing a ``.text`` attribute."""

    def __init__(self, text: list[str]) -> None:
        self.text = text


def _valid_library_path(relative: str) -> LibraryPath:
    """Build a valid LibraryPath for testing (direct construction is test-only)."""
    return LibraryPath(
        relative=relative,
        absolute=Path("/music") / relative,
        library_id=1,
        status="valid",
    )


class TestReadTagsFromFile:
    """Tests for ``read_tags_from_file()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_valid_tags_when_namespaced_tags_exist(self) -> None:
        """Namespaced MP3 TXXX frames become a non-empty Tags object."""
        fake_audio = type("Audio", (), {})()
        fake_audio.tags = {
            "TXXX:nom:genre": _FakeFrame(["rock"]),
            "TXXX:nom:mood": _FakeFrame(["calm", "bright"]),
        }
        lib_path = _valid_library_path("song.mp3")

        with patch("nomarr.components.tagging.tagging_reader_comp.mutagen.File", return_value=fake_audio):
            result = read_tags_from_file(lib_path, "nom")

        assert result is not None
        assert result.to_dict() == {"genre": ("rock",), "mood": ("calm", "bright")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_no_namespaced_tags_match(self) -> None:
        """Frames without the namespace prefix are ignored, yielding None."""
        fake_audio = type("Audio", (), {})()
        fake_audio.tags = {
            "TXXX:other:genre": _FakeFrame(["rock"]),
            "TPE1": _FakeFrame(["artist"]),
        }
        lib_path = _valid_library_path("song.mp3")

        with patch("nomarr.components.tagging.tagging_reader_comp.mutagen.File", return_value=fake_audio):
            result = read_tags_from_file(lib_path, "nom")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_no_tag_dict_at_all(self) -> None:
        fake_audio = type("Audio", (), {})()
        fake_audio.tags = {}
        lib_path = _valid_library_path("song.mp3")

        with patch("nomarr.components.tagging.tagging_reader_comp.mutagen.File", return_value=fake_audio):
            result = read_tags_from_file(lib_path, "nom")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_value_error_for_invalid_path(self) -> None:
        lib_path = LibraryPath(
            relative="song.mp3",
            absolute=Path("/music/song.mp3"),
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )
        with pytest.raises(ValueError, match="invalid path"):
            read_tags_from_file(lib_path, "nom")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_runtime_error_when_mutagen_cannot_load(self) -> None:
        """A failed mutagen load surfaces as RuntimeError (wrapped ValueError)."""
        lib_path = _valid_library_path("song.mp3")

        with (
            patch("nomarr.components.tagging.tagging_reader_comp.mutagen.File", return_value=None),
            pytest.raises(RuntimeError, match="Failed to read tags"),
        ):
            read_tags_from_file(lib_path, "nom")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_runtime_error_for_unsupported_format(self) -> None:
        """An unsupported extension surfaces as RuntimeError (wrapped ValueError)."""
        lib_path = _valid_library_path("song.wav")

        with pytest.raises(RuntimeError, match="Unsupported audio format"):
            read_tags_from_file(lib_path, "nom")


class TestReadVorbisRoundTrip:
    """Real-audio write-then-read-back through the public ``TagWriter`` / ``read_tags_from_file`` pair.

    The reader component previously had no real-audio coverage, which is how the Vorbis
    case-sensitive namespace-prefix defect survived. These tests write through the real
    ``TagWriter`` onto real fixture copies and read the tags back from disk through the
    real reader path (never by inspecting an in-memory object).
    """

    @pytest.mark.integration
    @pytest.mark.requires_audio
    @pytest.mark.parametrize("ext", ["flac", "ogg", "opus"])
    def test_vorbis_write_read_round_trip(self, tmp_path: Path, ext: str) -> None:
        """A written ``nom:`` tag reads back from disk for flac/ogg/opus."""
        target = tmp_path / f"cooltrack.{ext}"
        shutil.copy2(_FIXTURE_DIR / f"cooltrack.{ext}", target)
        lib_path = _real_library_path(target)
        tags = Tags(items=(Tag(name="genre", values=("rock",)), Tag(name="mood-happy", values=("1",))))

        TagWriter().write(lib_path, tags)

        result = read_tags_from_file(lib_path, "nom")
        assert result is not None
        assert result.to_dict() == {"genre": ("rock",), "mood-happy": ("1",)}

    @pytest.mark.integration
    @pytest.mark.requires_audio
    def test_m4a_write_read_round_trip(self, tmp_path: Path) -> None:
        """Parity: a written ``nom:`` atom reads back from disk for m4a (freeform keys keep case)."""
        target = tmp_path / "cooltrack.m4a"
        shutil.copy2(_FIXTURE_DIR / "cooltrack.m4a", target)
        lib_path = _real_library_path(target)
        tags = Tags(items=(Tag(name="genre", values=("rock",)),))

        TagWriter().write(lib_path, tags)

        result = read_tags_from_file(lib_path, "nom")
        assert result is not None
        assert result.to_dict() == {"genre": ("rock",)}

    @pytest.mark.integration
    @pytest.mark.requires_audio
    def test_mp3_write_read_round_trip(self, tmp_path: Path) -> None:
        """Parity: a written ``nom:`` TXXX frame reads back from disk for mp3.

        The mp3 is synthesized in-test rather than copied from a tracked fixture: the
        four tracked ``*.mp3`` fixtures (``help.mp3``, ``yesterday.mp3``,
        ``prelude.mp3``, ``blue_in_green.mp3``) are deliberate 114-byte stubs (empty
        ID3 header + one truncated MPEG frame) on which ``mutagen.File`` raises
        ``HeaderNotFoundError("can't sync to MPEG frame")``, so none can source an
        mp3 parity case. No new binary fixture may be committed, so a minimal but
        genuinely loadable MPEG-1 Layer III stream is written here: >= 2 frames (4 is
        verified safe), each 417 bytes = 4-byte header ``FF FB 90 00`` (MPEG-1 Layer
        III, 128 kbps, 44100 Hz, stereo, no padding) + 413 zero bytes. One frame
        fails to load; >= 2 frames load as ``type=MP3``.
        """
        target = tmp_path / "synth.mp3"
        frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
        target.write_bytes(frame * 4)
        lib_path = _real_library_path(target)
        tags = Tags(items=(Tag(name="genre", values=("rock",)),))

        TagWriter().write(lib_path, tags)

        result = read_tags_from_file(lib_path, "nom")
        assert result is not None
        assert result.to_dict() == {"genre": ("rock",)}

    @pytest.mark.integration
    @pytest.mark.requires_audio
    @pytest.mark.parametrize("ext", ["flac", "ogg", "opus"])
    def test_vorbis_case_variant_key_is_matched_case_insensitively(self, tmp_path: Path, ext: str) -> None:
        """A Vorbis comment seeded directly through mutagen is matched case-insensitively.

        The writer is bypassed: the key is assigned through mutagen's Vorbis mapping (which
        lower-cases keys on write, yielding an on-disk ``nom_mood_happy`` while the reader
        builds the ``NOM_`` prefix). After the ``_``->``-`` normalization the canonical
        ``mood-happy`` name must be returned.
        """
        target = tmp_path / f"cooltrack.{ext}"
        shutil.copy2(_FIXTURE_DIR / f"cooltrack.{ext}", target)

        audio = mutagen.File(str(target))
        assert audio is not None
        if audio.tags is None:
            audio.add_tags()
        audio.tags["NOM_MOOD_HAPPY"] = ["1"]
        audio.save()

        lib_path = _real_library_path(target)
        result = read_tags_from_file(lib_path, "nom")
        assert result is not None
        assert result.to_dict() == {"mood-happy": ("1",)}

    @pytest.mark.integration
    @pytest.mark.requires_audio
    @pytest.mark.parametrize("ext", ["flac", "ogg", "opus"])
    def test_vorbis_non_namespaced_keys_are_ignored(self, tmp_path: Path, ext: str) -> None:
        """The case-insensitive namespace predicate ignores keys not prefixed ``nom_``.

        This is the negative boundary of the predicate fixed in the reader: a standard
        ``TITLE`` comment and the near-prefix probe ``NOMINAL`` (which starts with ``NOM``
        but not ``NOM_``) must both be ignored. An over-matching regression (for example
        dropping the trailing underscore, or using a containment check) would return a tag
        here, so this pins that only the exact ``NOM_`` prefix matches.
        """
        target = tmp_path / f"cooltrack.{ext}"
        shutil.copy2(_FIXTURE_DIR / f"cooltrack.{ext}", target)

        audio = mutagen.File(str(target))
        assert audio is not None
        if audio.tags is None:
            audio.add_tags()
        audio.tags["TITLE"] = ["Untitled"]
        audio.tags["NOMINAL"] = ["x"]
        audio.save()

        lib_path = _real_library_path(target)
        assert read_tags_from_file(lib_path, "nom") is None
