"""Canonical filesystem-access contract: the fact vocabulary and stdlib-only probe.

This module is the shared **fact** layer for filesystem access. It reports what the
operating system returned; it never decides what to do about it.

Contract properties (ADR-050, DD §8.1):

- **Fact-only.** The contract never chooses to retry, delete, or preserve anything —
  that policy stays operation-specific (DD R8). It contains no retry, remount, sleep,
  timeout, delete, or preserve logic.
- **No path validation.** It performs no containment, ``..``, or NUL validation; it
  consumes paths that are already resolved and validated upstream (ADR-037). Any
  validation stays upstream of this layer.
- **Server-side detail.** ``FsFact.detail`` is a short, server-side diagnostic. It must
  never cross the client boundary; client-facing messages are built by callers and stay
  generic.
- **Single absence producer.** ``presence="absent"`` and ``kind="resource_missing"`` are
  produced only by the corroboration component in a later part (same-pass enumeration
  witnessing). Nothing in this module ever returns either value: a bare ``ENOENT`` is
  ``unconfirmed_missing``, never ``absent``.

The module is a leaf: it imports the standard library only and never imports any other
``nomarr`` module.
"""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type Presence = Literal["present", "absent", "unknown"]

type FsErrorKind = Literal[
    "resource_missing",  # ENOENT, ONLY after same-pass enumeration corroboration
    "unconfirmed_missing",  # bare/uncorroborated ENOENT (and autofs-style ENOENT)
    "permission_denied",  # EACCES, EPERM
    "storage_unavailable",  # ESTALE, ENOTCONN, EHOSTDOWN, ENODEV, EREMOTEIO, ENXIO
    "transient_io",  # EIO, ETIMEDOUT, EAGAIN/EWOULDBLOCK, EINTR
    "storage_full",  # ENOSPC
    "read_only_fs",  # EROFS
    "invalid_path",  # EINVAL, ENAMETOOLONG, ELOOP
    "wrong_resource_type",  # ENOTDIR, EISDIR, EEXIST
    "unknown",  # any other errno, or errno is None
]


@dataclass(frozen=True, slots=True)
class FsFact:
    """A lossless statement about one filesystem observation.

    Attributes:
        presence: Tri-state presence. ``"absent"`` is only ever produced by the
            corroboration component; this module yields only ``"present"``/``"unknown"``.
        kind: The classified failure kind, or ``None`` exactly when present.
        errno: The raw errno from the underlying ``OSError``, or ``None``.
        detail: Short server-side diagnostic; never crosses the client boundary.

    """

    presence: Presence
    kind: FsErrorKind | None
    errno: int | None
    detail: str | None = None

    def __post_init__(self) -> None:
        """Enforce the four documented invariants with explicit ``ValueError``."""
        if (self.kind is None) != (self.presence == "present"):
            raise ValueError("kind is None if and only if presence is 'present'")
        if (self.kind == "resource_missing") != (self.presence == "absent"):
            raise ValueError("kind 'resource_missing' if and only if presence is 'absent'")
        if self.presence == "unknown" and self.kind is None:
            raise ValueError("presence 'unknown' requires a non-None kind")
        if self.presence == "unknown" and self.kind == "resource_missing":
            raise ValueError("presence 'unknown' cannot carry kind 'resource_missing'")


# errno -> kind. Deliberately contains NO "resource_missing" entry: absence is never
# authorized by an errno alone (only by enumeration corroboration in a later part).
_ERRNO_KIND: dict[int, FsErrorKind] = {
    errno.ENOENT: "unconfirmed_missing",
    errno.EACCES: "permission_denied",
    errno.EPERM: "permission_denied",
    errno.ENOTDIR: "wrong_resource_type",
    errno.EISDIR: "wrong_resource_type",
    errno.EEXIST: "wrong_resource_type",
    errno.EINVAL: "invalid_path",
    errno.ENAMETOOLONG: "invalid_path",
    errno.ELOOP: "invalid_path",
    errno.ESTALE: "storage_unavailable",
    errno.ENOTCONN: "storage_unavailable",
    errno.EHOSTDOWN: "storage_unavailable",
    errno.ENODEV: "storage_unavailable",
    errno.EREMOTEIO: "storage_unavailable",
    errno.ENXIO: "storage_unavailable",
    errno.EIO: "transient_io",
    errno.ETIMEDOUT: "transient_io",
    # EAGAIN and EWOULDBLOCK share a value on Linux; both are kept for documentation.
    errno.EAGAIN: "transient_io",
    errno.EWOULDBLOCK: "transient_io",
    errno.EINTR: "transient_io",
    errno.ENOSPC: "storage_full",
    errno.EROFS: "read_only_fs",
}


def classify_os_error(exc: OSError) -> FsErrorKind:
    """Classify an ``OSError`` from its ``errno`` alone, never from its subclass."""
    if exc.errno is None:
        return "unknown"
    return _ERRNO_KIND.get(exc.errno, "unknown")


def fact_from_error(exc: OSError, *, path: str | os.PathLike[str]) -> FsFact:
    """Build an ``unknown`` fact from a failed filesystem operation.

    The result is always ``presence="unknown"`` — this function never authorizes
    absence. ``detail`` is a short server-side diagnostic.
    """
    return FsFact(
        presence="unknown",
        kind=classify_os_error(exc),
        errno=exc.errno,
        detail=f"{os.fspath(path)}: {exc.strerror or exc}",
    )


def probe_fact(path: str | os.PathLike[str]) -> FsFact:
    """Probe ``path`` with exactly one ``os.stat`` and report the fact.

    Success yields the canonical ``present`` fact; an ``OSError`` is classified via
    :func:`fact_from_error`. This function **never** returns ``absent``. Any
    non-``OSError`` exception propagates unchanged.
    """
    try:
        os.stat(path)
    except OSError as exc:
        return fact_from_error(exc, path=path)
    return FsFact(presence="present", kind=None, errno=None)


def canonicalize(path: str | os.PathLike[str], *, strict: bool) -> Path:
    """Return ``Path(path).resolve(strict=strict)`` with failures normalised to ``OSError``.

    ``Path.resolve()`` can raise ``RuntimeError`` for a symlink loop; that failure mode is
    normalised to ``OSError(errno.ELOOP, ...)`` chained from the original, so callers can
    classify every failure with :func:`fact_from_error`. This stdlib-only module raises no
    ``nomarr``-typed error.
    """
    try:
        return Path(path).resolve(strict=strict)
    except RuntimeError as exc:
        raise OSError(errno.ELOOP, str(exc)) from exc
