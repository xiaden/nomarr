"""Immutable stream / head-stream value objects and registry contracts (Plan B Phase 1).

This module is intentionally PURE: it has no DuckDB, numpy, audio, or filesystem
side effects, so any layer (store, catalog, tests) can import it without a
backend.  It is the single source of the record *field vocabulary* that every
later phase (C-F) consumes - the same names/types the shared planning ledger and
the DD ``stream_registry`` / ``head_stream_registry`` schemas define.

Two immutable value objects live here:

* :class:`StreamRecord` — logical identity ``(song_id, backbone)`` + validated
  scalar metadata + an opaque root-relative ``artifact_ref`` for one frozen
  per-song float32 patch stream.
* :class:`HeadStreamRecord` — the analogous complete, patch-aligned per-song
  head-activation stream (canonical head IDs/dimensions, alignment provenance).

plus the digest-only Plan B Phase 2 record types :class:`MaskRecord` (the patch-aligned
silence mask metadata), :class:`ObservationCommit` (the LAST-published observation-group
marker), and :class:`ReindexReport` (the filesystem-authoritative reindex result), along
with :class:`ReconcileReport` (the reconcile result type) and the small :mod:`streams`
exception hierarchy.  Validation here is deliberately
scope-limited to the *constrained* fields the ledger/DD pin (``dtype`` must be
``float32``, ``status`` must be in the lifecycle vocabulary, counts/dimensions/
timestamps must be non-negative integers, ``fingerprint_sha256`` must be a
64-hex sha256, ``artifact_ref`` must be a safe root-relative path).  Free-text
provenance fields are not over-constrained so legacy semantics can be recorded
verbatim.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# ── Exceptions ────────────────────────────────────────────────────────────────


class StreamStoreError(Exception):
    """Base error for the frozen stream/head-stream store."""


class StreamNotFoundError(StreamStoreError):
    """No registry row exists for the requested logical ``(song_id, backbone)``."""


class StreamNotReadyError(StreamStoreError):
    """A registry row exists but is not ``ready``, so it must not satisfy a read."""


class StreamValidationError(StreamStoreError):
    """A ``ready`` row's artifact failed read-path validation (missing/corrupt/mismatch)."""


class DuplicateStreamError(StreamStoreError):
    """Registering a second row for an already-present logical identity without replacement."""


class VerifyFailureError(StreamStoreError):
    """A strict ``verify`` found a registry cache row that cannot support a complete corpus.

    Raised by the store-level ``verify(..., strict=True)`` entry point when any
    registered row is not ``ready`` after reconcile: a ``pending`` row that never
    promoted, or a ``ready`` row whose current digest payload + self-describing
    manifest no longer validate (missing/corrupt/incomplete current payloads or
    manifests, or digest/shape/dtype/finite mismatches).  Reconcile never scans
    rowless files and no supersession/legacy/archival classification exists, so those
    conditions are never a strict failure here.  The CLI ``--verify --strict``
    exit-nonzero wiring is Plan E; this is the store-level seam it calls.
    """


# ── Vocabulary / identity constants ───────────────────────────────────────────

#: The only v1 payload dtype (float32 payload codec).
STREAM_DTYPE = "float32"

#: Registry lifecycle statuses (DD: ``pending -> ready``; ``ready -> missing|corrupt``).
#: ``pending`` is the post-register, pre-reconcile state.  A ``.tmp`` staging file
#: is a file-level condition, never a registry state.
STREAM_STATUSES: frozenset[str] = frozenset({"pending", "ready", "missing", "corrupt"})

#: DuckDB logical table names (application identity ``(song_id, backbone)``).
STREAM_TABLE = "stream_registry"
HEAD_STREAM_TABLE = "head_stream_registry"

#: Exact ``stream_registry`` column order (named-column writes / row tuples).
STREAM_REGISTRY_COLUMNS: tuple[str, ...] = (
    "song_id",
    "backbone",
    "artifact_ref",
    "patch_count",
    "dim",
    "dtype",
    "format_version",
    "fingerprint_sha256",
    "preprocess_fn",
    "preprocess_version",
    "backbone_model_hash",
    "audio_params",
    "embed_semantics_version",
    "provenance_source",
    "provenance_assumption",
    "status",
    "run_id",
    "created_at",
    "updated_at",
)

