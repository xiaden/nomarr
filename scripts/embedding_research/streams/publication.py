"""Durable immutable file publication for frozen stream artifacts (Plan B Phase 2).

This module owns the *filesystem durability* half of the A' publication contract.
It is deliberately separated from the registry so the always-on write-proxy seam
(the thing the lifecycle tests assert against) is structural rather than a
monkeypatch on a specific call site.

The durable-create sequence for one artifact, exactly as the DD and the shared
ledger pin it, is::

    fsync(file) -> close(file) -> atomic rename -> fsync(destination directory)

This is a Linux/POSIX assumption and is documented here rather than treated as a
portability promise.  All ``fsync`` / ``close`` / ``rename`` syscalls route through
a small :class:`FileOps` proxy whose default (production) implementation calls the
real ``os`` functions; a :class:`RecordingFileOps` subclass captures the exact call
sequence for the lifecycle tests without monkeypatching.

Post-migration artifact grammar (the ONLY payload grammar after the corrective
pass, DD § filesystem layout / immutable artifact contracts)::

    <song_id>.<backbone>.<lowercase-64-hex-payload-sha256><suffix>

where ``song_id`` is a single dot-free token, ``backbone`` matches
``[A-Za-z0-9_-]+`` and the final component is exactly 64 lowercase hexadecimal
digits.  The suffix is ``.npy`` for streams/masks and ``.npz`` for heads.  Each
payload is accompanied by a self-describing ``.json`` manifest at the same digest
name.  There is NO bare, ``.vN``, archival, CTP or pre-corrective name branch.

A payload and its manifest are immutable once published: bytes are never replaced
at an existing digest (re-publishing identical bytes reuses the existing artifact;
different bytes produce a different digest name and therefore a different file).
"""

from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

#: Staging directory name (a file-level concern, never a registry state).
STAGING_DIRNAME = ".staging"

#: Exact post-migration digest grammar: ``{song_id}.{backbone}.{64-hex}{suffix}``.
_DIGEST_NAME_RE = re.compile(r"^(?P<song_id>[^.]+)\.(?P<backbone>[A-Za-z0-9_-]+)\.(?P<digest>[0-9a-f]{64})$")

#: Backbone grammar (no dot, alphanumeric plus ``-``/``_``).
_BACKBONE_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: Lowercase 64-hex sha256 digest grammar.
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

#: ``os.open`` flag for the destination-directory fsync handle (read-only is enough
#: to obtain an fd whose ``fsync`` flushes directory entries on Linux/POSIX).
_DIR_FSYNC_FLAGS = os.O_RDONLY


@dataclass(frozen=True)
class ArtifactIdentity:
    """The typed logical identity decoded from a digest-grammar artifact name.

    Post-migration there is exactly one grammar family (``digest``); there is no
    bare/``.vN``/archival variant.  ``song_id``/``backbone`` are the logical
    identity, ``digest`` is the lowercase-64-hex payload sha256 and ``suffix`` is
    the matched filename suffix (``.npy``/``.npz``/``.json``).
    """

    song_id: str
    backbone: str
    digest: str
    suffix: str
    family: str = "digest"


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
    order the syscalls actually happen.  This is the seam the lifecycle tests assert
    against.
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
        ``fsync(file) -> close(file) -> rename -> fsync(directory)`` per file write.
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


