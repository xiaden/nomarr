"""Tests for safe_write_comp - atomic tag writing with audio sanity verification."""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nomarr.components.tagging import safe_write_comp
from nomarr.components.tagging.safe_write_comp import (
    SafeWriteResult,
    _AudioProperties,
    _probe_audio_properties,
    safe_write_tags,
)
from nomarr.helpers.dto.path_dto import LibraryPath
from nomarr.helpers.files_helper import AUDIO_EXTENSIONS, is_audio_file

pytestmark = [pytest.mark.unit]

_GOOD_PROPS = _AudioProperties(duration=180.0, sample_rate=44100, channels=2)

_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests/fixtures/library/good/AllFormats/SameTrack"

_OLD_BYTES = b"old original bytes"
_NEW_BYTES = b"new written bytes"


def _make_library_path(path: Path) -> LibraryPath:
    return LibraryPath(relative=path.name, absolute=path, library_id="test_lib", status="valid")


def _write_new_bytes(temp_path: Path) -> None:
    Path(temp_path).write_bytes(_NEW_BYTES)


def _force_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safe_write_comp, "_supports_hardlinks", lambda *_a, **_k: False)


def _force_hardlink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safe_write_comp, "_supports_hardlinks", lambda *_a, **_k: True)


def _stub_probe(monkeypatch: pytest.MonkeyPatch, *, fail_after_original: bool = False) -> None:
    calls = {"count": 0}

    def probe(_path: Path) -> _AudioProperties:
        calls["count"] += 1
        if fail_after_original and calls["count"] >= 2:
            raise OSError(errno.EIO, "probe failed")
        return _GOOD_PROPS

    monkeypatch.setattr(safe_write_comp, "_probe_audio_properties", probe)


def _leftover_names(base: Path, suffix: str) -> list[str]:
    """Names of files in ``base`` (and its ``.ignore`` temp folder) ending in ``suffix``."""
    names = [p.name for p in base.iterdir() if p.name.endswith(suffix)]
    ignore = base / ".ignore"
    if ignore.is_dir():
        names += [p.name for p in ignore.iterdir() if p.name.endswith(suffix)]
    return names


def _install_post_replace_stat_failure(monkeypatch: pytest.MonkeyPatch, original: Path) -> None:
    """Make the post-``os.replace`` ``os.stat`` raise, while the pre-flight stat succeeds."""
    real_replace = os.replace
    real_stat = os.stat
    state = {"replaced": False}

    def fake_replace(src: object, dst: object, *args: object, **kwargs: object) -> None:
        real_replace(src, dst, *args, **kwargs)
        state["replaced"] = True

    def fake_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if state["replaced"] and os.fspath(path) == os.fspath(original):
            raise OSError(errno.EIO, "stat after replace failed")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(safe_write_comp.os, "replace", fake_replace)
    monkeypatch.setattr(safe_write_comp.os, "stat", fake_stat)


