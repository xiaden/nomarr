"""Tests for nomarr.components.tagging.tagging_writer_comp module."""

from __future__ import annotations

import errno
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import mutagen
import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from nomarr.components.tagging.safe_write_comp import (
    DURATION_TOLERANCE_S,
    SafeWriteResult,
    _AudioProperties,
)
from nomarr.components.tagging.tagging_writer_comp import TagWriter, _MP3Writer, _MP4Writer, _VorbisWriter
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.path_dto import LibraryPath

_GOOD_PROPS = _AudioProperties(duration=180.0, sample_rate=44100, channels=2)

_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests/fixtures/library/good/AllFormats/SameTrack"


def _valid_library_path(relative: str) -> LibraryPath:
    return LibraryPath(
        relative=relative,
        absolute=Path("/music") / relative,
        library_id=1,
        status="valid",
    )


def _make_tags() -> Tags:
    return Tags(items=(Tag(name="genre", values=("rock", "pop")),))


class TestTagWriterWrite:
    """Tests for ``TagWriter.write()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_with_tags_delegates_to_format_writer_with_to_dict(self) -> None:
        writer = TagWriter()
        writer._mp3 = MagicMock()
        lib_path = _valid_library_path("song.mp3")
        tags = _make_tags()

        writer.write(lib_path, tags)

        writer._mp3.write.assert_called_once_with(lib_path.absolute, {"genre": ("rock", "pop")})

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_with_none_clears_namespace_with_empty_dict(self) -> None:
        writer = TagWriter()
        writer._mp3 = MagicMock()
        lib_path = _valid_library_path("song.mp3")

        writer.write(lib_path, None)

        writer._mp3.write.assert_called_once_with(lib_path.absolute, {})

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_routes_by_extension(self) -> None:
        writer = TagWriter()
        writer._mp4 = MagicMock()
        lib_path = _valid_library_path("song.m4a")

        writer.write(lib_path, _make_tags())

        writer._mp4.write.assert_called_once_with(lib_path.absolute, {"genre": ("rock", "pop")})

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_raises_value_error_for_invalid_path(self) -> None:
        writer = TagWriter()
        lib_path = LibraryPath(
            relative="song.mp3",
            absolute=Path("/music/song.mp3"),
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )
        with pytest.raises(ValueError, match="invalid path"):
            writer.write(lib_path, _make_tags())

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_to_path_passes_raw_path_not_library_path(self) -> None:
        """The private temp-write path passes the raw path (DD 8.9) and takes ``source_ext``."""
        writer = TagWriter()
        writer._mp3 = MagicMock()

        writer._write_to_path("/tmp/.song.abc123.nomarr-tmp", {"genre": "rock"}, source_ext="mp3")

        writer._mp3.write.assert_called_once()
        first_arg = writer._mp3.write.call_args.args[0]
        assert first_arg == "/tmp/.song.abc123.nomarr-tmp"
        assert isinstance(first_arg, LibraryPath) is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_to_path_dispatches_on_source_ext_not_temp_suffix(self) -> None:
        """``_write_to_path`` dispatches on ``source_ext``; the ``.nomarr-tmp`` suffix is ignored."""
        writer = TagWriter()
        writer._mp3 = MagicMock()
        writer._mp4 = MagicMock()
        writer._vorbis = MagicMock()

        writer._write_to_path("/tmp/.song.abc123.nomarr-tmp", {"genre": "rock"}, source_ext="flac")

        writer._vorbis.write.assert_called_once()
        writer._mp3.write.assert_not_called()
        writer._mp4.write.assert_not_called()


class TestFormatWriterSourceExt:
    """Container selection is driven by ``source_ext``; the temp suffix is never parsed."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(
        ("source_ext", "constructor_name"),
        [("flac", "FLAC"), ("ogg", "OggVorbis"), ("opus", "OggOpus")],
    )
    def test_vorbis_writer_selects_container_from_source_ext(
        self,
        monkeypatch: pytest.MonkeyPatch,
        source_ext: str,
        constructor_name: str,
    ) -> None:
        """``_VorbisWriter`` picks FLAC/OggVorbis/OggOpus from ``source_ext``, not the file name."""
        constructors: dict[str, MagicMock] = {}
        for name in ("FLAC", "OggVorbis", "OggOpus"):
            container = MagicMock()
            container.tags = {}
            constructors[name] = MagicMock(return_value=container)
        for name, constructor in constructors.items():
            monkeypatch.setattr(f"nomarr.components.tagging.tagging_writer_comp.{name}", constructor)

        temp = Path("/tmp/.song.abc123.nomarr-tmp")
        _VorbisWriter().write(temp, {"genre": "rock"}, source_ext=source_ext)

        constructors[constructor_name].assert_called_once_with(str(temp))
        for name, constructor in constructors.items():
            if name != constructor_name:
                constructor.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_mp3_writer_write_accepts_path_object(self, tmp_path: Path) -> None:
        """``_MP3Writer.write`` accepts a ``pathlib.Path`` (the ``str | Path`` widening, C4)."""
        song = tmp_path / "song.mp3"
        song.write_bytes(b"")

        _MP3Writer().write(song, {"genre": "rock"})

        id3 = ID3(str(song))
        assert any(getattr(frame, "desc", "") == "nom:genre" for frame in id3.values())


