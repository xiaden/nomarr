"""Unit tests for files_helper.py — security-critical path validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nomarr.helpers.files_helper import (
    AUDIO_EXTENSIONS,
    collect_audio_files,
    is_audio_file,
    resolve_library_path,
    validate_library_path,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# is_audio_file
# ---------------------------------------------------------------------------


class TestIsAudioFile:
    """Tests for ``is_audio_file``."""

    def test_returns_true_for_supported_extensions(self):
        """Supported audio extensions return True."""
        for ext in AUDIO_EXTENSIONS:
            assert is_audio_file(f"song{ext}") is True

    def test_returns_false_for_unsupported_extensions(self):
        """Unsupported extensions return False."""
        assert is_audio_file("song.txt") is False
        assert is_audio_file("song.pdf") is False
        assert is_audio_file("song") is False

    def test_is_case_insensitive(self):
        """Extension check is case-insensitive."""
        assert is_audio_file("song.MP3") is True
        assert is_audio_file("song.FlAc") is True


# ---------------------------------------------------------------------------
# collect_audio_files
# ---------------------------------------------------------------------------


class TestCollectAudioFiles:
    """Tests for ``collect_audio_files``."""

    def test_collects_single_audio_file(self, tmp_path: Path):
        """Given a single audio file path, returns it in a list."""
        audio = tmp_path / "test.mp3"
        audio.touch()
        result = collect_audio_files(str(audio))
        assert result == [str(audio.resolve())]

    def test_skips_non_audio_file(self, tmp_path: Path):
        """Non-audio files are excluded from results."""
        txt = tmp_path / "notes.txt"
        txt.touch()
        result = collect_audio_files(str(txt))
        assert result == []

    def test_collects_audio_from_directory_recursively(self, tmp_path: Path):
        """Recursive scan finds audio files in nested directories."""
        sub = tmp_path / "sub"
        sub.mkdir()
        a = tmp_path / "a.mp3"
        b = sub / "b.flac"
        a.touch()
        b.touch()
        result = collect_audio_files(str(tmp_path), recursive=True)
        assert set(result) == {str(a.resolve()), str(b.resolve())}

    def test_collects_audio_from_directory_non_recursive(self, tmp_path: Path):
        """Non-recursive scan only finds audio in the immediate directory."""
        sub = tmp_path / "sub"
        sub.mkdir()
        a = tmp_path / "a.mp3"
        b = sub / "b.flac"
        a.touch()
        b.touch()
        result = collect_audio_files(str(tmp_path), recursive=False)
        assert result == [str(a.resolve())]

    def test_skips_nonexistent_paths(self, tmp_path: Path):
        """Non-existent paths are silently skipped."""
        result = collect_audio_files(str(tmp_path / "no_such_dir"))
        assert result == []

    def test_deduplicates_duplicate_paths(self, tmp_path: Path):
        """Duplicate paths are deduplicated and sorted."""
        a = tmp_path / "a.mp3"
        a.touch()
        result = collect_audio_files([str(a), str(a), str(tmp_path)])
        assert result == [str(a.resolve())]

    def test_accepts_list_of_paths(self, tmp_path: Path):
        """A list of mixed file and directory paths is handled correctly."""
        sub = tmp_path / "sub"
        sub.mkdir()
        a = tmp_path / "a.mp3"
        b = sub / "b.flac"
        c = sub / "notes.txt"
        a.touch()
        b.touch()
        c.touch()
        result = collect_audio_files([str(a), str(sub)])
        assert set(result) == {str(a.resolve()), str(b.resolve())}


# ---------------------------------------------------------------------------
# resolve_library_path
# ---------------------------------------------------------------------------


class TestResolveLibraryPath:
    """Tests for ``resolve_library_path`` — the core security validation function."""

    def test_resolves_valid_relative_path(self, tmp_path: Path):
        """A valid relative path within the library root is resolved correctly."""
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "song.mp3"
        f.touch()
        result = resolve_library_path(library_root=tmp_path, user_path="sub/song.mp3")
        assert result == f.resolve()

    def test_resolves_unicode_path(self, tmp_path: Path):
        """Unicode / kanji paths within the library root are resolved."""
        sub = tmp_path / "アーティスト"
        sub.mkdir()
        f = sub / "曲.mp3"
        f.touch()
        result = resolve_library_path(library_root=tmp_path, user_path="アーティスト/曲.mp3")
        assert result == f.resolve()

    def test_rejects_absolute_user_path(self, tmp_path: Path):
        """Absolute user paths are rejected."""
        with pytest.raises(ValueError, match="Access denied"):
            resolve_library_path(library_root=tmp_path, user_path="/etc/passwd")

    def test_rejects_parent_directory_traversal(self, tmp_path: Path):
        """Parent directory traversal ('..') is rejected."""
        sub = tmp_path / "sub"
        sub.mkdir()
        with pytest.raises(ValueError, match="Access denied"):
            resolve_library_path(library_root=sub, user_path="../outside")

    def test_rejects_double_dot_traversal(self, tmp_path: Path):
        """Paths containing '..' as a component are rejected."""
        sub = tmp_path / "sub"
        sub.mkdir()
        with pytest.raises(ValueError, match="Access denied"):
            resolve_library_path(library_root=sub, user_path="../../etc/passwd")

    def test_rejects_nul_byte_in_path(self, tmp_path: Path):
        """NUL bytes in user path are rejected."""
        with pytest.raises(ValueError, match="Access denied"):
            resolve_library_path(library_root=tmp_path, user_path="valid\x00hidden")

    def test_raises_when_library_root_is_empty(self):
        """Empty library root raises ValueError."""
        with pytest.raises(ValueError, match="Library root not configured"):
            resolve_library_path(library_root="", user_path="song.mp3")

    def test_raises_when_path_does_not_exist_and_must_exist_is_true(self, tmp_path: Path):
        """When must_exist=True, non-existent paths raise ValueError."""
        with pytest.raises(ValueError, match="Access denied"):
            resolve_library_path(library_root=tmp_path, user_path="nonexistent.mp3", must_exist=True)

    def test_allows_nonexistent_path_when_must_exist_is_false(self, tmp_path: Path):
        """When must_exist=False, non-existent paths are resolved without error."""
        result = resolve_library_path(library_root=tmp_path, user_path="nonexistent.mp3", must_exist=False)
        assert result == (tmp_path / "nonexistent.mp3").resolve()
        # Resolve with strict=False because the file does not exist
        tmp_path.resolve(strict=True)
        result.resolve(strict=False)  # will fail; let me reconsider

    def test_validates_file_type_when_must_be_file_true(self, tmp_path: Path):
        """When must_be_file=True, directories are rejected."""
        sub = tmp_path / "sub"
        sub.mkdir()
        with pytest.raises(ValueError, match="Access denied"):
            resolve_library_path(library_root=tmp_path, user_path="sub", must_be_file=True)

    def test_validates_directory_type_when_must_be_file_false(self, tmp_path: Path):
        """When must_be_file=False, files are rejected."""
        f = tmp_path / "song.mp3"
        f.touch()
        with pytest.raises(ValueError, match="Access denied"):
            resolve_library_path(library_root=tmp_path, user_path="song.mp3", must_be_file=False)

    def test_resolves_symlink_within_boundary(self, tmp_path: Path):
        """Symlinks that point within the library root are allowed."""
        sub = tmp_path / "sub"
        sub.mkdir()
        real_file = sub / "real.mp3"
        real_file.touch()
        link = tmp_path / "link.mp3"
        link.symlink_to(real_file)
        result = resolve_library_path(library_root=tmp_path, user_path="link.mp3")
        assert result == real_file.resolve()

    def test_rejects_symlink_outside_boundary(self, tmp_path: Path):
        """Symlinks that point outside the library root are rejected."""
        outside = tmp_path.parent / "outside.mp3"
        outside.touch()
        try:
            link = tmp_path / "escape.mp3"
            link.symlink_to(outside)
            with pytest.raises(ValueError, match="Access denied"):
                resolve_library_path(library_root=tmp_path, user_path="escape.mp3")
        finally:
            outside.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# validate_library_path
# ---------------------------------------------------------------------------


class TestValidateLibraryPath:
    """Tests for ``validate_library_path`` — thin wrapper around resolve_library_path."""

    def test_returns_resolved_path_string(self, tmp_path: Path):
        """Validates and returns the resolved path as a string."""
        f = tmp_path / "song.mp3"
        f.touch()
        result = validate_library_path(file_path="song.mp3", library_path=str(tmp_path))
        assert result == str(f.resolve())
        assert isinstance(result, str)

    def test_raises_value_error_for_invalid_path(self, tmp_path: Path):
        """Invalid paths raise ValueError with 'Access denied' message."""
        with pytest.raises(ValueError, match="Access denied"):
            validate_library_path(file_path="../outside", library_path=str(tmp_path))

    def test_requires_file_to_exist(self, tmp_path: Path):
        """Non-existent files raise ValueError."""
        with pytest.raises(ValueError, match="Access denied"):
            validate_library_path(file_path="missing.mp3", library_path=str(tmp_path))
