"""Unit tests for the canonical filesystem-access contract (Part A).

Spec-first RED tests written against the final Part A contract (DD §8.1, ADR-050)
*before* the production module exists. Every assertion pins the contract and is
deliberately not weakened to make a later implementation phase easier.
"""

from __future__ import annotations

import errno
import os
import typing
from pathlib import Path

import pytest

from nomarr.helpers.exceptions import FilesystemError
from nomarr.helpers.fs_contract import (
    FsErrorKind,
    FsFact,
    Presence,
    canonicalize,
    classify_os_error,
    fact_from_error,
    probe_fact,
)

pytestmark = [pytest.mark.unit]


class _EaccesOSError(OSError):
    """Locally declared OSError subclass proving classification is errno-only."""


# Every pair from the DD §8.1 errno → kind map (EAGAIN/EWOULDBLOCK alias on Linux).
_ERRNO_KIND_CASES: list[tuple[int, str]] = [
    (errno.ENOENT, "unconfirmed_missing"),
    (errno.EACCES, "permission_denied"),
    (errno.EPERM, "permission_denied"),
    (errno.ENOTDIR, "wrong_resource_type"),
    (errno.EISDIR, "wrong_resource_type"),
    (errno.EEXIST, "wrong_resource_type"),
    (errno.EINVAL, "invalid_path"),
    (errno.ENAMETOOLONG, "invalid_path"),
    (errno.ELOOP, "invalid_path"),
    (errno.ESTALE, "storage_unavailable"),
    (errno.ENOTCONN, "storage_unavailable"),
    (errno.EHOSTDOWN, "storage_unavailable"),
    (errno.ENODEV, "storage_unavailable"),
    (errno.EREMOTEIO, "storage_unavailable"),
    (errno.ENXIO, "storage_unavailable"),
    (errno.EIO, "transient_io"),
    (errno.ETIMEDOUT, "transient_io"),
    (errno.EAGAIN, "transient_io"),
    (errno.EWOULDBLOCK, "transient_io"),
    (errno.EINTR, "transient_io"),
    (errno.ENOSPC, "storage_full"),
    (errno.EROFS, "read_only_fs"),
]

_MAPPED_ERRNOS: list[int] = sorted({errno_value for errno_value, _ in _ERRNO_KIND_CASES})

_PRESENCE_VALUES: list[Presence] = ["present", "absent", "unknown"]

_KIND_VALUES: list[FsErrorKind | None] = [
    "resource_missing",
    "unconfirmed_missing",
    "permission_denied",
    "storage_unavailable",
    "transient_io",
    "storage_full",
    "read_only_fs",
    "invalid_path",
    "wrong_resource_type",
    "unknown",
    None,
]

# The full 3 presence x 11 kind (10 kinds + None) = 33-cell invariant matrix.
_ALL_CELLS: list[tuple[Presence, FsErrorKind | None]] = [
    (presence, kind) for presence in _PRESENCE_VALUES for kind in _KIND_VALUES
]

# Valid: ("present", None); ("absent", "resource_missing"); ("unknown", k) for the
# 9 kinds other than "resource_missing". Everything else is an invariant violation.
_VALID_CELLS: list[tuple[Presence, FsErrorKind | None]] = [
    ("present", None),
    ("absent", "resource_missing"),
    *[("unknown", kind) for kind in _KIND_VALUES if kind is not None and kind != "resource_missing"],
]

_INVALID_CELLS: list[tuple[Presence, FsErrorKind | None]] = [cell for cell in _ALL_CELLS if cell not in _VALID_CELLS]


class TestFsErrorKindTaxonomy:
    """The errno → FsErrorKind taxonomy is exact and errno-keyed only."""

    @pytest.mark.parametrize(("errno_value", "expected_kind"), _ERRNO_KIND_CASES)
    def test_errno_maps_to_expected_kind(self, errno_value: int, expected_kind: str) -> None:
        """Each documented errno classifies to its documented kind."""
        assert classify_os_error(OSError(errno_value, "x")) == expected_kind

    def test_errno_none_is_unknown(self) -> None:
        """An OSError with no errno is unknown."""
        assert classify_os_error(OSError()) == "unknown"

    def test_unmapped_errno_is_unknown(self) -> None:
        """Any errno outside the map is unknown."""
        assert classify_os_error(OSError(9999, "x")) == "unknown"

    def test_classifies_by_errno_not_isinstance(self) -> None:
        """Classification branches on exc.errno, never on the exception subclass."""
        assert classify_os_error(FileNotFoundError(errno.EIO, "x")) == "transient_io"
        assert classify_os_error(TimeoutError(errno.ETIMEDOUT, "x")) == "transient_io"
        assert classify_os_error(_EaccesOSError(errno.EACCES, "x")) == "permission_denied"

    def test_never_returns_resource_missing(self) -> None:
        """No errno in the mapped set can ever classify as resource_missing."""
        for errno_value in _MAPPED_ERRNOS:
            assert classify_os_error(OSError(errno_value, "x")) != "resource_missing"

    def test_taxonomy_has_exactly_ten_kinds(self) -> None:
        """FsErrorKind is exactly the 10 documented kind strings."""
        expected = {
            "resource_missing",
            "unconfirmed_missing",
            "permission_denied",
            "storage_unavailable",
            "transient_io",
            "storage_full",
            "read_only_fs",
            "invalid_path",
            "wrong_resource_type",
            "unknown",
        }
        assert set(typing.get_args(getattr(FsErrorKind, "__value__", FsErrorKind))) == expected