class TestMP4Writer:
    """``_MP4Writer`` maps namespaced keys to iTunes freeform atoms (Part E widening)."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_mp4_writer_write_accepts_path_object_and_maps_freeform_atoms(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``write`` accepts a ``pathlib.Path`` and maps ``nom:`` keys to freeform atoms.

        The constructor receives ``str(path)`` (no ``LibraryPath``/``is_valid``/``.absolute``
        handling), a stale namespaced atom is cleared, and the new atom carries the value.
        """
        container = MagicMock()
        container.tags = {"----:com.apple.iTunes:nom:stale": [b"stale"]}
        mp4_ctor = MagicMock(return_value=container)
        monkeypatch.setattr("nomarr.components.tagging.tagging_writer_comp.MP4", mp4_ctor)

        temp = Path("/tmp/.song.abc123.nomarr-tmp")
        _MP4Writer().write(temp, {"genre": "rock"})

        mp4_ctor.assert_called_once_with(str(temp))
        atom_key = "----:com.apple.iTunes:nom:genre"
        assert atom_key in container.tags
        assert "----:com.apple.iTunes:nom:stale" not in container.tags
        assert bytes(container.tags[atom_key][0]) == b"rock"
        container.save.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_mp4_writer_adds_tags_when_container_has_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A container without a tag mapping gets ``add_tags()`` before atoms are written."""
        container = MagicMock()
        container.tags = None
        container.add_tags.side_effect = lambda: setattr(container, "tags", {})
        mp4_ctor = MagicMock(return_value=container)
        monkeypatch.setattr("nomarr.components.tagging.tagging_writer_comp.MP4", mp4_ctor)

        _MP4Writer().write(Path("/tmp/.song.abc123.nomarr-tmp"), {"genre": ["rock", "pop"]})

        container.add_tags.assert_called_once_with()
        atom_values = container.tags["----:com.apple.iTunes:nom:genre"]
        assert [bytes(value) for value in atom_values] == [b"rock", b"pop"]
        container.save.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_to_path_dispatches_m4a_to_mp4_writer(self) -> None:
        """The m4a/mp4/m4b branch of ``_write_to_path`` passes the raw path to ``_mp4``."""
        writer = TagWriter()
        writer._mp4 = MagicMock()

        writer._write_to_path("/tmp/.song.abc123.nomarr-tmp", {"genre": "rock"}, source_ext="m4a")

        writer._mp4.write.assert_called_once_with("/tmp/.song.abc123.nomarr-tmp", {"genre": "rock"})


class TestTagWriterWriteSafe:
    """Tests for ``TagWriter.write_safe()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_safe_with_none_clears_namespace_with_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        writer = TagWriter()
        writer._write_to_path = MagicMock()

        def fake_safe_write_tags(path, library_root, write_fn, expected_mtime_ms) -> SafeWriteResult:
            write_fn(Path("/tmp/temp.flac"))
            return SafeWriteResult(success=True, error=None)

        monkeypatch.setattr(
            "nomarr.components.tagging.tagging_writer_comp.safe_write_tags",
            fake_safe_write_tags,
        )

        lib_path = _valid_library_path("song.flac")
        result = writer.write_safe(lib_path, None, library_root=Path("/music"), expected_mtime_ms=1000)

        assert result.success is True
        writer._write_to_path.assert_called_once()
        assert writer._write_to_path.call_args.args[1] == {}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_safe_with_tags_passes_to_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        writer = TagWriter()
        writer._write_to_path = MagicMock()

        def fake_safe_write_tags(path, library_root, write_fn, expected_mtime_ms) -> SafeWriteResult:
            write_fn(Path("/tmp/temp.flac"))
            return SafeWriteResult(success=True, error=None)

        monkeypatch.setattr(
            "nomarr.components.tagging.tagging_writer_comp.safe_write_tags",
            fake_safe_write_tags,
        )

        lib_path = _valid_library_path("song.flac")
        result = writer.write_safe(lib_path, _make_tags(), library_root=Path("/music"), expected_mtime_ms=1000)

        assert result.success is True
        assert writer._write_to_path.call_args.args[1] == {"genre": ("rock", "pop")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_safe_returns_failure_for_invalid_path(self) -> None:
        writer = TagWriter()
        lib_path = LibraryPath(
            relative="song.mp3",
            absolute=Path("/music/song.mp3"),
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )
        result = writer.write_safe(lib_path, _make_tags(), library_root=Path("/music"), expected_mtime_ms=1000)
        assert result.success is False
        assert "Invalid path" in (result.error or "")


class TestWriteSafeRealCallerPath:
    """Non-mock caller path: real TagWriter.write_safe -> safe_write_tags -> _write_to_path -> _MP3Writer."""

    @pytest.mark.integration
    def test_real_callers_write_and_reopen(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(b"headerless audio bytes")
        lib_path = LibraryPath(relative="song.mp3", absolute=original, library_id=1, status="valid")
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties",
            lambda _p: _GOOD_PROPS,
        )
        # The capability boundary is substituted with True so the temp keeps its audio
        # extension (the hardlink temp is ``{uuid}_song.mp3``); the fallback temp is
        # ``*.nomarr-tmp`` and would not round-trip through ``_write_to_path``'s extension
        # routing, which is what the unit fallback tests (byte-writer ``write_fn``) pin.
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._supports_hardlinks",
            lambda *_a, **_k: True,
        )
        mtime_ms = int(original.stat().st_mtime * 1000)
        writer = TagWriter()

        result = writer.write_safe(lib_path, _make_tags(), library_root=tmp_path, expected_mtime_ms=mtime_ms)

        assert result.success is True
        id3 = ID3(str(original))
        assert any(getattr(frame, "desc", "") == "nom:genre" for frame in id3.values())

    @pytest.mark.integration
    def test_real_callers_classify_replace_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(b"headerless audio bytes")
        lib_path = LibraryPath(relative="song.mp3", absolute=original, library_id=1, status="valid")
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties",
            lambda _p: _GOOD_PROPS,
        )
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._supports_hardlinks",
            lambda *_a, **_k: True,
        )

        def boom_replace(*_a: object, **_k: object) -> None:
            raise OSError(errno.EACCES, "replace denied")

        monkeypatch.setattr("nomarr.components.tagging.safe_write_comp.os.replace", boom_replace)
        mtime_ms = int(original.stat().st_mtime * 1000)
        writer = TagWriter()

        result = writer.write_safe(lib_path, _make_tags(), library_root=tmp_path, expected_mtime_ms=mtime_ms)

        assert result.success is False
        assert result.fs_fact is not None
        assert result.fs_fact.kind == "permission_denied"
        assert original.read_bytes() == b"headerless audio bytes"

    @pytest.mark.integration
    def test_real_callers_fallback_writes_through_nomarr_tmp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """C2: the real fallback branch writes through the non-audio ``.nomarr-tmp`` temp.

        Only the probe and filesystem-capability boundaries are substituted; the real
        ``TagWriter.write_safe`` -> ``safe_write_tags`` -> ``_write_to_path`` -> ``_MP3Writer``
        closure runs on a real file. The format must come from the original path (the
        ``source_ext`` hint), never from the ``.nomarr-tmp`` temp name.
        """
        original = tmp_path / "song.mp3"
        original.write_bytes(b"headerless audio bytes")
        lib_path = LibraryPath(relative="song.mp3", absolute=original, library_id=1, status="valid")
        probed: list[Path] = []

        def recording_probe(path: Path) -> _AudioProperties:
            probed.append(Path(path))
            return _GOOD_PROPS

        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties",
            recording_probe,
        )
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._supports_hardlinks",
            lambda *_a, **_k: False,
        )
        mtime_ms = int(original.stat().st_mtime * 1000)
        writer = TagWriter()

        result = writer.write_safe(lib_path, _make_tags(), library_root=tmp_path, expected_mtime_ms=mtime_ms)

        assert result.success is True
        # The second probe target is the fallback's same-directory temp: non-audio, yet written.
        assert len(probed) == 2
        temp_path = probed[1]
        assert temp_path.name.endswith(".nomarr-tmp")
        assert not temp_path.exists()
        assert list(tmp_path.glob(".*.nomarr-tmp")) == []
        id3 = ID3(str(original))
        assert any(getattr(frame, "desc", "") == "nom:genre" for frame in id3.values())

    @pytest.mark.integration
    def test_real_callers_contain_unsupported_extension(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The real closure contains ``_write_to_path``'s ``RuntimeError`` for unknown extensions.

        A ``.wav`` original routes to no writer; the real ``TagWriter.write_safe`` closure raises
        ``RuntimeError('Unsupported file type for writing: .wav')`` inside ``write_fn`` and the
        non-``OSError`` containment returns a failure result instead of letting it escape.
        """
        original = tmp_path / "song.wav"
        original.write_bytes(b"headerless audio bytes")
        lib_path = LibraryPath(relative="song.wav", absolute=original, library_id=1, status="valid")
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties",
            lambda _p: _GOOD_PROPS,
        )
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._supports_hardlinks",
            lambda *_a, **_k: False,
        )
        mtime_ms = int(original.stat().st_mtime * 1000)
        writer = TagWriter()

        result = writer.write_safe(lib_path, _make_tags(), library_root=tmp_path, expected_mtime_ms=mtime_ms)

        assert result.success is False
        assert "Unsupported file type" in (result.error or "")
        assert original.read_bytes() == b"headerless audio bytes"
        assert list(tmp_path.glob(".*.nomarr-tmp")) == []

    @pytest.mark.integration
    def test_real_probe_and_sanity_check_on_real_audio(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """C4: the real ``_probe_audio_properties`` body runs over a real FLAC fixture.

        Every other real-caller test stubs the probe. Only the filesystem-capability boundary
        (``_supports_hardlinks``) is substituted here; the probe, ``_check_audio_properties``,
        the real ``_VorbisWriter`` and ``safe_write_tags`` all run over real audio.
        """
        fixture = (
            Path(__file__).resolve().parents[4] / "tests/fixtures/library/good/AllFormats/SameTrack/cooltrack.flac"
        )
        original = tmp_path / "cooltrack.flac"
        shutil.copy2(fixture, original)
        lib_path = LibraryPath(relative="cooltrack.flac", absolute=original, library_id=1, status="valid")

        before_file = mutagen.File(str(original))
        assert before_file is not None
        before = before_file.info

        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._supports_hardlinks",
            lambda *_a, **_k: True,
        )
        mtime_ms = int(original.stat().st_mtime * 1000)

        result = TagWriter().write_safe(lib_path, _make_tags(), library_root=tmp_path, expected_mtime_ms=mtime_ms)

        assert result.success is True
        after_file = mutagen.File(str(original))
        assert after_file is not None
        after = after_file.info
        assert abs(after.length - before.length) <= DURATION_TOLERANCE_S
        assert after.sample_rate == before.sample_rate
        assert after.channels == before.channels
        assert list(tmp_path.glob(".*.nomarr-tmp")) == []
        assert list(tmp_path.glob(".*.nomarr-bak")) == []

    @pytest.mark.integration
    @pytest.mark.requires_audio
    @pytest.mark.parametrize(
        ("source_ext", "constructor"),
        [("m4a", MP4), ("flac", FLAC), ("ogg", OggVorbis)],
    )
    def test_real_callers_round_trip_via_real_probe(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        source_ext: str,
        constructor: type[mutagen.FileType],
    ) -> None:
        """Real ``write_safe`` with the real probe persists ``nom:`` for m4a/flac/ogg.

        Only the filesystem-capability boundary (``_supports_hardlinks``) is substituted;
        ``_probe_audio_properties`` runs for real.
        """
        original = tmp_path / f"cooltrack.{source_ext}"
        shutil.copy2(_FIXTURE_DIR / f"cooltrack.{source_ext}", original)
        lib_path = LibraryPath(relative=original.name, absolute=original, library_id=1, status="valid")
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._supports_hardlinks",
            lambda *_a, **_k: True,
        )
        mtime_ms = int(original.stat().st_mtime * 1000)

        result = TagWriter().write_safe(lib_path, _make_tags(), library_root=tmp_path, expected_mtime_ms=mtime_ms)

        assert result.success is True
        tags = constructor(str(original)).tags
        assert tags is not None
        if source_ext == "m4a":
            assert bytes(tags["----:com.apple.iTunes:nom:genre"][0]) == b"rock"
        else:
            assert tags["NOM_GENRE"] == ["rock", "pop"]

    @pytest.mark.integration
    @pytest.mark.requires_audio
    def test_real_callers_round_trip_opus_with_real_probe(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Opus works end to end through the real probe and real ``OggOpus`` writer (no stub)."""
        original = tmp_path / "cooltrack.opus"
        shutil.copy2(_FIXTURE_DIR / "cooltrack.opus", original)
        lib_path = LibraryPath(relative=original.name, absolute=original, library_id=1, status="valid")
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._supports_hardlinks",
            lambda *_a, **_k: True,
        )
        mtime_ms = int(original.stat().st_mtime * 1000)

        result = TagWriter().write_safe(lib_path, _make_tags(), library_root=tmp_path, expected_mtime_ms=mtime_ms)

        assert result.success is True
        tags = OggOpus(str(original)).tags
        assert tags is not None
        assert tags["NOM_GENRE"] == ["rock", "pop"]

    @pytest.mark.integration
    def test_mp4_writer_raises_when_mapping_stays_none(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A container whose ``tags`` stays ``None`` after ``add_tags()`` must raise, not return."""
        container = MagicMock()
        container.tags = None
        container.add_tags.side_effect = None
        monkeypatch.setattr("nomarr.components.tagging.tagging_writer_comp.MP4", MagicMock(return_value=container))

        with pytest.raises(RuntimeError):
            _MP4Writer().write(tmp_path / "song.m4a", {"genre": "rock"})

        container.save.assert_not_called()

    @pytest.mark.integration
    def test_vorbis_writer_raises_when_mapping_stays_none(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The FLAC branch must raise (not return) when the mapping stays ``None``."""
        container = MagicMock()
        container.tags = None
        container.add_tags.side_effect = None
        monkeypatch.setattr("nomarr.components.tagging.tagging_writer_comp.FLAC", MagicMock(return_value=container))

        with pytest.raises(RuntimeError):
            _VorbisWriter().write(tmp_path / "song.flac", {"genre": "rock"}, source_ext="flac")

        container.save.assert_not_called()

    @pytest.mark.integration
    def test_real_callers_contain_writer_failure_with_fake_container(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A writer that raises is contained into ``success=False`` and leaves the original intact."""
        original = tmp_path / "song.flac"
        original.write_bytes(b"headerless audio bytes")
        lib_path = LibraryPath(relative=original.name, absolute=original, library_id=1, status="valid")
        container = MagicMock()
        container.tags = None
        container.add_tags.side_effect = None
        monkeypatch.setattr("nomarr.components.tagging.tagging_writer_comp.FLAC", MagicMock(return_value=container))
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties",
            lambda _p: _GOOD_PROPS,
        )
        monkeypatch.setattr(
            "nomarr.components.tagging.safe_write_comp._supports_hardlinks",
            lambda *_a, **_k: True,
        )
        mtime_ms = int(original.stat().st_mtime * 1000)

        result = TagWriter().write_safe(lib_path, _make_tags(), library_root=tmp_path, expected_mtime_ms=mtime_ms)

        assert result.success is False
        assert result.error
        assert original.read_bytes() == b"headerless audio bytes"

    @pytest.mark.integration
    def test_vorbis_writer_adds_tags_when_container_has_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A Vorbis container with no tag mapping gets ``add_tags()`` and reaches ``save()``.

        Discrimination: the pre-fix guard ``if not isinstance(vorbis_file.tags, dict):
        return`` silently returned before ``save()`` for every real Vorbis mapping
        (``VCFLACDict``/``VCommentDict`` are ``list`` subclasses, never ``dict``). The
        mapping installed by ``add_tags()`` here is deliberately a non-``dict`` stub, so
        that pre-fix guard would return early and fail the write and ``save()``
        assertions; the corrected writer persists through the container's real mapping.
        """
        mapping = MagicMock()
        container = MagicMock()
        container.tags = None
        container.add_tags.side_effect = lambda: setattr(container, "tags", mapping)
        monkeypatch.setattr("nomarr.components.tagging.tagging_writer_comp.FLAC", MagicMock(return_value=container))

        _VorbisWriter().write(Path("/tmp/.song.abc123.nomarr-tmp"), {"genre": ("rock",)}, source_ext="flac")

        container.add_tags.assert_called_once_with()
        mapping.__setitem__.assert_called_once_with("NOM_GENRE", ["rock"])
        container.save.assert_called_once_with()


class TestWriterRealRoundTripPerContainer:
    """Site 1: each real format writer persists ``nom:`` tags read back from disk."""

    @pytest.mark.integration
    @pytest.mark.requires_audio
    def test_mp4_writer_round_trip_persists_nom_atom(self, tmp_path: Path) -> None:
        """``_MP4Writer.write`` reaches ``save()`` and the freeform atom is on disk."""
        target = tmp_path / "cooltrack.m4a"
        shutil.copy2(_FIXTURE_DIR / "cooltrack.m4a", target)

        _MP4Writer().write(target, {"genre": ["rock"]})

        tags = MP4(str(target)).tags
        assert tags is not None
        atom_key = "----:com.apple.iTunes:nom:genre"
        assert atom_key in tags
        assert bytes(tags[atom_key][0]) == b"rock"

    @pytest.mark.integration
    @pytest.mark.requires_audio
    @pytest.mark.parametrize(
        ("source_ext", "constructor"),
        [("flac", FLAC), ("ogg", OggVorbis), ("opus", OggOpus)],
    )
    def test_vorbis_writer_round_trip_persists_nom_comment(
        self,
        tmp_path: Path,
        source_ext: str,
        constructor: type[mutagen.FileType],
    ) -> None:
        """``_VorbisWriter.write`` reaches ``save()`` for flac/ogg/opus.

        mutagen lower-cases Vorbis keys on write and ``VCommentDict`` lookups are
        case-insensitive, so ``["NOM_GENRE"]`` finds the on-disk ``nom_genre``.
        """
        target = tmp_path / f"cooltrack.{source_ext}"
        shutil.copy2(_FIXTURE_DIR / f"cooltrack.{source_ext}", target)

        _VorbisWriter().write(target, {"genre": ["rock"]}, source_ext=source_ext)

        tags = constructor(str(target)).tags
        assert tags is not None
        assert tags["NOM_GENRE"] == ["rock"]

    @pytest.mark.integration
    def test_mp3_writer_round_trip_persists_nom_frame(self, tmp_path: Path) -> None:
        """``_MP3Writer.write`` works on a synthetic headerless file (only MP3 worked pre-fix)."""
        target = tmp_path / "song.mp3"
        target.write_bytes(b"headerless audio bytes")

        _MP3Writer().write(target, {"genre": ["rock"]})

        id3 = ID3(str(target))
        assert any(
            getattr(frame, "desc", "") == "nom:genre" and getattr(frame, "text", []) == ["rock"]
            for frame in id3.values()
        )

    @pytest.mark.integration
    def test_mp3_writer_round_trip_persists_native_multi_value_frame(self, tmp_path: Path) -> None:
        """Site 4: a production tuple payload persists as one native ID3v2.4 multi-value frame.

        ``TagWriter.write_safe`` always hands the writer a tuple payload (``Tags.to_dict()``);
        the multi-value branch must therefore accept tuples and store a native list on disk
        (``["rock", "pop"]``), never one ``_to_text_value`` JSON string (``'["rock","pop"]'``).
        """
        target = tmp_path / "song.mp3"
        target.write_bytes(b"headerless audio bytes")

        _MP3Writer().write(target, {"genre": ("rock", "pop")})

        frame = next(f for f in ID3(str(target)).values() if getattr(f, "desc", "") == "nom:genre")
        assert frame.text == ["rock", "pop"]
        assert frame.text != ['["rock","pop"]']

    @pytest.mark.integration
    def test_mp3_writer_round_trip_persists_single_value_production_tuple(self, tmp_path: Path) -> None:
        """Site 4: a production single-value tuple persists natively on MP3, not as JSON.

        ``Tags.to_dict()`` always yields tuples, so a single-value tag arrives as a
        one-element tuple. The native branch must treat that as the multi-value shape
        and store ``["rock"]``, never ``_to_text_value(("rock",))`` (``'["rock"]'``).
        """
        target = tmp_path / "song.mp3"
        target.write_bytes(b"headerless audio bytes")

        payload = Tags(items=(Tag(name="genre", values=("rock",)),)).to_dict()
        assert payload == {"genre": ("rock",)}

        _MP3Writer().write(target, payload)

        frame = next(f for f in ID3(str(target)).values() if getattr(f, "desc", "") == "nom:genre")
        assert list(frame.text) == ["rock"]
        assert list(frame.text) != ['["rock"]']

    @pytest.mark.integration
    @pytest.mark.parametrize(
        ("payload", "expected_frame_text"),
        [
            ((1, 2), ["[1,2]"]),
            (("rock", 1), ['["rock",1]']),
            ("rock", ["rock"]),
        ],
        ids=["int-tuple-keeps-json", "mixed-tuple-keeps-json", "scalar-keeps-text"],
    )
    def test_mp3_writer_keeps_json_branch_for_non_str_tuple_elements(
        self,
        tmp_path: Path,
        payload: object,
        expected_frame_text: list[str],
    ) -> None:
        """A non-``str``-element payload keeps the ``_to_text_value`` branch, not native multi-value.

        Discrimination: the native branch is gated by
        ``all(isinstance(x, str) for x in tag_value)``. Dropping that gate while keeping the
        widening/normalization would persist ``(1, 2)`` natively as ``["1", "2"]`` and
        ``("rock", 1)`` as ``["rock", "1"]``; the scalar ``"rock"`` must stay ``["rock"]``.
        The assertions pin the on-disk frame text read back from a real file.
        """
        target = tmp_path / "song.mp3"
        target.write_bytes(b"headerless audio bytes")

        _MP3Writer().write(target, {"genre": payload})

        frame = next(f for f in ID3(str(target)).values() if getattr(f, "desc", "") == "nom:genre")
        assert frame.text == expected_frame_text

    @pytest.mark.integration
    @pytest.mark.requires_audio
    def test_mp4_writer_keeps_json_branch_for_non_str_tuple_elements(self, tmp_path: Path) -> None:
        """A non-``str``-element payload on MP4 keeps one ``_to_text_value`` JSON atom value.

        Discrimination: dropping the ``all(isinstance(x, str))`` gate while keeping the
        ``list | tuple`` widening would persist ``(1, 2)`` as two freeform values
        ``[b"1", b"2"]``; the corrected writer must instead encode ``_to_text_value((1, 2))``
        as a single ``[b"[1,2]"]`` read back from the real fixture on disk.
        """
        target = tmp_path / "cooltrack.m4a"
        shutil.copy2(_FIXTURE_DIR / "cooltrack.m4a", target)

        _MP4Writer().write(target, {"genre": (1, 2)})

        tags = MP4(str(target)).tags
        assert tags is not None
        values = [bytes(value) for value in tags["----:com.apple.iTunes:nom:genre"]]
        assert values == [b"[1,2]"]
        assert values != [b"1", b"2"]

    @pytest.mark.integration
    @pytest.mark.requires_audio
    @pytest.mark.parametrize(
        ("source_ext", "constructor"),
        [("flac", FLAC), ("ogg", OggVorbis)],
    )
    def test_vorbis_writer_keeps_json_branch_for_non_str_tuple_elements(
        self,
        tmp_path: Path,
        source_ext: str,
        constructor: type[mutagen.FileType],
    ) -> None:
        """A non-``str``-element payload on Vorbis keeps one JSON comment value.

        Discrimination: dropping the ``all(isinstance(x, str))`` gate while keeping the
        ``list | tuple`` widening would persist ``(1, 2)`` natively as ``["1", "2"]``;
        the corrected writer must instead store ``_to_text_value((1, 2))`` as
        ``["[1,2]"]`` read back from the real fixture on disk.
        """
        target = tmp_path / f"cooltrack.{source_ext}"
        shutil.copy2(_FIXTURE_DIR / f"cooltrack.{source_ext}", target)

        _VorbisWriter().write(target, {"genre": (1, 2)}, source_ext=source_ext)

        tags = constructor(str(target)).tags
        assert tags is not None
        assert tags["NOM_GENRE"] == ["[1,2]"]
        assert tags["NOM_GENRE"] != ["1", "2"]
