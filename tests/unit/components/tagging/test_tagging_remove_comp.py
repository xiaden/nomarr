"""Tests for nomarr.components.tagging.tagging_remove_comp module."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from nomarr.components.tagging.tagging_remove_comp import remove_tags_from_file
from nomarr.helpers.dto.path_dto import LibraryPath

pytestmark = [pytest.mark.unit]

_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests/fixtures/library/good/AllFormats/SameTrack"


def _library_path(path: Path) -> LibraryPath:
    return LibraryPath(relative=path.name, absolute=path, library_id=1, status="valid")


def _seed_vorbis(path: Path, constructor: type) -> None:
    """Seed namespaced + non-namespaced tags directly through mutagen (never the writer)."""
    audio = constructor(str(path))
    if audio.tags is None:
        audio.add_tags()
    audio.tags["NOM_GENRE"] = ["rock"]
    audio.tags["NOM_MOOD_HAPPY"] = ["1"]
    audio.tags["ARTIST"] = ["keep"]
    audio.save()


def _vorbis_keys(path: Path, constructor: type) -> list[str]:
    tags = constructor(str(path)).tags
    return list(tags.keys()) if tags is not None else []


class TestRemoveVorbisTags:
    """Site 2: Vorbis removal must delete seeded namespaced tags and report the true count."""

    @pytest.mark.integration
    @pytest.mark.requires_audio
    @pytest.mark.parametrize(
        ("source_ext", "constructor"),
        [("flac", FLAC), ("ogg", OggVorbis), ("opus", OggOpus)],
    )
    def test_removes_seeded_namespaced_tags_and_returns_true_count(
        self,
        tmp_path: Path,
        source_ext: str,
        constructor: type,
    ) -> None:
        target = tmp_path / f"cooltrack.{source_ext}"
        shutil.copy2(_FIXTURE_DIR / f"cooltrack.{source_ext}", target)
        _seed_vorbis(target, constructor)

        removed = remove_tags_from_file(_library_path(target), "nom")

        assert removed == 2
        remaining = _vorbis_keys(target, constructor)
        assert not [key for key in remaining if key.upper().startswith("NOM_")]
        assert [key for key in remaining if key.upper() == "ARTIST"]


class TestRemoveId3Tags:
    """The MP3 helper is already correct pre-fix (sweep evidence for P3-S4)."""

    @pytest.mark.integration
    def test_removes_namespaced_txxx_and_keeps_non_namespaced(self, tmp_path: Path) -> None:
        target = tmp_path / "song.mp3"
        target.write_bytes(b"headerless audio bytes")
        id3 = ID3()
        id3.add(TXXX(encoding=3, desc="nom:genre", text=["rock"]))
        id3.add(TXXX(encoding=3, desc="nom:mood_happy", text=["1"]))
        id3.add(TXXX(encoding=3, desc="artist", text=["keep"]))
        id3.save(str(target), v2_version=4)

        removed = remove_tags_from_file(_library_path(target), "nom")

        assert removed == 2
        remaining = ID3(str(target))
        assert "TXXX:nom:genre" not in remaining
        assert "TXXX:nom:mood_happy" not in remaining
        assert "TXXX:artist" in remaining


class TestRemoveMp4Tags:
    """The MP4 helper is already correct pre-fix (sweep evidence for P3-S4)."""

    @pytest.mark.integration
    @pytest.mark.requires_audio
    def test_removes_namespaced_freeform_atoms_and_keeps_others(self, tmp_path: Path) -> None:
        target = tmp_path / "cooltrack.m4a"
        shutil.copy2(_FIXTURE_DIR / "cooltrack.m4a", target)
        audio = MP4(str(target))
        audio["----:com.apple.iTunes:nom:genre"] = [MP4FreeForm(b"rock")]
        audio["----:com.apple.iTunes:nom:mood_happy"] = [MP4FreeForm(b"1")]
        audio.save()

        removed = remove_tags_from_file(_library_path(target), "nom")

        assert removed == 2
        remaining = MP4(str(target)).tags
        assert remaining is not None
        assert not [key for key in remaining if key.startswith("----:com.apple.iTunes:nom:")]
        assert "\u00a9too" in remaining


class TestRemoveAccurateZero:
    """An unseeded file reports 0 and is not rewritten."""

    @pytest.mark.integration
    @pytest.mark.requires_audio
    def test_unseeded_fixture_returns_zero_without_saving(self, tmp_path: Path) -> None:
        target = tmp_path / "cooltrack.flac"
        shutil.copy2(_FIXTURE_DIR / "cooltrack.flac", target)
        before = target.stat().st_mtime_ns

        removed = remove_tags_from_file(_library_path(target), "nom")

        assert removed == 0
        assert target.stat().st_mtime_ns == before


class TestRemoveTagsFromFileGuards:
    """``remove_tags_from_file`` path/extension guards."""

    def test_invalid_path_raises_value_error(self, tmp_path: Path) -> None:
        target = tmp_path / "song.flac"
        target.write_bytes(b"x")
        invalid = LibraryPath(
            relative="song.flac",
            absolute=target,
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )

        with pytest.raises(ValueError, match="invalid path"):
            remove_tags_from_file(invalid, "nom")

    def test_unsupported_extension_raises_runtime_error(self, tmp_path: Path) -> None:
        target = tmp_path / "song.wav"
        target.write_bytes(b"headerless audio bytes")

        with pytest.raises(RuntimeError, match="Failed to remove tags"):
            remove_tags_from_file(_library_path(target), "nom")