class TestFsFactInvariants:
    """FsFact.__post_init__ enforces the four documented invariants."""

    @pytest.mark.parametrize(("presence", "kind"), _VALID_CELLS)
    def test_valid_combinations_construct(self, presence: Presence, kind: FsErrorKind | None) -> None:
        """Every valid (presence, kind) cell constructs and round-trips."""
        fact = FsFact(presence=presence, kind=kind, errno=None)
        assert fact.presence == presence
        assert fact.kind == kind

    @pytest.mark.parametrize(("presence", "kind"), _INVALID_CELLS)
    def test_invalid_combinations_raise_value_error(self, presence: Presence, kind: FsErrorKind | None) -> None:
        """Every invalid (presence, kind) cell raises ValueError."""
        with pytest.raises(ValueError):
            FsFact(presence=presence, kind=kind, errno=None)

    def test_invariant_violations_are_value_error_not_assertion_error(self) -> None:
        """Invariant enforcement is an explicit ValueError, never a bare assert."""
        with pytest.raises(ValueError) as exc_info:
            FsFact(presence="present", kind="permission_denied", errno=None)
        assert type(exc_info.value) is ValueError
        assert not isinstance(exc_info.value, AssertionError)


class TestProbeFact:
    """probe_fact performs exactly one stat and never reports absence."""

    def test_real_file_is_present(self, tmp_path: Path) -> None:
        """A real file yields the canonical present fact."""
        target = tmp_path / "song.mp3"
        target.touch()
        assert probe_fact(target) == FsFact(presence="present", kind=None, errno=None, detail=None)

    @pytest.mark.parametrize(("errno_value", "expected_kind"), _ERRNO_KIND_CASES)
    def test_mapped_oserror_is_unknown_with_kind(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, errno_value: int, expected_kind: str
    ) -> None:
        """A stat OSError yields unknown with the classified kind and preserved errno."""

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError(errno_value, os.strerror(errno_value))

        monkeypatch.setattr("nomarr.helpers.fs_contract.os.stat", _raise)
        fact = probe_fact(tmp_path / "anything")
        assert fact.presence == "unknown"
        assert fact.kind == expected_kind
        assert fact.errno == errno_value
        assert fact.presence != "absent"

    def test_oserror_without_errno_is_unknown(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A stat OSError with errno None yields unknown with errno preserved as None."""

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError()

        monkeypatch.setattr("nomarr.helpers.fs_contract.os.stat", _raise)
        fact = probe_fact(tmp_path / "anything")
        assert fact.presence == "unknown"
        assert fact.kind == "unknown"
        assert fact.errno is None
        assert fact.presence != "absent"


class TestAbsenceCorroborationRule:
    """Neither probe_fact nor fact_from_error may ever authorize absence."""

    def test_fact_from_bare_enoent_is_unconfirmed_missing(self) -> None:
        """A bare ENOENT classifies as unconfirmed_missing, not resource_missing."""
        fact = fact_from_error(OSError(errno.ENOENT, os.strerror(errno.ENOENT)), path="/gone")
        assert fact.presence == "unknown"
        assert fact.kind == "unconfirmed_missing"
        assert fact.presence != "absent"
        assert fact.kind != "resource_missing"

    def test_probe_fact_on_missing_path_is_unconfirmed_missing(self, tmp_path: Path) -> None:
        """A genuinely missing path is unknown/unconfirmed_missing, never absent."""
        fact = probe_fact(tmp_path / "definitely-missing")
        assert fact.presence == "unknown"
        assert fact.kind == "unconfirmed_missing"
        assert fact.presence != "absent"
        assert fact.kind != "resource_missing"

    @pytest.mark.parametrize("errno_value", _MAPPED_ERRNOS)
    def test_never_returns_absent_for_any_mapped_errno(self, monkeypatch: pytest.MonkeyPatch, errno_value: int) -> None:
        """Sweep every mapped errno: neither producer ever yields absent/resource_missing."""

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError(errno_value, os.strerror(errno_value))

        monkeypatch.setattr("nomarr.helpers.fs_contract.os.stat", _raise)
        probed = probe_fact("/whatever")
        assert probed.presence != "absent"
        assert probed.kind != "resource_missing"

        derived = fact_from_error(OSError(errno_value, os.strerror(errno_value)), path="/whatever")
        assert derived.presence != "absent"
        assert derived.kind != "resource_missing"


class TestStdlibPathAsymmetry:
    """CPython ≥3.12: os.path.isfile swallows OSError, Path.exists re-raises."""

    def test_os_path_isfile_swallows_but_path_exists_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ESTALE: isfile() is False while Path.exists() raises the same OSError."""
        with monkeypatch.context() as patched:

            def _raise(*_args: object, **_kwargs: object) -> None:
                raise OSError(errno.ESTALE, os.strerror(errno.ESTALE))

            patched.setattr("os.stat", _raise)
            assert os.path.isfile("/whatever") is False
            with pytest.raises(OSError) as exc_info:
                Path("/whatever").exists()
            assert exc_info.value.errno == errno.ESTALE


class TestCanonicalize:
    """canonicalize returns resolved paths and normalises failure modes to OSError."""

    def test_real_directory_returns_absolute_resolved_path(self, tmp_path: Path) -> None:
        """A real directory resolves to an absolute Path."""
        result = canonicalize(tmp_path, strict=True)
        assert isinstance(result, Path)
        assert result.is_absolute()
        assert result == tmp_path.resolve()

    def test_symlink_loop_raises_eloop(self, tmp_path: Path) -> None:
        """A real symlink loop surfaces as OSError(ELOOP)/invalid_path."""
        a = tmp_path / "a"
        b = tmp_path / "b"
        os.symlink(b, a)
        os.symlink(a, b)
        with pytest.raises(OSError) as exc_info:
            canonicalize(a, strict=True)
        assert exc_info.value.errno == errno.ELOOP
        fact = fact_from_error(exc_info.value, path=a)
        assert fact.presence == "unknown"
        assert fact.kind == "invalid_path"

    def test_missing_path_strict_raises_enoent(self, tmp_path: Path) -> None:
        """strict=True on a missing path raises ENOENT, classifiable as unconfirmed_missing."""
        missing = tmp_path / "missing"
        with pytest.raises(OSError) as exc_info:
            canonicalize(missing, strict=True)
        assert exc_info.value.errno == errno.ENOENT
        fact = fact_from_error(exc_info.value, path=missing)
        assert fact.presence == "unknown"
        assert fact.kind == "unconfirmed_missing"

    def test_missing_path_non_strict_does_not_raise(self, tmp_path: Path) -> None:
        """strict=False on a missing path returns a Path without raising."""
        result = canonicalize(tmp_path / "missing", strict=False)
        assert isinstance(result, Path)


class TestFilesystemError:
    """FilesystemError is a ValueError carrying the structured fact."""

    def test_is_value_error_subclass(self) -> None:
        """Subclassing ValueError keeps existing except ValueError sites working."""
        assert issubclass(FilesystemError, ValueError)

    def test_carries_fact_and_derived_errno_strerror(self) -> None:
        """Construction stores the fact identity and derives errno/strerror."""
        fact = FsFact(presence="unknown", kind="permission_denied", errno=errno.EACCES)
        exc = FilesystemError("Access denied", fact=fact)
        assert exc.fact is fact
        assert exc.errno == errno.EACCES
        assert exc.strerror == os.strerror(errno.EACCES)

    def test_errno_and_strerror_none_when_fact_errno_none(self) -> None:
        """A fact with errno None yields errno/strerror None."""
        fact = FsFact(presence="present", kind=None, errno=None)
        exc = FilesystemError("Access denied", fact=fact)
        assert exc.errno is None
        assert exc.strerror is None

    def test_str_is_generic_and_leaks_neither_path_nor_strerror(self) -> None:
        """The client-safe message equals the supplied string and leaks no detail."""
        fact = FsFact(
            presence="unknown",
            kind="permission_denied",
            errno=errno.EACCES,
            detail="/library/secret/song.mp3: Permission denied",
        )
        exc = FilesystemError("Access denied", fact=fact)
        assert str(exc) == "Access denied"
        assert "/library/secret/song.mp3" not in str(exc)
        assert os.strerror(errno.EACCES) not in str(exc)

    def test_from_exc_chaining_preserves_cause(self) -> None:
        """Raising `from exc` keeps the original OSError as __cause__."""
        fact = FsFact(presence="unknown", kind="permission_denied", errno=errno.EACCES)
        original: OSError | None = None
        with pytest.raises(FilesystemError) as exc_info:
            try:
                raise OSError(errno.EACCES, os.strerror(errno.EACCES))
            except OSError as exc:
                original = exc
                raise FilesystemError("Access denied", fact=fact) from exc
        assert original is not None
        assert exc_info.value.__cause__ is original