#: Exact ``head_stream_registry`` column order.
HEAD_STREAM_REGISTRY_COLUMNS: tuple[str, ...] = (
    "song_id",
    "backbone",
    "artifact_ref",
    "patch_count",
    "head_ids",
    "dim_by_head",
    "format_version",
    "fingerprint_sha256",
    "preprocess_fn",
    "preprocess_version",
    "backbone_model_hash",
    "alignment_version",
    "status",
    "run_id",
    "created_at",
    "updated_at",
)

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_REQUIRED = ("song_id", "backbone", "artifact_ref", "run_id", "status")


def now_ms() -> int:
    """Return the current wall-clock time as INTEGER milliseconds (project convention).

    ``created_at``/``updated_at`` are integer milliseconds (the ML-repo ``int(time.time())``
    seconds bug is intentionally avoided).  This helper stays independent of the
    nomarr production time helper so the pure research layer imports cleanly under tests.
    """

    # helpers are intentionally not imported by this pure research package.
    return int(time.time() * 1000)


# ── Validation helpers ────────────────────────────────────────────────────────


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(f"{name} must be text; got {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer; got {type(value).__name__}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}; got {value!r}")
    return value


def validate_status(status: object) -> str:
    """Validate a registry status against the DD lifecycle vocabulary."""
    text = _require_text(status, "status")
    if text not in STREAM_STATUSES:
        raise ValueError(f"Unknown registry status {status!r}. Allowed: {sorted(STREAM_STATUSES)}")
    return text


def validate_dtype(dtype: object) -> str:
    """The only v1 payload dtype is ``float32``."""
    text = _require_text(dtype, "dtype")
    if text != STREAM_DTYPE:
        raise ValueError(f"Stream dtype must be {STREAM_DTYPE!r}; got {dtype!r}")
    return text


def validate_fingerprint(value: object) -> str:
    """``fingerprint_sha256`` must be a 64-char lowercase sha256 hex digest."""
    text = _require_text(value, "fingerprint_sha256")
    if _FINGERPRINT_RE.match(text) is None:
        raise ValueError(f"fingerprint_sha256 must be a 64-char lowercase sha256 hex digest; got {value!r}")
    return text


def validate_artifact_ref(value: object) -> str:
    """A root-relative, opaque artifact reference (never an absolute path / SQL key).

    The reference is relative to the store's ``OUTPUT_ROOT`` and must not escape it
    (no absolute paths, no ``..`` traversal segments).  Resolution happens only inside
    the store; downstream code never sees an absolute path from this field.
    """
    text = _require_text(value, "artifact_ref")
    if text.startswith(("/", "\\")) or ":" in text.split("/", 1)[0]:
        raise ValueError(f"artifact_ref must be root-relative (no absolute path); got {value!r}")
    parts = PurePosixPath(text).parts
    if not parts or ".." in parts:
        raise ValueError(f"artifact_ref must not contain '..' traversal; got {value!r}")
    return text


# ── Canonical head-ID / dimension serialization (R3/R4) ───────────────────────
# Head IDs and per-head dimensions are stored as a *stable canonical text* form,
# never as an unbounded opaque blob.  ``canonical_dim_by_head``/``canonical_head_ids``
# sort by head name so two equal-content sets serialize identically.


def canonical_head_ids(heads: Iterable[str]) -> str:
    """Canonical serialized head IDs: sorted, comma-joined, deduplicated."""
    unique: list[str] = []
    seen: set[str] = set()
    for head in sorted(_require_text(h, "head") for h in heads):
        if head not in seen:
            seen.add(head)
            unique.append(head)
    if not unique:
        raise ValueError("head_ids must contain at least one head")
    return ",".join(unique)


def canonical_dim_by_head(dims: Mapping[str, int]) -> str:
    """Canonical serialized ``head=dim`` pairs, sorted by head name (``;``-joined)."""
    if not dims:
        raise ValueError("dim_by_head must contain at least one head")
    pairs: list[str] = []
    for head in sorted(dims, key=str):
        name = _require_text(head, "head")
        dim = _require_int(dims[head], f"dim_by_head[{name!r}]", minimum=1)
        pairs.append(f"{name}={dim}")
    return ";".join(pairs)


