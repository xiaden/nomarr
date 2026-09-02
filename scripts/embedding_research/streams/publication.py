"""Durable immutable file publication for frozen stream artifacts (Plan B Phase 2).

This module owns the *filesystem durability* half of the A' publication contract.
It is deliberately separated from the registry so the always-on write-proxy seam
(the thing the Phase 4 lifecycle tests assert against) is structural rather than a
monkeypatch on a specific call site.

The durable-create sequence for one artifact, exactly as the DD and the shared
ledger pin it, is::

    fsync(file) -> close(file) -> atomic rename -> fsync(destination directory)

This is a Linux/POSIX assumption and is documented here rather than treated as a
portability promise.  All ``fsync`` / ``close`` / ``rename`` syscalls route through
a small :class:`FileOps` proxy whose default (production) implementation calls the
real ``os`` functions; a :class:`RecordingFileOps` subclass captures the exact call
sequence for the lifecycle tests without monkeypatching.

The file is written to a ``.staging`` sibling directory as ``<name>.<suffix>.tmp``,
flushed/fsync'd, atomically renamed into its final location, then the destination
directory is fsync'd — all before any registry row is touched.  A leftover ``.tmp``
in ``.staging`` is a *file-level* condition (reportable/removable), never a registry
state.

Artifact filename parsing lives here too because the immutable-supersession design
(publish a NEW versioned artifact rather than overwrite old bytes) requires a
deterministic mapping between on-disk filenames and the logical
``(song_id, backbone)`` identity they encode.  The identity prefix is always kept
in the filename so a filesystem scan can map a rowless file back to its logical
identity.
"""

from __future__ import annotations

import io
import os
import re
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

#: Staging directory name (a file-level concern, never a registry state).
STAGING_DIRNAME = ".staging"

#: Regex separating the trailing version of a superseded artifact name
#: (``{sid}.{backbone}.v2.npy`` -> backbone ``{backbone}``, version ``2``).
_VERSION_RE = re.compile(r"^(.*)\.v(\d+)$")

#: ``os.open`` flag for the destination-directory fsync handle (read-only is enough
#: to obtain an fd whose ``fsync`` flushes directory entries on Linux/POSIX).
_DIR_FSYNC_FLAGS = os.O_RDONLY


# ── always-on write-proxy seam ─────────────────────────────────────────────────


class FileOps:
    """Routes the fsync/close/rename syscalls of a durable write.

    The production default simply calls the real ``os`` functions.  The methods are
    separated by *kind* (``fsync_file`` vs ``fsync_dir``, ``close_fd``) so a recorder
    can label each event structurally instead of inferring it from a path.
    """

    def fsync_file(self, fd: int) -> None:
        """``os.fsync`` on a regular-file descriptor (the staged payload)."""
        os.fsync(fd)

    def fsync_dir(self, fd: int) -> None:
        """``os.fsync`` on a directory descriptor (the destination directory)."""
        os.fsync(fd)

    def close_fd(self, fd: int) -> None:
        """``os.close`` of a descriptor opened for a durable write."""
        os.close(fd)

    def rename(self, src: str, dst: str) -> None:
        """Atomic rename into the final location (``os.replace``)."""
        os.replace(src, dst)


class RecordingFileOps(FileOps):
    """A :class:`FileOps` that records each durable-write syscall in order.

    ``events`` is an ordered list of ``(operation, detail)`` tuples where
    ``operation`` is one of ``"fsync"``/``"close"``/``"rename"`` and ``detail`` is a
    label (``"file"``/``"dir"``) or the ``(src, dst)`` pair for ``rename``.  Recording
    is done before delegating to the real implementation, so the recorded order is the
    order the syscalls actually happen.  This is the seam Phase 4 lifecycle tests
    assert against.
    """

    def __init__(self, inner: FileOps | None = None) -> None:
        self.events: list[tuple[str, object]] = []
        self._inner = inner if inner is not None else FileOps()

    # -- recording helpers ------------------------------------------------------
    def _record(self, operation: str, detail: object) -> None:
        self.events.append((operation, detail))

    def fsync_file(self, fd: int) -> None:
        self._record("fsync", "file")
        self._inner.fsync_file(fd)

    def fsync_dir(self, fd: int) -> None:
        self._record("fsync", "dir")
        self._inner.fsync_dir(fd)

    def close_fd(self, fd: int) -> None:
        self._record("close", "file")
        self._inner.close_fd(fd)

    def rename(self, src: str, dst: str) -> None:
        self._record("rename", (src, dst))
        self._inner.rename(src, dst)

    @property
    def order(self) -> list[tuple[str, str]]:
        """The expected durable-write ordering as ``[(op, kind), ...]`` for assertions.

        Only the fsync/close/rename sequence is surfaced (the DD lifecycle order):
        ``fsync(file) -> close(file) -> rename -> fsync(directory)``.
        """
        result: list[tuple[str, str]] = []
        for operation, detail in self.events:
            if operation == "fsync":
                result.append(("fsync", str(detail)))
            elif operation == "close":
                result.append(("close", str(detail)))
            elif operation == "rename":
                result.append(("rename", "file"))
        return result