class TestSafeWriteVerification:
    """Tests that audio property sanity check is always performed."""

    def test_audio_properties_verified_on_success(self, tmp_path: Path) -> None:
        """Audio properties are probed and compared for every write."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio content")

        library_path = LibraryPath(
            relative="test.mp3",
            absolute=test_file,
            library_id="test_lib",
            status="valid",
        )

        def mock_write_fn(temp_path: Path) -> None:
            temp_path.touch()

        with patch("nomarr.components.tagging.safe_write_comp._probe_audio_properties") as mock_probe:
            mock_probe.return_value = _GOOD_PROPS

            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, mock_write_fn, mtime_ms)

            # Probed twice: original before copy, temp after write
            assert mock_probe.call_count == 2
            assert result.success is True

    def test_duration_mismatch_returns_failure(self, tmp_path: Path) -> None:
        """Returns failure when duration differs beyond tolerance after write."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio content")

        library_path = LibraryPath(
            relative="test.mp3",
            absolute=test_file,
            library_id="test_lib",
            status="valid",
        )

        def mock_write_fn(temp_path: Path) -> None:
            temp_path.touch()

        truncated_props = _AudioProperties(duration=10.0, sample_rate=44100, channels=2)

        with patch("nomarr.components.tagging.safe_write_comp._probe_audio_properties") as mock_probe:
            mock_probe.side_effect = [_GOOD_PROPS, truncated_props]

            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, mock_write_fn, mtime_ms)

            assert result.success is False
            assert result.outcome == "audio_sanity_failed"
            assert result.fs_fact is None

    def test_sample_rate_mismatch_returns_failure(self, tmp_path: Path) -> None:
        """Returns failure when sample rate changes after write."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio content")

        library_path = LibraryPath(
            relative="test.mp3",
            absolute=test_file,
            library_id="test_lib",
            status="valid",
        )

        def mock_write_fn(temp_path: Path) -> None:
            temp_path.touch()

        wrong_sr_props = _AudioProperties(duration=180.0, sample_rate=22050, channels=2)

        with patch("nomarr.components.tagging.safe_write_comp._probe_audio_properties") as mock_probe:
            mock_probe.side_effect = [_GOOD_PROPS, wrong_sr_props]

            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, mock_write_fn, mtime_ms)

            assert result.success is False
            assert result.outcome == "audio_sanity_failed"
            assert result.fs_fact is None

    def test_channels_mismatch_returns_failure(self, tmp_path: Path) -> None:
        """Returns failure when the channel count changes after write."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(_OLD_BYTES)

        library_path = LibraryPath(
            relative="test.mp3",
            absolute=test_file,
            library_id="test_lib",
            status="valid",
        )

        def mock_write_fn(temp_path: Path) -> None:
            temp_path.touch()

        wrong_channels_props = _AudioProperties(duration=180.0, sample_rate=44100, channels=1)

        with patch("nomarr.components.tagging.safe_write_comp._probe_audio_properties") as mock_probe:
            mock_probe.side_effect = [_GOOD_PROPS, wrong_channels_props]

            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, mock_write_fn, mtime_ms)

            assert result.success is False
            assert result.outcome == "audio_sanity_failed"
            assert result.fs_fact is None
            assert test_file.read_bytes() == _OLD_BYTES

    def test_probe_failure_on_original_returns_failure(self, tmp_path: Path) -> None:
        """Returns failure when the original file cannot be probed."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"not a real audio file")

        library_path = LibraryPath(
            relative="test.mp3",
            absolute=test_file,
            library_id="test_lib",
            status="valid",
        )

        with patch(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties",
            side_effect=RuntimeError("mutagen could not read audio file"),
        ):
            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, lambda _: None, mtime_ms)

            assert result.success is False
            assert result.outcome == "probe_unsupported"
            assert result.fs_fact is None


class TestSafeWriteResult:
    """Tests for SafeWriteResult dataclass."""

    def test_success_result(self) -> None:
        """Can create a success result."""
        result = SafeWriteResult(success=True)
        assert result.success is True
        assert result.error is None

    def test_failure_result(self) -> None:
        """A failure result derives ``error`` from the structured outcome."""
        result = SafeWriteResult(success=False, outcome="write_failed")
        assert result.success is False
        assert result.outcome == "write_failed"
        assert result.error == "write_failed"


class TestSafeWriteResultFactField:
    """The SafeWriteResult.fs_fact field carries the structured Part A fact."""

    def test_default_is_none(self) -> None:
        """A result constructed without the fact exposes ``fs_fact is None``."""
        assert SafeWriteResult(success=True).fs_fact is None

    def test_positional_field_order_is_stable(self) -> None:
        """``outcome`` is the fourth positional field, after success/new_mtime_ms/fs_fact."""
        fact = _present_fact()
        result = SafeWriteResult(True, None, fact, None)
        assert result.success is True
        assert result.error is None
        assert result.new_mtime_ms is None
        assert result.fs_fact is fact
        assert result.outcome is None

    def test_fact_round_trips_on_field(self) -> None:
        """A constructed FsFact round-trips unchanged on the field."""
        fact = _present_fact()
        result = SafeWriteResult(success=True, fs_fact=fact)
        assert result.fs_fact is fact
        assert result.fs_fact is not None
        assert result.fs_fact.presence == "present"


def _present_fact():
    from nomarr.helpers.fs_contract import FsFact

    return FsFact(presence="present", kind=None, errno=None)


class TestSafeWritePreflightClassification:
    """Pre-write ``OSError`` sites are classified into the structured fact."""

    def test_preflight_stat_stale_is_classified(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A stale-mount pre-flight ``os.stat`` failure is a classified storage_unavailable."""
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        real_stat = os.stat

        def fake_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            if os.fspath(path) == os.fspath(original):
                raise OSError(errno.ESTALE, "stale file handle")
            return real_stat(path, *args, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(safe_write_comp.os, "stat", fake_stat)
            result = safe_write_tags(library_path, tmp_path, _write_new_bytes, 0)

        assert result.success is False
        assert result.fs_fact is not None
        assert result.fs_fact.kind == "storage_unavailable"
        assert original.exists()
        assert original.read_bytes() == _OLD_BYTES

    def test_temp_folder_mkdir_permission_is_classified(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A ``_get_temp_folder`` ``mkdir`` EACCES is a classified permission_denied."""
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        real_stat = os.stat
        mtime_ms = int(real_stat(original).st_mtime * 1000)
        monkeypatch.setattr(safe_write_comp, "_probe_audio_properties", lambda _p: _GOOD_PROPS)

        def boom_mkdir(_self: Path, *_a: object, **_k: object) -> None:
            raise OSError(errno.EACCES, "mkdir denied")

        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "mkdir", boom_mkdir)
            result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is False
        assert result.fs_fact is not None
        assert result.fs_fact.kind == "permission_denied"
        assert original.exists()
        assert original.read_bytes() == _OLD_BYTES


class TestSafeWriteFallbackAtomicity:
    """The fallback path never loses the original at any mutation boundary."""

    @pytest.mark.parametrize(
        "boundary",
        ["shutil_copy2", "write_fn", "post_write_probe", "os_replace"],
    )
    def test_failure_never_loses_original(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        boundary: str,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_fallback(monkeypatch)
        _stub_probe(monkeypatch, fail_after_original=boundary == "post_write_probe")
        write_fn = _write_new_bytes

        if boundary == "shutil_copy2":

            def boom_copy(*_a: object, **_k: object) -> None:
                raise OSError(errno.EIO, "copy failed")

            monkeypatch.setattr(safe_write_comp.shutil, "copy2", boom_copy)
        elif boundary == "write_fn":

            def boom_write(_temp: Path) -> None:
                raise OSError(errno.EIO, "write failed")

            write_fn = boom_write
        elif boundary == "os_replace":

            def boom_replace(*_a: object, **_k: object) -> None:
                raise OSError(errno.EACCES, "replace failed")

            monkeypatch.setattr(safe_write_comp.os, "replace", boom_replace)

        result = safe_write_tags(library_path, tmp_path, write_fn, mtime_ms)

        assert result.success is False
        assert original.exists()
        assert original.read_bytes() in {_OLD_BYTES, _NEW_BYTES}
        assert original.read_bytes() == _OLD_BYTES
        assert _leftover_names(tmp_path, ".nomarr-tmp") == []

    def test_success_replaces_original_and_cleans_temp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_fallback(monkeypatch)
        _stub_probe(monkeypatch)

        result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is True
        assert original.exists()
        assert original.read_bytes() == _NEW_BYTES
        assert _leftover_names(tmp_path, ".nomarr-tmp") == []

    def test_post_replace_stat_failure_is_advisory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_fallback(monkeypatch)
        _stub_probe(monkeypatch)

        with monkeypatch.context() as scoped:
            _install_post_replace_stat_failure(scoped, original)
            result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is True
        assert result.new_mtime_ms is None
        assert result.fs_fact is not None
        assert original.exists()
        assert original.read_bytes() == _NEW_BYTES


class TestSafeWriteHardlinkAtomicity:
    """The hardlink path never leaves the original absent at any mutation boundary."""

    @pytest.mark.parametrize(
        "boundary",
        [
            "shutil_copy2",
            "write_fn",
            "post_write_probe",
            "os_link",
            "os_replace",
            "backup_unlink",
            "post_replace_stat",
        ],
    )
    def test_original_never_lost(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        boundary: str,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_hardlink(monkeypatch)
        _stub_probe(monkeypatch, fail_after_original=boundary == "post_write_probe")
        write_fn = _write_new_bytes

        if boundary == "shutil_copy2":

            def boom_copy(*_a: object, **_k: object) -> None:
                raise OSError(errno.EIO, "copy failed")

            monkeypatch.setattr(safe_write_comp.shutil, "copy2", boom_copy)
        elif boundary == "write_fn":

            def boom_write(_temp: Path) -> None:
                raise OSError(errno.EIO, "write failed")

            write_fn = boom_write
        elif boundary == "os_link":

            def boom_link(*_a: object, **_k: object) -> None:
                raise OSError(errno.EPERM, "link denied")

            monkeypatch.setattr(safe_write_comp.os, "link", boom_link)
        elif boundary == "os_replace":

            def boom_replace(*_a: object, **_k: object) -> None:
                raise OSError(errno.EACCES, "replace failed")

            monkeypatch.setattr(safe_write_comp.os, "replace", boom_replace)
        elif boundary == "backup_unlink":
            real_unlink = Path.unlink

            def fake_unlink(self: Path, *args: object, **kwargs: object) -> None:
                if self.name.endswith(".nomarr-bak"):
                    raise OSError(errno.EACCES, "unlink denied")
                real_unlink(self, *args, **kwargs)

            monkeypatch.setattr(Path, "unlink", fake_unlink)
        elif boundary == "post_replace_stat":
            with monkeypatch.context() as scoped:
                _install_post_replace_stat_failure(scoped, original)
                result = safe_write_tags(library_path, tmp_path, write_fn, mtime_ms)
        if boundary != "post_replace_stat":
            result = safe_write_tags(library_path, tmp_path, write_fn, mtime_ms)

        assert original.exists(), f"original must never be absent at boundary {boundary}"
        assert original.read_bytes() in {_OLD_BYTES, _NEW_BYTES}

        if boundary == "os_link":
            assert result.success is False
            assert result.fs_fact is not None
            assert result.fs_fact.kind == "permission_denied"
            assert _leftover_names(tmp_path, ".nomarr-bak") == []
        elif boundary == "os_replace":
            assert result.success is False
            assert original.read_bytes() == _OLD_BYTES
            assert _leftover_names(tmp_path, ".nomarr-bak") == []
        elif boundary == "backup_unlink":
            assert result.success is True
            assert result.fs_fact is not None
            assert original.read_bytes() == _NEW_BYTES
        elif boundary == "post_replace_stat":
            assert result.success is True
            assert result.new_mtime_ms is None
            assert result.fs_fact is not None
            assert original.read_bytes() == _NEW_BYTES
        else:
            assert result.success is False
            assert result.fs_fact is not None

    def test_success_replaces_original_and_cleans_backup(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_hardlink(monkeypatch)
        _stub_probe(monkeypatch)

        result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is True
        assert original.exists()
        assert original.read_bytes() == _NEW_BYTES
        assert _leftover_names(tmp_path, ".nomarr-bak") == []

    def test_original_vanished_after_backup_link_preserves_backup(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """C3: the "original vanished after backup link" guard preserves the same-call backup.

        The guard aborts before ``os.replace``; the backup link created by this call stays in
        place (Q6b: never auto-restore/auto-delete), the temp is cleaned, and no ``OSError``
        escapes even though ``os.link`` removed the original.
        """
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_hardlink(monkeypatch)
        _stub_probe(monkeypatch)
        real_link = os.link
        created: list[Path] = []

        def link_then_remove_original(src: object, dst: object, *args: object, **kwargs: object) -> None:
            real_link(src, dst, *args, **kwargs)
            dst_path = Path(os.fspath(dst))
            if dst_path.name.endswith(".nomarr-bak"):
                created.append(dst_path)
                Path(os.fspath(src)).unlink()

        with monkeypatch.context() as scoped:
            scoped.setattr(safe_write_comp.os, "link", link_then_remove_original)
            result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is False
        assert result.outcome == "write_failed"
        assert result.fs_fact is None
        assert created, "expected the same-call backup link to be created before the guard"
        backup = created[0]
        assert backup.exists()
        assert backup.read_bytes() == _OLD_BYTES
        assert not original.exists()
        ignore_dir = tmp_path / ".ignore"
        assert not ignore_dir.exists() or not any(ignore_dir.iterdir())
        assert _leftover_names(tmp_path, ".nomarr-tmp") == []


class TestSafeWriteStaleBackupProvenance:
    """Q6b: provenance-uncertain backups and temps are preserved, never restored/overwritten."""

    def test_pre_existing_bak_files_are_preserved(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        user_bak = tmp_path / "song.mp3.bak"
        user_bak.write_bytes(b"user backup")
        orphan_bak = tmp_path / ".song.mp3.deadbeef.nomarr-bak"
        orphan_bak.write_bytes(b"orphan backup")
        stale_temp = tmp_path / ".song.mp3.cafe.nomarr-tmp"
        stale_temp.write_bytes(b"stale temp")
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_hardlink(monkeypatch)
        _stub_probe(monkeypatch)

        result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is True
        assert user_bak.exists()
        assert user_bak.read_bytes() == b"user backup"
        assert orphan_bak.exists()
        assert orphan_bak.read_bytes() == b"orphan backup"
        assert stale_temp.exists()
        assert stale_temp.read_bytes() == b"stale temp"

    def test_same_call_backup_collision_is_preserve_and_report(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        monkeypatch.setattr(safe_write_comp.uuid, "uuid4", lambda: SimpleNamespace(hex="deadbeef"))
        exact_backup = tmp_path / ".song.mp3.deadbeef.nomarr-bak"
        exact_backup.write_bytes(b"pre-existing backup")
        library_path = _make_library_path(original)
        real_stat = os.stat
        mtime_ms = int(real_stat(original).st_mtime * 1000)
        _force_hardlink(monkeypatch)
        _stub_probe(monkeypatch)

        result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is False
        assert result.fs_fact is not None
        assert result.fs_fact.kind == "wrong_resource_type"
        assert original.exists()
        assert original.read_bytes() == _OLD_BYTES
        assert exact_backup.exists()
        assert exact_backup.read_bytes() == b"pre-existing backup"

    def test_crash_leftover_is_not_renamed_over_original(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        leftover = tmp_path / ".song.mp3.deadbeef.nomarr-bak"
        leftover.write_bytes(b"crash leftover")
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_hardlink(monkeypatch)
        _stub_probe(monkeypatch)

        result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is True
        assert original.exists()
        assert original.read_bytes() == _NEW_BYTES
        assert leftover.exists()
        assert leftover.read_bytes() == b"crash leftover"


class TestSafeWriteBackupNameNonAudio:
    """Backup and temp names are non-audio so the scanner cannot upsert them as Songs."""

    def test_hardlink_backup_name_is_non_audio(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        link_targets: list[Path] = []
        real_link = os.link

        def spy_link(src: object, dst: object, *args: object, **kwargs: object) -> None:
            link_targets.append(Path(os.fspath(dst)))
            real_link(src, dst, *args, **kwargs)

        _force_hardlink(monkeypatch)
        _stub_probe(monkeypatch)
        monkeypatch.setattr(safe_write_comp.os, "link", spy_link)

        result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is True
        backup_names = [p.name for p in link_targets if p.name.endswith(".nomarr-bak")]
        assert backup_names, f"expected an os.link target ending .nomarr-bak, saw {link_targets}"
        backup_name = backup_names[0]
        assert is_audio_file(backup_name) is False
        assert Path(backup_name).suffix.lower() not in AUDIO_EXTENSIONS

    def test_fallback_temp_name_is_non_audio(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        recorded: list[Path] = []

        def recording_write_fn(temp_path: Path) -> None:
            recorded.append(Path(temp_path))
            Path(temp_path).write_bytes(_NEW_BYTES)

        _force_fallback(monkeypatch)
        _stub_probe(monkeypatch)

        result = safe_write_tags(library_path, tmp_path, recording_write_fn, mtime_ms)

        assert result.success is True
        assert len(recorded) == 1
        temp_name = recorded[0].name
        assert temp_name.endswith(".nomarr-tmp")
        assert is_audio_file(temp_name) is False
        assert Path(temp_name).suffix.lower() not in AUDIO_EXTENSIONS


class TestSafeWriteTempCleanupSuppression:
    """D-E9: a best-effort temp cleanup failure never escapes as a bare ``OSError``."""

    @staticmethod
    def _cleanup_failure_result(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        hardlink: bool,
    ) -> SafeWriteResult:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        if hardlink:
            _force_hardlink(monkeypatch)
        else:
            _force_fallback(monkeypatch)
        _stub_probe(monkeypatch)
        seen: dict[str, Path] = {}

        def recording_write_fn(temp_path: Path) -> None:
            seen["temp"] = Path(temp_path)
            Path(temp_path).write_bytes(_NEW_BYTES)

        real_unlink = Path.unlink
        real_stat = os.stat

        def fake_unlink(self: Path, *args: object, **kwargs: object) -> None:
            if seen.get("temp") == self:
                raise OSError(errno.EIO, "cleanup unlink failed")
            real_unlink(self, *args, **kwargs)

        def fake_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            temp = seen.get("temp")
            if temp is not None and os.fspath(path) == os.fspath(temp):
                raise OSError(errno.EIO, "cleanup stat failed")
            return real_stat(path, *args, **kwargs)

        def boom_replace(*_a: object, **_k: object) -> None:
            raise OSError(errno.EIO, "replace failed")

        with monkeypatch.context() as scoped:
            scoped.setattr(safe_write_comp.os, "replace", boom_replace)
            scoped.setattr(Path, "unlink", fake_unlink)
            scoped.setattr(safe_write_comp.os, "stat", fake_stat)
            result = safe_write_tags(library_path, tmp_path, recording_write_fn, mtime_ms)

        # The cleanup must be suppressed; the classified failure must survive unchanged and the
        # temp is left on disk rather than letting an OSError escape.
        assert result.success is False
        assert result.fs_fact is not None
        assert result.fs_fact.kind == "transient_io"
        assert original.exists()
        assert original.read_bytes() == _OLD_BYTES
        assert seen["temp"].exists()
        return result

    def test_fallback_cleanup_failure_does_not_escape(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._cleanup_failure_result(tmp_path, monkeypatch, hardlink=False)

    def test_hardlink_cleanup_failure_does_not_escape(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._cleanup_failure_result(tmp_path, monkeypatch, hardlink=True)


class TestSafeWriteFallbackSanityFailure:
    """D-E: the fallback sanity-check failure preserves the original and cleans the temp."""

    def test_fallback_audio_sanity_failure_preserves_original_and_cleans_temp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A mismatched after-probe fails the write, leaves the original, and removes the temp.

        The explicit ``unlink`` was removed from this branch; cleanup must still happen via the
        ``finally`` block.
        """
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        _force_fallback(monkeypatch)
        truncated_props = _AudioProperties(duration=10.0, sample_rate=44100, channels=2)
        probes = iter([_GOOD_PROPS, truncated_props])
        monkeypatch.setattr(safe_write_comp, "_probe_audio_properties", lambda _p: next(probes))

        result = safe_write_tags(library_path, tmp_path, _write_new_bytes, mtime_ms)

        assert result.success is False
        assert result.outcome == "audio_sanity_failed"
        assert result.fs_fact is None
        assert original.exists()
        assert original.read_bytes() == _OLD_BYTES
        assert _leftover_names(tmp_path, ".nomarr-tmp") == []


class TestSafeWriteNonOSErrorContainment:
    """A non-``OSError`` from ``write_fn`` is contained, never escapes ``safe_write_tags``."""

    @staticmethod
    def _leftover_artifacts(base: Path) -> list[str]:
        names = _leftover_names(base, ".nomarr-tmp") + _leftover_names(base, ".nomarr-bak")
        ignore = base / ".ignore"
        if ignore.is_dir():
            names += [p.name for p in ignore.iterdir()]
        return names

    @pytest.mark.parametrize("strategy", ["hardlink", "fallback"])
    def test_non_oserror_from_write_fn_is_contained(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        strategy: str,
    ) -> None:
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        mtime_ms = int(original.stat().st_mtime * 1000)
        if strategy == "hardlink":
            _force_hardlink(monkeypatch)
        else:
            _force_fallback(monkeypatch)
        _stub_probe(monkeypatch)

        def boom_write(_temp: Path) -> None:
            raise RuntimeError("boom")

        result = safe_write_tags(library_path, tmp_path, boom_write, mtime_ms)

        assert result.success is False
        assert result.outcome == "write_failed"
        assert result.fs_fact is None
        assert original.exists()
        assert original.read_bytes() == _OLD_BYTES
        assert self._leftover_artifacts(tmp_path) == []


class TestSafeWriteMtimeGuard:
    """DD v0.6 section 8.6: the mtime guard aborts a write when the file changed since the caller read it."""

    def test_stale_expected_mtime_aborts_write(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A stale ``expected_mtime_ms`` aborts before any probe or write, leaving the original intact."""
        original = tmp_path / "song.mp3"
        original.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(original)
        calls: list[Path] = []

        def recording_write_fn(temp_path: Path) -> None:
            calls.append(Path(temp_path))

        actual_mtime_ms = int(original.stat().st_mtime * 1000)
        stale_mtime_ms = actual_mtime_ms - 1
        # Good props prove the guard is what aborts: were the guard removed, the write would succeed.
        _stub_probe(monkeypatch)

        result = safe_write_tags(library_path, tmp_path, recording_write_fn, stale_mtime_ms)

        assert result.success is False
        assert result.outcome == "modified_externally"
        assert result.error == "file_modified_externally"
        assert result.new_mtime_ms is None
        # This abort is not a filesystem-fact classification (DD section 8.6).
        assert result.fs_fact is None
        assert original.exists()
        assert original.read_bytes() == _OLD_BYTES
        assert calls == []
        assert _leftover_names(tmp_path, ".nomarr-tmp") == []
        assert _leftover_names(tmp_path, ".nomarr-bak") == []


class TestSafeWriteInvalidPath:
    """The public ``safe_write_tags`` invalid-path guard returns before touching disk."""

    def test_invalid_library_path_returns_failure_without_write(
        self,
        tmp_path: Path,
    ) -> None:
        """A known library with an invalid path aborts with the invalid_path fact, never writing."""
        target = tmp_path / "song.mp3"
        library_path = LibraryPath(
            relative="song.mp3",
            absolute=target,
            library_id=1,
            status="not_found",
            reason="missing on disk",
        )
        calls: list[Path] = []

        def recording_write_fn(temp_path: Path) -> None:
            calls.append(Path(temp_path))

        result = safe_write_tags(library_path, tmp_path, recording_write_fn, 0)

        assert result.success is False
        assert result.outcome is None
        assert result.fs_fact is not None
        assert result.fs_fact.kind == "invalid_path"
        assert calls == []
        assert not target.exists()

    def test_invalid_library_path_without_library_reports_library_unresolved(
        self,
        tmp_path: Path,
    ) -> None:
        """An invalid path with no owning library is a domain/config miss, not a filesystem fact."""
        target = tmp_path / "song.mp3"
        library_path = LibraryPath(
            relative="song.mp3",
            absolute=target,
            library_id=None,
            status="not_found",
            reason="missing on disk",
        )
        calls: list[Path] = []

        def recording_write_fn(temp_path: Path) -> None:
            calls.append(Path(temp_path))

        result = safe_write_tags(library_path, tmp_path, recording_write_fn, 0)

        assert result.success is False
        assert result.outcome == "library_unresolved"
        assert result.fs_fact is None
        assert calls == []
        assert not target.exists()


class TestProbeAudioProperties:
    """C4: the real ``_probe_audio_properties`` body (no stub) is exercised directly."""

    def test_unreadable_file_raises_runtime_error(self, tmp_path: Path) -> None:
        """A file mutagen cannot identify raises ``RuntimeError`` naming the file."""
        unreadable = tmp_path / "mystery.dat"
        unreadable.write_bytes(b"not recognizable audio content")

        with pytest.raises(RuntimeError, match=r"mutagen could not read audio file: mystery\.dat"):
            _probe_audio_properties(unreadable)

    @pytest.mark.integration
    @pytest.mark.requires_audio
    def test_probe_opus_fixture_reports_decoded_48khz(self, tmp_path: Path) -> None:
        """Site 3: ``OggOpusInfo`` exposes no ``sample_rate``; the probe reports 48 kHz."""
        fixture = _FIXTURE_DIR / "cooltrack.opus"
        target = tmp_path / "cooltrack.opus"
        shutil.copy2(fixture, target)

        props = _probe_audio_properties(target)

        assert props.sample_rate == 48000
        assert props.channels == 1
        assert props.duration == pytest.approx(32.0, abs=1.0)

    def test_probe_info_without_sample_rate_raises_runtime_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-OggOpus info lacking ``sample_rate`` raises ``RuntimeError`` naming the info type.

        Boundary fake: no real fixture reaches this branch because every non-Opus fixture
        exposes ``sample_rate`` and Opus is an ``OggOpusInfo``. The guarded-getattr path is
        what turns a missing attribute into a named ``RuntimeError``; the pre-fix
        ``int(info.sample_rate)`` would surface an ``AttributeError`` instead.
        """
        target = tmp_path / "song.mp3"
        target.write_bytes(_OLD_BYTES)
        stub_audio = SimpleNamespace(info=SimpleNamespace(length=1.0, channels=2))
        monkeypatch.setattr(safe_write_comp.mutagen, "File", lambda _path: stub_audio)

        with pytest.raises(RuntimeError) as exc_info:
            _probe_audio_properties(target)

        message = str(exc_info.value)
        assert "SimpleNamespace" in message
        assert "sample_rate" in message

    def test_probe_no_sample_rate_contained_as_probe_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The no-sample-rate ``RuntimeError`` is contained into a ``SafeWriteResult`` failure."""
        target = tmp_path / "song.mp3"
        target.write_bytes(_OLD_BYTES)
        library_path = _make_library_path(target)
        stub_audio = SimpleNamespace(info=SimpleNamespace(length=1.0, channels=2))
        monkeypatch.setattr(safe_write_comp.mutagen, "File", lambda _path: stub_audio)

        mtime_ms = int(target.stat().st_mtime * 1000)
        result = safe_write_tags(library_path, tmp_path, lambda _: None, mtime_ms)

        assert isinstance(result, SafeWriteResult)
        assert result.success is False
        assert result.outcome == "probe_unsupported"
        assert result.fs_fact is None
        # The probe fails before any copy/write, so the original is untouched on disk.
        assert target.read_bytes() == _OLD_BYTES