def parse_head_ids(text: object) -> tuple[str, ...]:
    """Parse canonical head IDs back into an ordered tuple (canonical/sorted order)."""
    raw = _require_text(text, "head_ids")
    ids = tuple(h.strip() for h in raw.split(",") if h.strip())
    if not ids:
        raise ValueError(f"head_ids must contain at least one head; got {text!r}")
    return ids


def parse_dim_by_head(text: object) -> dict[str, int]:
    """Parse canonical ``head=dim;head=dim`` text into ``{head: dim}``."""
    raw = _require_text(text, "dim_by_head")
    result: dict[str, int] = {}
    for token in raw.split(";"):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"dim_by_head token must be 'head=dim'; got {token!r}")
        head, dim = token.split("=", 1)
        result[_require_text(head, "head")] = _require_int(int(dim), f"dim_by_head[{head!r}]", minimum=1)
    if not result:
        raise ValueError(f"dim_by_head must contain at least one head; got {text!r}")
    return result


def _coerce_created(created_at: object, updated_at: object) -> tuple[int, int]:
    created = _require_int(created_at, "created_at")
    updated = _require_int(updated_at, "updated_at")
    if created and updated and updated < created:
        raise ValueError(f"updated_at ({updated}) must not precede created_at ({created})")
    return created, updated


# ── StreamRecord ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StreamRecord:
    """One frozen per-song patch stream: logical identity + validated scalar metadata.

    The logical identity is ``(song_id, backbone)``.  ``artifact_ref`` is an opaque
    root-relative reference resolved only inside the store — never a path identity,
    SQL key, or external result ID downstream.  All numeric fields are validated
    non-negative integers; ``dtype`` is pinned to ``float32`` and ``status`` to the
    DD lifecycle vocabulary.  ``fingerprint_sha256`` is the sha256 hex of the payload
    file bytes.  Instances are immutable.
    """

    song_id: str
    backbone: str
    artifact_ref: str
    patch_count: int
    dim: int
    dtype: str
    format_version: str
    fingerprint_sha256: str
    preprocess_fn: str
    preprocess_version: str
    backbone_model_hash: str
    audio_params: str
    embed_semantics_version: int
    provenance_source: str
    provenance_assumption: str
    status: str
    run_id: str
    created_at: int
    updated_at: int

    def __post_init__(self) -> None:
        song_id = _require_text(self.song_id, "song_id")
        backbone = _require_text(self.backbone, "backbone")
        artifact_ref = validate_artifact_ref(self.artifact_ref)
        patch_count = _require_int(self.patch_count, "patch_count")
        dim = _require_int(self.dim, "dim", minimum=1)
        dtype = validate_dtype(self.dtype)
        format_version = _require_text(self.format_version, "format_version")
        fingerprint = validate_fingerprint(self.fingerprint_sha256)
        preprocess_fn = _require_text(self.preprocess_fn, "preprocess_fn", allow_empty=True)
        preprocess_version = _require_text(self.preprocess_version, "preprocess_version", allow_empty=True)
        backbone_model_hash = _require_text(self.backbone_model_hash, "backbone_model_hash", allow_empty=True)
        audio_params = _require_text(self.audio_params, "audio_params", allow_empty=True)
        embed_semantics_version = _require_int(self.embed_semantics_version, "embed_semantics_version")
        provenance_source = _require_text(self.provenance_source, "provenance_source")
        provenance_assumption = _require_text(self.provenance_assumption, "provenance_assumption", allow_empty=True)
        status = validate_status(self.status)
        run_id = _require_text(self.run_id, "run_id")
        created, updated = _coerce_created(self.created_at, self.updated_at)
        object.__setattr__(self, "song_id", song_id)
        object.__setattr__(self, "backbone", backbone)
        object.__setattr__(self, "artifact_ref", artifact_ref)
        object.__setattr__(self, "patch_count", patch_count)
        object.__setattr__(self, "dim", dim)
        object.__setattr__(self, "dtype", dtype)
        object.__setattr__(self, "format_version", format_version)
        object.__setattr__(self, "fingerprint_sha256", fingerprint)
        object.__setattr__(self, "preprocess_fn", preprocess_fn)
        object.__setattr__(self, "preprocess_version", preprocess_version)
        object.__setattr__(self, "backbone_model_hash", backbone_model_hash)
        object.__setattr__(self, "audio_params", audio_params)
        object.__setattr__(self, "embed_semantics_version", embed_semantics_version)
        object.__setattr__(self, "provenance_source", provenance_source)
        object.__setattr__(self, "provenance_assumption", provenance_assumption)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)

    def row_tuple(self) -> tuple[object, ...]:
        """Values in :data:`STREAM_REGISTRY_COLUMNS` order (named-column DB writes)."""
        return tuple(getattr(self, col) for col in STREAM_REGISTRY_COLUMNS)

    @classmethod
    def from_row(cls, row: Sequence[object]) -> StreamRecord:
        """Build a record from a DB row in :data:`STREAM_REGISTRY_COLUMNS` order."""
        values = dict(zip(STREAM_REGISTRY_COLUMNS, row, strict=False))
        return cls(**values)

    def with_status(self, status: str) -> StreamRecord:
        """A copy of this record with a new status (keeps timestamps/identity)."""
        return replace(self, status=validate_status(status))