def _sha256_hex_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _file_sha256_hex(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    ids — the documented layout contract for the ``infer-heads`` writer and the
    ``HeadStreamStore`` reader.  Head ids are passed as ``np.savez`` keyword names.
    Payload format changes require a new ``format_version``.
    """
    buffer = io.BytesIO()
    np.savez(buffer, **{name: np.ascontiguousarray(arr, dtype=np.float32) for name, arr in arrays.items()})
    return buffer.getvalue()


def durable_write(tmp_path: Path, final_path: Path, payload: bytes, ops: FileOps) -> None:
    """Persist *payload* at *final_path* following the exact durable-create sequence.

    Order (Linux/POSIX assumption, documented): write the complete bytes to *tmp_path*,
    ``fsync`` the open file, close it, atomically ``rename`` into *final_path*, then
    ``fsync`` the destination directory.  All four syscalls route through *ops* so a
    recording proxy can assert the order.  The destination directory must already exist
    (the caller creates the staging and final parents).  On failure before the rename,
    *tmp_path* may be left behind; it is a reportable/removable file-level condition,
    never a registry state.
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


def durable_write_if_absent(final_path: Path, payload: bytes, ops: FileOps) -> bool:
    """Content-addressed durable write that NEVER replaces bytes at an existing digest.

    Because the filename encodes the payload sha256, an existing file at *final_path*
    must already contain exactly *payload*; if so we reuse it (idempotent re-publish of
    identical bytes) and return ``False`` (nothing written).  If a file exists whose
    bytes do not match its digest name we raise — that is an irreconcilable corruption
    and must not be overwritten.  Otherwise the file is written through the staged
    durable sequence and ``True`` is returned.
    """
    if final_path.is_file():
        if _file_sha256_hex(final_path) != _sha256_hex_bytes(payload):
            raise OSError(
                f"refusing to replace bytes at existing digest path {final_path}: "
                "on-disk content does not match the digest-encoded sha256"
            )
        return False
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = staging_path_for(final_path)
    durable_write(tmp_path, final_path, payload, ops)
    return True


def staging_path_for(final_path: Path) -> Path:
    """The ``.staging/<final-name>.tmp`` path for a final artifact at *final_path*.

    The staging directory is created (and must exist) as a sibling ``.staging`` of the
    final artifact's parent.  A digest-named final produces a digest-named ``.tmp``.
    """
    staging_dir = final_path.parent / STAGING_DIRNAME
    staging_dir.mkdir(parents=True, exist_ok=True)
    return staging_dir / f"{final_path.name}.tmp"


# ── JSON self-describing manifests ─────────────────────────────────────────────


def write_json_durable(final_path: Path, data: Mapping[str, object], ops: FileOps) -> bool:
    """Durably write a JSON document at *final_path* (never replacing existing bytes).

    Serialization is deterministic (sorted keys, compact separators) so identical
    logical documents produce identical bytes.  Returns ``True`` when written, ``False``
    when an identical document already exists (immutable no-replace reuse).
    """
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return durable_write_if_absent(final_path, payload, ops)


def read_json_manifest(path: Path) -> dict[str, object]:
    """Read and parse a JSON manifest, raising ``ValueError`` on malformed JSON."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced by callers as missing/corrupt
        raise ValueError(f"manifest unreadable: {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"manifest must be a JSON object: {path}")
    return data


# ── digest artifact naming ─────────────────────────────────────────────────────


def digest_artifact_name(song_id: str, backbone: str, digest: str, suffix: str) -> str:
    """Return the exact digest-grammar filename ``{sid}.{bb}.{64hex}{suffix}``.

    Validates the logical identity (song_id is a dot-free token, backbone matches the
    grammar) and that *digest* is exactly 64 lowercase hexadecimal digits.
    """
    if not song_id or "." in song_id:
        raise ValueError(f"song_id must be a dot-free token; got {song_id!r}")
    if not _BACKBONE_RE.match(backbone):
        raise ValueError(f"backbone must match {_BACKBONE_RE.pattern}; got {backbone!r}")
    if not _DIGEST_RE.match(digest):
        raise ValueError(f"digest must be 64 lowercase hex digits; got {digest!r}")
    if not suffix.startswith(".") or not suffix[1:] or "." in suffix[1:]:
        raise ValueError(f"suffix must be a single dotted extension; got {suffix!r}")
    return f"{song_id}.{backbone}.{digest}{suffix}"


def parse_artifact_name(name: str, suffix: str) -> ArtifactIdentity | None:
    """Map a digest-grammar artifact filename back to its typed logical identity.

    Returns an :class:`ArtifactIdentity` or ``None`` when *name* is not a recognizable
    post-migration digest artifact for *suffix*.  There is deliberately NO branch for
    bare, ``.vN``, archival, CTP or pre-corrective names (Git is the source archive and
    old outputs are never interpreted at runtime).
    """
    if not name.endswith(suffix):
        return None
    stem = name[: -len(suffix)]
    match = _DIGEST_NAME_RE.match(stem)
    if match is None:
        return None
    return ArtifactIdentity(
        song_id=match.group("song_id"),
        backbone=match.group("backbone"),
        digest=match.group("digest"),
        suffix=suffix,
    )