# ── durable byte write ─────────────────────────────────────────────────────────


def _write_fd_all(fd: int, payload: bytes) -> None:
    """Write *payload* fully to *fd* (a plain, non-recording raw write)."""
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def npy_bytes(arr: np.ndarray) -> bytes:
    """Serialize a float32 C-order array to the exact ``.npy`` payload bytes.

    ``np.save`` to an in-memory buffer yields the canonical header + raw data byte
    stream that ``np.load(..., allow_pickle=False)`` round-trips.  This is the only v1
    payload codec (float32 ``.npy`` + ``format_version``); format changes require a
    new version.
    """
    buffer = io.BytesIO()
    np.save(buffer, np.ascontiguousarray(arr, dtype=np.float32))
    return buffer.getvalue()


def npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Serialize a per-head float32 array suite to the exact ``.npz`` payload bytes.

    The head-suite codec (Plan B Phase 3): one float32 ``[T, dim]`` array per head id
    key, zipped with ``np.savez`` (``ZIP_STORED``).  ``np.load(..., allow_pickle=False)``
    on the bytes round-trips an :class:`np.NpzFile` whose ``keys()`` are exactly the head
    ids — the Phase-1 documented layout contract for the ``infer-heads`` writer and the
    ``HeadStreamStore`` reader.  The durable-write fsync/rename ordering applies to the
    ``.npz`` file bytes exactly as it does to a bare ``.npy`` payload.

    Head ids are the config stem-derived classifier names (``_discover_heads`` returns
    ``stem.split(\"-\")[0]``), which are Python identifiers, so they are passed as
    ``np.savez`` keyword names (the canonical npz writer this package already uses in
    tests).  Payload format changes require a new ``format_version``.
    """
    buffer = io.BytesIO()
    np.savez(buffer, **{name: np.ascontiguousarray(arr, dtype=np.float32) for name, arr in arrays.items()})
    return buffer.getvalue()


def durable_write(tmp_path: Path, final_path: Path, payload: bytes, ops: FileOps) -> None:
    """Persist *payload* at *final_path* following the exact durable-create sequence.

    Order (Linux/POSIX assumption, documented — a SIGKILL test is not treated as proof
    of power-loss durability): write the complete bytes to *tmp_path*, ``fsync`` the
    open file, close it, atomically ``rename`` into *final_path*, then ``fsync`` the
    destination directory.  All four syscalls route through *ops* so a recording proxy
    can assert the order.

    The destination directory must already exist (the caller creates the staging and
    final parents).  On failure before the rename, *tmp_path* may be left behind; it is
    a reportable/removable file-level condition, never a registry state.
    """
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        _write_fd_all(fd, payload)
        ops.fsync_file(fd)
    finally:
        ops.close_fd(fd)
    # Atomic rename into the final location, then fsync the destination directory.
    ops.rename(str(tmp_path), str(final_path))
    dir_fd = os.open(str(final_path.parent), _DIR_FSYNC_FLAGS)
    try:
        ops.fsync_dir(dir_fd)
    finally:
        os.close(dir_fd)


def staging_path_for(final_path: Path) -> Path:
    """The ``.staging/<final-name>.tmp`` path for a final artifact at *final_path*.

    The staging directory is created (and must exist) as a sibling ``.staging`` of the
    final artifact's parent, mirroring the DD layout ``patches/.staging/{name}.npy.tmp``.
    """
    staging_dir = final_path.parent / STAGING_DIRNAME
    staging_dir.mkdir(parents=True, exist_ok=True)
    return staging_dir / f"{final_path.name}.tmp"


# ── artifact filename parsing (immutable supersession identity) ───────────────


def parse_artifact_name(name: str, suffix: str) -> tuple[str, str, int | None] | None:
    """Map an on-disk artifact filename back to its logical identity.

    Returns ``(song_id, backbone, version)`` or ``None`` when the name is not a
    recognizable frozen-stream artifact.  The identity prefix ``{song_id}.{backbone}``
    is preserved in every artifact filename (canonical bare name for the first-ever
    artifact, a versioned ``{song_id}.{backbone}.v{N}`` suffix for every artifact
    published when prior bytes exist at that identity), so a reconcile filesystem scan
    can map a rowless file back to its logical identity and distinguish a SUPERSEDED
    old artifact from a genuine stray ORPHAN or a LEGACY pre-registry file.

    ``song_id`` is the first dot-free segment (project ``song_id`` is a 12-char hex
    digest and therefore never contains ``.``), so parsing is deterministic.
    ``version`` is ``None`` for the canonical bare name and the integer version for a
    superseded/versioned artifact.
    """
    if not name.endswith(suffix):
        return None
    stem = name[: -len(suffix)]
    if "." not in stem:
        return None
    song_id, rest = stem.split(".", 1)
    if not song_id or not rest:
        return None
    match = _VERSION_RE.match(rest)
    if match is not None:
        backbone, version = match.group(1), int(match.group(2))
        if not backbone:
            return None
        return song_id, backbone, version
    return song_id, rest, None