# ── HeadStreamRecord ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HeadStreamRecord:
    """A complete, patch-aligned per-song head-activation stream.

    Identity is ``(song_id, backbone)``.  ``head_ids`` and ``dim_by_head`` are the
    canonical serialized head-ID / per-head-dimension texts (sorted, stable) so the
    head suite is fully described in scalar metadata, never as an opaque blob.
    ``alignment_version`` names the patch-alignment contract used by ``infer-heads``.
    """

    song_id: str
    backbone: str
    artifact_ref: str
    patch_count: int
    head_ids: str
    dim_by_head: str
    format_version: str
    fingerprint_sha256: str
    preprocess_fn: str
    preprocess_version: str
    backbone_model_hash: str
    alignment_version: str
    status: str
    run_id: str
    created_at: int
    updated_at: int

    def __post_init__(self) -> None:
        song_id = _require_text(self.song_id, "song_id")
        backbone = _require_text(self.backbone, "backbone")
        artifact_ref = validate_artifact_ref(self.artifact_ref)
        patch_count = _require_int(self.patch_count, "patch_count")
        head_ids = canonical_head_ids(parse_head_ids(self.head_ids))
        dims = parse_dim_by_head(self.dim_by_head)
        # Canonical head IDs and dimension keys must describe the SAME head set.
        if set(dims) != set(parse_head_ids(head_ids)):
            raise ValueError(
                f"head_ids and dim_by_head disagree on the head set "
                f"(ids={parse_head_ids(head_ids)!r}, dims={tuple(sorted(dims))!r})"
            )
        dim_by_head = canonical_dim_by_head(dims)
        format_version = _require_text(self.format_version, "format_version")
        fingerprint = validate_fingerprint(self.fingerprint_sha256)
        preprocess_fn = _require_text(self.preprocess_fn, "preprocess_fn", allow_empty=True)
        preprocess_version = _require_text(self.preprocess_version, "preprocess_version", allow_empty=True)
        backbone_model_hash = _require_text(self.backbone_model_hash, "backbone_model_hash", allow_empty=True)
        alignment_version = _require_text(self.alignment_version, "alignment_version")
        status = validate_status(self.status)
        run_id = _require_text(self.run_id, "run_id")
        created, updated = _coerce_created(self.created_at, self.updated_at)
        object.__setattr__(self, "song_id", song_id)
        object.__setattr__(self, "backbone", backbone)
        object.__setattr__(self, "artifact_ref", artifact_ref)
        object.__setattr__(self, "patch_count", patch_count)
        object.__setattr__(self, "head_ids", head_ids)
        object.__setattr__(self, "dim_by_head", dim_by_head)
        object.__setattr__(self, "format_version", format_version)
        object.__setattr__(self, "fingerprint_sha256", fingerprint)
        object.__setattr__(self, "preprocess_fn", preprocess_fn)
        object.__setattr__(self, "preprocess_version", preprocess_version)
        object.__setattr__(self, "backbone_model_hash", backbone_model_hash)
        object.__setattr__(self, "alignment_version", alignment_version)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)

    def row_tuple(self) -> tuple[object, ...]:
        """Values in :data:`HEAD_STREAM_REGISTRY_COLUMNS` order."""
        return tuple(getattr(self, col) for col in HEAD_STREAM_REGISTRY_COLUMNS)

    @classmethod
    def from_row(cls, row: Sequence[object]) -> HeadStreamRecord:
        """Build a record from a DB row in :data:`HEAD_STREAM_REGISTRY_COLUMNS` order."""
        values = dict(zip(HEAD_STREAM_REGISTRY_COLUMNS, row, strict=False))
        return cls(**values)

    def with_status(self, status: str) -> HeadStreamRecord:
        """A copy of this record with a new status (keeps timestamps/identity)."""
        return replace(self, status=validate_status(status))


# ── ReconcileReport ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReconcileReport:
    """Result of reconciling registry cache rows against current filesystem artifacts.

    ``ready``/``missing``/``corrupt``/``pending`` are the post-pass persisted row
    counts by status.  Reconcile walks the registry ROWS (never scanning for rowless
    files) and validates each referenced current digest payload + self-describing
    manifest, promoting a ``pending`` row to ``ready`` only when fully valid, marking
    a previously ``ready`` row ``missing``/``corrupt`` when its artifact no longer
    validates, and refusing corrupt/incomplete artifacts and reporting any row that fails
    to reach ready (a pending row with a valid manifest+payload promotes; one whose artifact
    is absent/corrupt stays pending and is reported) — never emitting legacy status rows.  ``stale`` counts rows that were ``ready`` before this pass
    and are no longer ``ready`` after it (a previously verified stream degraded).

    The ``orphan``/``superseded``/``legacy``/``stray`` fields are retained only as
    registry/cache characterization: the legacy-adoption/supersession/rowless
    classification machinery was deleted by Plan B, so reconcile never scans rowless
    files and these counts are always 0.

    ``strict`` records whether the reconcile ran in strict ``--verify`` mode; issues
    carry human-readable notes for any non-ready condition.
    """

    scanned: int = 0
    ready: int = 0
    pending: int = 0
    missing: int = 0
    corrupt: int = 0
    orphan: int = 0
    superseded: int = 0
    legacy: int = 0
    stray: int = 0
    stale: int = 0
    strict: bool = False
    issues: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        """True when every scanned row resolved to ``ready`` with no issues.

        A strict caller still decides whether to treat the report as failure; this
        only reports the unqualified readiness of the scanned registry.  The
        orphan/superseded/legacy/stray counts are always 0 under current reconcile
        (the rowless-classification machinery is deleted), so clean is purely
        readiness of the scanned rows plus an empty issues list.
        """
        return self.scanned > 0 and self.ready == self.scanned and self.orphan == 0 and not self.issues


# ── Post-migration digest-only record types (Plan B Phase 2) ──────────────────

#: Root-relative reference grammar separator helpers for the immutable artifact
#: layout.  A payload is ``<subdir>/<sid>.<backbone>.<64-hex>.npy|.npz`` and its
#: self-describing manifest is the same digest name with a ``.json`` suffix.
MANIFEST_SUFFIX = ".json"
_PAYLOAD_SUFFIXES = (".npy", ".npz")


def payload_to_manifest_ref(artifact_ref: str) -> str:
    """The root-relative ``.json`` manifest ref for a digest payload artifact ref."""
    if artifact_ref.startswith(("/", "../")) or ".." in artifact_ref.split("/"):
        raise ValueError(f"artifact_ref must be root-relative; got {artifact_ref!r}")
    for suffix in _PAYLOAD_SUFFIXES:
        if artifact_ref.endswith(suffix):
            return artifact_ref[: -len(suffix)] + MANIFEST_SUFFIX
    raise ValueError(f"artifact_ref must end in a payload suffix; got {artifact_ref!r}")


@dataclass(frozen=True)
class MaskRecord:
    """Immutable audio-derived silence mask metadata (uint8, 1 == searchable).

    A mask shares the *stream logical identity* (song_id/backbone) of the observation
    it annotates.  It is produced from production audio-derived machinery (S3) and is
    never derived from a model/session/ONNX/CUDA at read time.  The payload is a
    one-dimensional uint8 ``[patch_count]`` mask (``dimension == 1``); ``1`` marks
    searchable patches.  Masks have no retained DuckDB registry table: their
    authoritative form is the immutable digest-named ``.npy`` payload plus the
    self-describing ``.json`` manifest.
    """

    song_id: str
    backbone: str
    artifact_ref: str
    mask_sha256: str
    patch_count: int
    dimension: int = 1
    dtype: str = "uint8"
    format_version: str = "1"
    mask_semantics_version: str = "1"
    algorithm: str = ""
    threshold_dbfs: float | None = None
    min_silent_run_frames: int | None = None
    hysteresis_frames: int | None = None
    params_id: str = ""
    audio_content_sha256: str = ""
    preprocess_fn: str = ""
    preprocess_version: str = ""
    provenance_source: str = "mask"
    run_id: str = ""
    created_at: int | None = None
    status: str = "pending"

    def __post_init__(self) -> None:
        validate_artifact_ref(self.artifact_ref)
        validate_fingerprint(self.mask_sha256)
        if not self.song_id or "." in self.song_id:
            raise ValueError("mask song_id must be a dot-free token")
        if not self.backbone:
            raise ValueError("mask backbone must be non-empty")
        if self.patch_count < 1:
            raise ValueError("mask patch_count must be >= 1")
        if self.dimension != 1:
            raise ValueError(f"mask dimension must be 1; got {self.dimension}")
        if self.dtype != "uint8":
            raise ValueError(f"mask dtype must be uint8; got {self.dtype}")
        if self.created_at is not None and self.created_at < 0:
            raise ValueError("mask created_at must be non-negative")


@dataclass(frozen=True)
class ObservationCommit:
    """Immutable observation-commit marker (the LAST-published artifact of a group).

    A stream + audio-mask pair is ONE logical observation group.  The publication
    protocol writes the individual payload + manifest artifacts first and stages the
    ``observation_commits/<sid>.<bb>.<commit_sha256>.json`` marker LAST.  Registry-row
    promotion (``reconcile``) is per artifact: a ``pending`` stream row promotes to
    ``ready`` on that row's own referenced digest payload + manifest validation, with NO
    commit-marker or mask check.  The FULL observation-group readiness — the commit marker
    *and* every referenced stream/mask manifest + payload verified — is enforced only by
    the ``observation_group_ready`` flow and by reindex (mirror :class:`ReconcileReport`).
    This dataclass models the marker contents; the marker's digest name is the sha256 over the marker content
    dict EXCLUDING its own ``commit_sha256`` field (the DD catalog-id pattern) — that
    field is then added before the marker is serialized, so re-reading the marker
    recomputes the same digest.
    """

    song_id: str
    backbone: str
    stream_ref: str
    mask_ref: str | None
    commit_sha256: str
    alignment_token: str = ""
    mask_semantics_version: str | None = None
    group_format_version: str = "1"
    audio_content_sha256: str = ""
    run_id: str = ""
    created_at: int | None = None
    status: str = "ready"

    def __post_init__(self) -> None:
        if not self.song_id or "." in self.song_id:
            raise ValueError("commit song_id must be a dot-free token")
        if not self.backbone:
            raise ValueError("commit backbone must be non-empty")
        validate_artifact_ref(self.stream_ref)
        if self.mask_ref is not None:
            validate_artifact_ref(self.mask_ref)
        validate_fingerprint(self.commit_sha256)
        if self.created_at is not None and self.created_at < 0:
            raise ValueError("commit created_at must be non-negative")
        if self.status not in STREAM_STATUSES:
            raise ValueError(f"invalid commit status {self.status!r}")


@dataclass(frozen=True)
class ReindexReport:
    """Result of the filesystem-authoritative (re)index walk over current manifests.

    The registry is a *rebuildable cache/index*, never the source of truth for
    artifact existence or content.  A reindex walks only the current-format digest
    manifests + observation-commit markers on disk and rebuilds registry rows from
    them.  ``scanned`` = artifacts indexed, ``rows_rebuilt`` = registry cache rows
    written/refreshed, ``ready`` = rows validated ready (manifest + payload all
    verify), ``orphan_payloads`` = digest payload files with no validated manifest,
    ``issues`` = human-readable notes for anything refused.
    """

    scanned: int = 0
    rows_rebuilt: int = 0
    ready: int = 0
    orphan_payloads: int = 0
    issues: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        """True when the walk indexed >=1 current artifact with no orphans/issues."""
        return self.scanned > 0 and self.ready == self.scanned and self.orphan_payloads == 0 and not self.issues
