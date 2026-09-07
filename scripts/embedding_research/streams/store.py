"""StreamStore / HeadStreamStore — the only downstream boundary to frozen observation streams.

This is the "thin interface" seam from the DD (``scripts/embedding_research`` A-prime design):

* :meth:`StreamStore.lookup` / :meth:`HeadStreamStore.lookup` — validated scalar metadata
  for one logical ``(song_id, backbone)``; returns an immutable record carrying an OPAQUE
  root-relative ``artifact_ref``.  Non-``ready`` rows are refused (raised), and the ref is
  never a path identity / SQL key / external result ID.
* :meth:`StreamStore.batch_gather` / :meth:`HeadStreamStore.batch_gather` — the only
  vector-read path.  Loads the artifact with ``allow_pickle=False``, checks SHA-256,
  dtype (``float32``), shape and finite values, then performs vectorized row selection.
* :meth:`StreamStore.publish` / :meth:`HeadStreamStore.publish` — the immutable writer.
  Serializes the payload, computes its sha256, writes it to a **digest-named** immutable
  artifact under ``streams/`` / ``heads/`` (never replacing bytes at an existing digest),
  writes a self-describing ``.json`` manifest beside it, then registers the identity
  ``pending`` via the app-level duplicate guard (transactional delete-then-insert).
  The head writer additionally durably publishes the filesystem-authoritative
  ``heads/current/`` CURRENT-suite marker (payload + manifest + CURRENT marker are the
  three durable writes), superseding any prior marker for the ``(song_id, backbone)``.
* :meth:`StreamStore.reconcile` — promote ``pending`` rows whose **manifest + payload**
  validate to ``ready``, demote ``ready`` rows whose artifact degrades to
  ``missing``/``corrupt``, and return a :class:`ReconcileReport`.

The ``stream_registry`` / ``head_stream_registry`` tables are a REBUILDABLE CACHE/INDEX for
downstream consumers — they are never the source of truth for artifact existence or content.
Artifact bytes and self-describing manifests on disk are authoritative; a registry row only
becomes ``ready`` when the referenced manifest + payload both verify.  Post-migration there is
NO bare/``.vN``/legacy grammar and no supersession/adoption/rowless-orphan classification in
this store (Git is the source archive; old outputs are never interpreted at runtime).

Artifact references are resolved against the store's ``output_root`` (default
``config.OUTPUT_ROOT``) ONLY inside this store.  Callers hand the store a connection and
never reach the filesystem themselves.

Module placement (documented choice): a top-level ``streams/`` package (``records.py`` +
``store.py``), separate from the pure ``helpers/`` contracts and the ``db/`` persistence
layer, so later plans (C-F) import one stable StreamStore/record vocabulary without
touching either package.  The low-level SQL lives in ``db/stream_registry.py`` and is
re-exported through ``db/__init__``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT
from scripts.embedding_research.db import stream_registry as _reg
from scripts.embedding_research.streams.masks import (
    CurrentMaskResolver,
    MaskPayload,
    mask_npy_bytes,
    mask_record_from_payload,
)
from scripts.embedding_research.streams.publication import (
    FileOps,
    digest_artifact_name,
    durable_write_if_absent,
    npy_bytes,
    npz_bytes,
    read_json_manifest,
    write_json_durable,
)
from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    HEAD_STREAM_TABLE,
    STREAM_DTYPE,
    STREAM_REGISTRY_COLUMNS,
    STREAM_TABLE,
    DuplicateStreamError,
    HeadStreamRecord,
    MaskRecord,
    ObservationCommit,
    ObservationGroupIdentity,
    ReconcileReport,
    StreamNotFoundError,
    StreamNotReadyError,
    StreamRecord,
    StreamStoreError,
    StreamValidationError,
    VerifyFailureError,
    canonical_dim_by_head,
    canonical_head_ids,
    now_ms,
    parse_dim_by_head,
    parse_head_ids,
    payload_to_manifest_ref,
    validate_status,
)

__all__ = [
    "CommittedObservation",
    "CurrentMaskResolver",
    "CurrentStreamResolver",
    "HeadStreamStore",
    "StreamStore",
    "make_current_mask_resolver",
    "make_current_stream_resolver",
    "observation_group_ready",
]


def _sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _to_index_array(source_patch_indices, patch_count: int) -> np.ndarray:
    """Validate source patch indices are in-range integers and return an int array."""
    raw = source_patch_indices if isinstance(source_patch_indices, np.ndarray) else np.asarray(source_patch_indices)
    if raw.ndim != 1:
        raise ValueError(f"source_patch_indices must be 1-D; got shape {raw.shape}")
    if raw.dtype.kind not in "iu":
        if raw.size:
            raise ValueError(f"source_patch_indices must be integers; got dtype {raw.dtype}")
        raw = raw.astype(np.int64)  # empty selection is safe regardless of nominal dtype
    idx = raw.astype(np.int64, copy=False)
    if idx.size and (idx.min() < 0 or idx.max() >= patch_count):
        raise ValueError(
            f"source_patch_indices out of range for patch_count={patch_count}: min={idx.min()}, max={idx.max()}"
        )
    return idx


def _reject_duplicate_indices(idx: np.ndarray, *, forbid: bool) -> None:
    """Reject duplicate source patch indices for uniqueness-required gather contracts.

    Membership/medoid gathers (seg membership medoid selection) require unique source
    rows; callers pass ``forbid_duplicates=True`` to enforce that.  An empty selection
    and a single repeated-free selection are always legal.
    """
    if forbid and idx.size and np.unique(idx).size != idx.size:
        raise ValueError("duplicate source patch indices are forbidden for this gather contract")


class _RegistryStore:
    """Shared registry lifecycle logic parameterized by table/columns/record class."""

    # Subclasses set these.
    _table: str
    _columns: tuple[str, ...]
    _record_cls: type
    _default_subdir: str
    _suffix: str
    _manifest_kind: str

    def __init__(self, con, *, output_root: str | Path | None = None) -> None:
        self._con = con
        self._output_root = Path(output_root) if output_root is not None else Path(OUTPUT_ROOT)

    @property
    def output_root(self) -> Path:
        """The storage root this store publishes artifacts under (read-only, public seam).

        Plan D's disposable search-view materialization derives its disposable-views
        directory from the same root so view bytes stay beside the frozen streams that
        produced them and under the same test-isolated tmp root.  The root is a storage
        location only — it is never an identity, SQL key, or external result ID (R3).
        """
        return self._output_root

    # ── path resolution (never exposed to callers) ───────────────────────────
    def _path(self, artifact_ref: str) -> Path:
        return self._output_root / artifact_ref

    # ── self-describing manifest path + validation ───────────────────────────
    def _manifest_path(self, record) -> Path:
        """The root-relative ``.json`` manifest sibling of a digest payload ref."""
        return self._path(payload_to_manifest_ref(record.artifact_ref))

    def _manifest(self, record, *, byte_size: int) -> dict[str, object]:
        """The self-describing manifest dict for a freshly-published artifact.

        The manifest carries the full committed registry row (as a rebuildable cache
        pre-image) plus the digest-derived fields a reindex needs to reconstruct the row
        from the filesystem alone: ``kind``, ``schema_version``, ``payload_sha256`` and
        ``byte_size``.  ``created_at``/``updated_at`` are deliberately EXCLUDED: they are
        publish-time cache-row bookkeeping that a reindex regenerates, and including them
        would make the manifest bytes differ across identical re-publishes — violating
        the content-addressed no-replace invariant (identical payload -> identical digest
        filename -> identical manifest bytes).  Serialization is deterministic (see
        ``write_json_durable``).
        """
        data: dict[str, object] = dict(zip(self._columns, record.row_tuple(), strict=False))
        data.pop("created_at", None)
        data.pop("updated_at", None)
        data["kind"] = self._manifest_kind
        data["schema_version"] = "1"
        data["payload_sha256"] = record.fingerprint_sha256
        data["byte_size"] = byte_size
        return data

    def _digest_ref(self, song_id: str, backbone: str, digest: str) -> str:
        """The root-relative digest-grammar artifact ref under this store's subdir."""
        name = digest_artifact_name(song_id, backbone, digest, self._suffix)
        return f"{self._default_subdir}/{name}"

    def _write_manifest(self, record, payload: bytes, ops: FileOps) -> None:
        """Durably write the self-describing ``.json`` manifest (immutable, first-write).

        The manifest shares its content-addressed digest name with the payload (a manifest
        is the self-describing record for that exact payload content).  Because re-publishing
        IDENTICAL payload bytes in a later run legitimately differs only in run-time
        provenance (``run_id``/timestamps), the FIRST committed manifest for a content is
        authoritative and later identical publishes skip the write (never replace bytes at an
        existing digest).  Manifest integrity is re-validated at reconcile/read time, not write.
        """
        manifest_path = self._manifest_path(record)
        if manifest_path.is_file():
            return
        manifest = self._manifest(record, byte_size=len(payload))
        write_json_durable(manifest_path, manifest, ops)

    def _manifest_ok(self, record) -> bool:
        """Does the referenced manifest exist, parse, and self-describe THIS artifact?"""
        manifest_path = self._manifest_path(record)
        if not manifest_path.is_file():
            return False
        try:
            data = read_json_manifest(manifest_path)
        except ValueError:
            return False
        return bool(
            data.get("kind") == self._manifest_kind
            and data.get("schema_version") == "1"
            and data.get("payload_sha256") == record.fingerprint_sha256
            and data.get("song_id") == record.song_id
            and data.get("backbone") == record.backbone
            and data.get("patch_count") == record.patch_count
        )

    # ── lookup / register / replace ──────────────────────────────────────────
    def lookup(self, song_id: str, backbone: str):
        """Resolve a ready-gated row for ``(song_id, backbone)``.

        Returns the validated ``StreamRecord``/``HeadStreamRecord`` whose status is
        ``ready``; raises :class:`StreamNotFoundError` when no row exists and
        :class:`StreamNotReadyError` when the row exists but is not yet ready.
        """
        row = _reg.select_row(self._con, self._table, self._columns, song_id, backbone)
        if row is None:
            raise StreamNotFoundError(f"No {self._table} row for ({song_id!r}, {backbone!r})")
        record = self._record_cls.from_row(tuple(row))
        if record.status != "ready":
            raise StreamNotReadyError(
                f"{self._table} row for ({song_id!r}, {backbone!r}) has status "
                f"{record.status!r}; only 'ready' rows satisfy reads"
            )
        return record

    def _register_impl(self, record, status: str, *, replace_existing: bool) -> object:
        target = replace(
            record,
            status=validate_status(status),
            created_at=now_ms(),
            updated_at=now_ms(),
        )
        if replace_existing:
            _reg.replace_row(self._con, self._table, self._columns, target.row_tuple())
        else:
            if _reg.identity_exists(self._con, self._table, record.song_id, record.backbone):
                raise DuplicateStreamError(
                    f"Cannot register ({record.song_id!r}, {record.backbone!r}): a {self._table} "
                    "row already exists. Use register(..., replace=True) to repoint the logical "
                    "identity at a newer immutable artifact."
                )
            _reg.insert_row(self._con, self._table, self._columns, target.row_tuple())
        return target

    def register(self, record, *, status: str = "pending"):
        """Persist a completed durable payload as a registry row.

        Status is ``pending`` by default (the DD publication order is register-pending
        then reconcile-to-ready).  A duplicate logical identity without ``replace=True``
        is rejected by the app-level guard.
        """
        return self._register_impl(record, status=status, replace_existing=False)

    def replace(self, record, *, status: str = "pending"):
        """Atomically repoint ``(song_id, backbone)`` at a newer immutable artifact.

        Transactional delete-then-insert (never leaves a duplicate row).  Publication
        uses this when a logical identity is (re)published — content-addressed so a new
        digest is a new immutable artifact and the row moves to it.
        """
        return self._register_impl(record, status=status, replace_existing=True)

    def has_ready(self, song_id: str, backbone: str) -> bool:
        """True when the identity already has a verified ``ready`` registry row.

        Embed skip semantics depend on this: a song/backbone is skipped only when the
        registry already holds a ``ready`` record (not merely because a file exists) and
        ``force`` is False.
        """
        row = _reg.select_row(self._con, self._table, self._columns, song_id, backbone)
        return row is not None and self._record_cls.from_row(tuple(row)).status == "ready"

    def run_records(self, run_id: str) -> list:
        """Every registry row published by one ``run_id`` (any status)."""
        rows = _reg.list_rows(self._con, self._table, self._columns)
        run_col = self._columns.index("run_id")
        return [self._record_cls.from_row(tuple(r)) for r in rows if r[run_col] == run_id]

    def ready_rows(self) -> list:
        """Every registry row currently in the verified ``ready`` state."""
        rows = _reg.list_rows(self._con, self._table, self._columns)
        status_col = self._columns.index("status")
        return [self._record_cls.from_row(tuple(r)) for r in rows if r[status_col] == "ready"]

    # ── reconciliation ───────────────────────────────────────────────────────
    def _payload_ok(self, path: Path, record) -> bool:
        """Subclass check: does the on-disk payload validate against *record*?"""
        raise NotImplementedError

    def _artifact_ok(self, path: Path, record) -> bool:
        """Manifest + payload both validate against *record* (filesystem is authority)."""
        if not self._manifest_ok(record):
            return False
        return self._payload_ok(path, record)

    def _classify(self, record) -> str:
        path = self._path(record.artifact_ref)
        if not path.is_file():
            return "missing"
        try:
            return "ready" if self._artifact_ok(path, record) else "corrupt"
        except (OSError, ValueError, StreamValidationError):
            return "corrupt"

    def reconcile(self, *, strict: bool = False) -> ReconcileReport:
        """Reconcile registry cache rows against on-disk manifest + payload and report.

        Applies only DD-allowed transitions: ``pending`` rows whose referenced manifest +
        payload validate promote to ``ready``; any non-``pending`` row adopts its
        file-derived state (``ready`` stays ``ready``, a missing artifact becomes
        ``missing``, a corrupt artifact becomes ``corrupt``, and a recovered artifact
        returns the row to ``ready``).  A ``pending`` row whose artifact is absent/corrupt
        stays ``pending`` (pending only promotes) and is reported as an issue rather than
        forced into a forbidden state.

        The registry is a cache/index only: reconcile walks the ROWS and validates each
        referenced artifact against the authoritative filesystem.  It does NOT scan for
        rowless files (superseded/legacy/stray) — orphan detection and manifest-only
        reindex belong to the Phase-5 filesystem-authoritative reconcile/reindex.
        """
        rows = _reg.list_rows(self._con, self._table, self._columns)
        final_statuses: dict[tuple[str, str], str] = {}
        pre_ready: set[tuple[str, str]] = set()
        issues: list[str] = []

        for row in rows:
            record = self._record_cls.from_row(tuple(row))
            identity = (record.song_id, record.backbone)
            if record.status == "ready":
                pre_ready.add(identity)
            desired = self._classify(record)
            if record.status == "pending":
                final = "ready" if desired == "ready" else "pending"
            else:
                final = desired
            if final != record.status:
                _reg.update_status(self._con, self._table, record.song_id, record.backbone, final, now_ms())
            final_statuses[identity] = final
            if final != "ready":
                issues.append(f"{record.song_id}:{record.backbone} -> {final}")

        counts = {
            status: sum(1 for s in final_statuses.values() if s == status)
            for status in ("ready", "pending", "missing", "corrupt")
        }
        stale = sum(1 for identity, final in final_statuses.items() if identity in pre_ready and final != "ready")

        return ReconcileReport(
            scanned=len(rows),
            ready=counts["ready"],
            pending=counts["pending"],
            missing=counts["missing"],
            corrupt=counts["corrupt"],
            orphan=0,
            superseded=0,
            legacy=0,
            stray=0,
            stale=stale,
            strict=strict,
            issues=tuple(issues),
        )

    def verify(self, *, strict: bool = False) -> ReconcileReport:
        """Reconcile, then report (and under ``strict`` refuse) an unsound corpus.

        This is the store-level seam behind the DD ``--verify`` / ``--verify --strict``
        contract (CLI wiring is Plan E).  It first runs the normal :meth:`reconcile`
        (so statuses are current), then decides whether the reconciled registry can
        support a "complete corpus" claim:

        * non-strict: returns the :class:`ReconcileReport` (which carries ``issues``
          and ``clean``) for the caller to inspect — never raises;
        * strict: RAISES :class:`VerifyFailureError` when any registered row is not
          ``ready`` (missing/corrupt/never-promoted pending).

        A fully verified corpus returns the report (``report.ready == report.scanned``)
        without raising.
        """
        report = self.reconcile(strict=strict)
        if strict and not self._strict_clean(report):
            problems = report.issues or ("no issues recorded",)
            raise VerifyFailureError(
                f"{type(self).__name__} strict verify failed for {self._table}: "
                f"ready={report.ready}/{report.scanned}, pending={report.pending}, "
                f"missing={report.missing}, corrupt={report.corrupt}; {'; '.join(problems)}"
            )
        return report

    @staticmethod
    def _strict_clean(report: ReconcileReport) -> bool:
        """True when *report* supports a strict ``--verify`` complete-corpus claim.

        Every scanned registry cache row must be ``ready`` (no missing/corrupt/
        unpromoted pending).  Rowless-orphan scanning (legacy/stray/superseded) is not a
        Phase-2 reconcile concern; the Phase-5 manifest walk is authoritative for that.
        """
        return report.scanned >= 1 and report.ready == report.scanned


class StreamStore(_RegistryStore):
    """Frozen per-song float32 patch streams over immutable digest-named ``.npy`` + manifest."""

    _table = STREAM_TABLE
    _columns = STREAM_REGISTRY_COLUMNS
    _record_cls = StreamRecord
    _default_subdir = "streams"
    _suffix = ".npy"
    _manifest_kind = "stream"

    def _payload_ok(self, path: Path, record: StreamRecord) -> bool:
        if _sha256_hex(path) != record.fingerprint_sha256:
            return False
        try:
            arr = np.load(str(path), allow_pickle=False)
        except (OSError, ValueError):
            return False
        return (
            isinstance(arr, np.ndarray)
            and arr.dtype == np.dtype(STREAM_DTYPE)
            and arr.shape == (record.patch_count, record.dim)
        )

    # ── immutable digest publication ─────────────────────────────────────────
    def publish(
        self,
        song_id: str,
        backbone: str,
        embeddings: np.ndarray,
        *,
        run_id: str,
        preprocess_fn: str = "",
        preprocess_version: str = "",
        backbone_model_hash: str = "",
        audio_params: str = "",
        embed_semantics_version: int = 1,
        format_version: str = "1",
        provenance_source: str = "embed",
        provenance_assumption: str = "",
        file_ops: FileOps | None = None,
    ) -> StreamRecord:
        """Durably publish one frozen stream and register it ``pending``.

        Serializes *embeddings* to float32 C-order ``.npy`` bytes and computes its
        payload sha256.  The artifact is written to the immutable, content-addressed,
        digest-named path ``streams/<sid>.<backbone>.<sha256>.npy`` (NEVER replacing
        bytes at an existing digest — identical bytes reuse the existing artifact,
        different bytes produce a different digest file), followed by the self-describing
        ``.json`` manifest.  Then in one transaction the ``(song_id, backbone)`` registry
        row is replaced with a ``pending`` record carrying full provenance.  Returns that
        pending record; the caller reconciles the phase to promote to ``ready``.
        """
        ops = file_ops if file_ops is not None else FileOps()
        arr = np.ascontiguousarray(embeddings, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"embeddings must be 2-D [patch_count, dim]; got shape {arr.shape}")
        if arr.shape[0] < 1:
            raise ValueError("embeddings must contain at least one patch row")
        if not np.isfinite(arr).all():
            raise ValueError("embeddings contain non-finite values")
        payload = npy_bytes(arr)
        fingerprint = hashlib.sha256(payload).hexdigest()
        artifact_ref = self._digest_ref(song_id, backbone, fingerprint)
        final_path = self._path(artifact_ref)
        durable_write_if_absent(final_path, payload, ops)
        now = now_ms()
        record = StreamRecord(
            song_id=song_id,
            backbone=backbone,
            artifact_ref=artifact_ref,
            patch_count=arr.shape[0],
            dim=arr.shape[1],
            dtype=STREAM_DTYPE,
            format_version=format_version,
            fingerprint_sha256=fingerprint,
            preprocess_fn=preprocess_fn,
            preprocess_version=preprocess_version,
            backbone_model_hash=backbone_model_hash,
            audio_params=audio_params,
            embed_semantics_version=embed_semantics_version,
            provenance_source=provenance_source,
            provenance_assumption=provenance_assumption,
            status="pending",
            run_id=run_id,
            created_at=now,
            updated_at=now,
        )
        self._write_manifest(record, payload, ops)
        return self.replace(record, status="pending")

    def batch_gather(
        self, song_id: str, backbone: str, source_patch_indices, *, forbid_duplicates: bool = False
    ) -> np.ndarray:
        """Load a verified stream and return float32 ``[N, D]`` rows for the given patch indices.

        Refuses non-``ready`` rows and validates SHA-256, dtype, shape and finite values
        with ``allow_pickle=False`` before gathering.  Indices must be in-range integers.
        Duplicates are permitted by default (a caller may select a row more than once);
        pass ``forbid_duplicates=True`` for uniqueness-required contracts (e.g. medoid /
        seg-membership gathers), which reject any repeated source index.
        """
        record = self.lookup(song_id, backbone)
        path = self._path(record.artifact_ref)
        if not path.is_file():
            raise StreamValidationError(f"{self._table} artifact missing: {record.artifact_ref}")
        if _sha256_hex(path) != record.fingerprint_sha256:
            raise StreamValidationError(
                f"SHA-256 mismatch for {record.artifact_ref} (expected {record.fingerprint_sha256[:12]}…)"
            )
        try:
            arr = np.load(str(path), allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise StreamValidationError(f"failed to load {record.artifact_ref}: {exc}") from exc
        if not isinstance(arr, np.ndarray):
            raise StreamValidationError(f"{record.artifact_ref} does not contain a numpy array")
        if arr.dtype != np.dtype(STREAM_DTYPE):
            raise StreamValidationError(f"{record.artifact_ref} dtype {arr.dtype} != {STREAM_DTYPE}")
        if arr.shape != (record.patch_count, record.dim):
            raise StreamValidationError(
                f"{record.artifact_ref} shape {arr.shape} != registry ({record.patch_count}, {record.dim})"
            )
        if not np.isfinite(arr).all():
            raise StreamValidationError(f"{record.artifact_ref} contains non-finite values")
        idx = _to_index_array(source_patch_indices, record.patch_count)
        _reject_duplicate_indices(idx, forbid=forbid_duplicates)
        return np.asarray(arr[idx], dtype=np.float32)

    # ── observation-group publication (stream + mask + commit marker, P1-S3) ──
    _mask_subdir = "audio_masks"
    _commit_subdir = "observation_commits"

    def _mask_ref(self, song_id: str, backbone: str, mask_sha: str) -> str:
        """Root-relative ``audio_masks/<sid>.<bb>.<mask_sha>.npy`` ref."""
        name = digest_artifact_name(song_id, backbone, mask_sha, ".npy")
        return f"{self._mask_subdir}/{name}"

    def _commit_ref(self, song_id: str, backbone: str, commit_sha: str) -> str:
        """Root-relative ``observation_commits/<sid>.<bb>.<commit_sha>.json`` ref."""
        name = digest_artifact_name(song_id, backbone, commit_sha, ".json")
        return f"{self._commit_subdir}/{name}"

    def publish_mask(self, mask_payload: MaskPayload, *, file_ops: FileOps | None = None) -> MaskRecord:
        """Durably publish a uint8 mask payload + self-describing manifest under ``audio_masks/``.

        Masks have no retained DuckDB registry table (Phase 2/3); their authoritative form
        is the digest-named ``.npy`` payload + ``.json`` manifest.  The payload is written
        content-addressed (never replacing bytes at an existing digest) and the manifest
        records the full mask provenance (algorithm, dBFS threshold, frame/run hysteresis,
        ``audio_content_sha256``, ``params_id``, mask semantics).
        """
        ops = file_ops if file_ops is not None else FileOps()
        arr = np.ascontiguousarray(mask_payload.mask, dtype=np.uint8)
        payload_bytes = mask_npy_bytes(arr)
        mask_sha = hashlib.sha256(payload_bytes).hexdigest()
        artifact_ref = self._mask_ref(mask_payload.song_id, mask_payload.backbone, mask_sha)
        final_path = self._path(artifact_ref)
        durable_write_if_absent(final_path, payload_bytes, ops)
        record = mask_record_from_payload(mask_payload, artifact_ref, mask_sha)
        manifest_path = self._path(payload_to_manifest_ref(artifact_ref))
        if not manifest_path.is_file():
            manifest = self._mask_manifest(record, byte_size=len(payload_bytes))
            write_json_durable(manifest_path, manifest, ops)
        return record

    def _mask_manifest(self, record: MaskRecord, *, byte_size: int) -> dict[str, object]:
        """The self-describing mask manifest dict (digest-deterministic, no created_at)."""
        return {
            "kind": "mask",
            "schema_version": "1",
            "payload_sha256": record.mask_sha256,
            "byte_size": byte_size,
            "song_id": record.song_id,
            "backbone": record.backbone,
            "artifact_ref": record.artifact_ref,
            "patch_count": record.patch_count,
            "dimension": record.dimension,
            "dtype": record.dtype,
            "format_version": record.format_version,
            "mask_semantics_version": record.mask_semantics_version,
            "algorithm": record.algorithm,
            "threshold_dbfs": record.threshold_dbfs,
            "min_silent_run_frames": record.min_silent_run_frames,
            "hysteresis_frames": record.hysteresis_frames,
            "params_id": record.params_id,
            "audio_content_sha256": record.audio_content_sha256,
            "preprocess_fn": record.preprocess_fn,
            "preprocess_version": record.preprocess_version,
            "provenance_source": record.provenance_source,
            "run_id": record.run_id,
            "status": record.status,
        }

    def _mask_manifest_ok(self, record: MaskRecord) -> bool:
        """Does the referenced mask manifest exist, parse, and self-describe THIS mask?"""
        manifest_path = self._path(payload_to_manifest_ref(record.artifact_ref))
        if not manifest_path.is_file():
            return False
        try:
            data = read_json_manifest(manifest_path)
        except ValueError:
            return False
        return bool(
            data.get("kind") == "mask"
            and data.get("schema_version") == "1"
            and data.get("payload_sha256") == record.mask_sha256
            and data.get("song_id") == record.song_id
            and data.get("backbone") == record.backbone
            and data.get("patch_count") == record.patch_count
        )

    def _mask_payload_ok(self, record: MaskRecord) -> bool:
        """Does the on-disk mask payload match the mask record (sha + uint8 [patch_count])?"""
        path = self._path(record.artifact_ref)
        if not path.is_file():
            return False
        if _sha256_hex(path) != record.mask_sha256:
            return False
        try:
            arr = np.load(str(path), allow_pickle=False)
        except (OSError, ValueError):
            return False
        return isinstance(arr, np.ndarray) and arr.dtype == np.dtype("uint8") and arr.shape == (record.patch_count,)

    def publish_observation_group(
        self,
        stream_record: StreamRecord,
        mask_payload: MaskPayload,
        *,
        file_ops: FileOps | None = None,
    ) -> ObservationCommit:
        """Publish stream+mask as ONE observation group: mask payload/manifest, commit marker LAST.

        *stream_record* is the just-published stream (its digest payload + manifest are
        already durable via ``publish``).  Cross-identity and alignment are enforced: the
        mask ``song_id``/``backbone``/``patch_count`` MUST equal the stream's.  The mask
        payload + manifest are durably published under ``audio_masks/``, then the
        observation-commit marker is staged + durably written under ``observation_commits/``
        LAST.  The commit marker digest is the sha256 of its content excluding its own
        ``commit_sha256`` field (the DD catalog-id pattern), so re-reading the marker
        recomputes the same digest.  Returns the committed :class:`ObservationCommit`.

        A crash before the commit marker leaves NO committed observation group: the partial
        stream/mask files are individually valid immutable artifacts but the observation is
        not committed/ready (registry-ready requires the marker AND both manifests AND both
        payloads to verify — see :meth:`observation_group_ready`).
        """
        ops = file_ops if file_ops is not None else FileOps()
        if mask_payload.song_id != stream_record.song_id:
            raise ValueError(
                f"observation group song_id mismatch: mask={mask_payload.song_id!r} stream={stream_record.song_id!r}"
            )
        if mask_payload.backbone != stream_record.backbone:
            raise ValueError(
                f"observation group backbone mismatch: mask={mask_payload.backbone!r} stream={stream_record.backbone!r}"
            )
        if mask_payload.patch_count != stream_record.patch_count:
            raise ValueError(
                f"observation group patch_count mismatch: mask={mask_payload.patch_count} "
                f"stream={stream_record.patch_count}"
            )

        mask_record = self.publish_mask(mask_payload, file_ops=ops)
        now = now_ms()
        content: dict[str, object] = {
            "song_id": stream_record.song_id,
            "backbone": stream_record.backbone,
            "stream_ref": stream_record.artifact_ref,
            "mask_ref": mask_record.artifact_ref,
            "alignment_token": f"{stream_record.artifact_ref}:{mask_record.artifact_ref}",
            "mask_semantics_version": mask_payload.mask_semantics_version,
            "group_format_version": "1",
            "audio_content_sha256": mask_payload.audio_content_sha256,
            "run_id": mask_payload.run_id,
            "created_at": now,
            "status": "ready",
        }
        marker_without_id = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
        commit_sha = hashlib.sha256(marker_without_id).hexdigest()
        content["commit_sha256"] = commit_sha
        marker_bytes = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
        final_path = self._path(self._commit_ref(stream_record.song_id, stream_record.backbone, commit_sha))
        durable_write_if_absent(final_path, marker_bytes, ops)
        return ObservationCommit(
            song_id=stream_record.song_id,
            backbone=stream_record.backbone,
            stream_ref=stream_record.artifact_ref,
            mask_ref=mask_record.artifact_ref,
            commit_sha256=commit_sha,
            alignment_token=f"{stream_record.artifact_ref}:{mask_record.artifact_ref}",
            mask_semantics_version=mask_payload.mask_semantics_version,
            group_format_version="1",
            audio_content_sha256=mask_payload.audio_content_sha256,
            run_id=mask_payload.run_id,
            created_at=now,
            status="ready",
        )

    def _commit_documents(self, song_id: str, backbone: str) -> list[dict[str, object]]:
        """Every valid observation-commit marker on disk for ``(song_id, backbone)``.

        Walks only the ``observation_commits/`` digest grammar, validates each marker's
        commit digest (sha256 of content excluding its own ``commit_sha256`` field) and its
        logical cross-identity (marker song_id/backbone match the request).  Returns the
        parsed contents ordered newest-first by ``created_at``.  Invalid/mismatched markers
        are ignored (never a committed group).
        """
        from scripts.embedding_research.streams.publication import parse_artifact_name

        commit_dir = self._output_root / self._commit_subdir
        documents: list[dict[str, object]] = []
        if not commit_dir.is_dir():
            return documents
        for path in sorted(commit_dir.glob(f"{song_id}.{backbone}.*.json")):
            parsed = parse_artifact_name(path.name, ".json")
            if parsed is None or parsed.song_id != song_id or parsed.backbone != backbone:
                continue
            try:
                doc = read_json_manifest(path)
            except ValueError:
                continue
            if not self._commit_doc_ok(doc, parsed.digest):
                continue
            documents.append(doc)
        documents.sort(key=lambda d: int(d.get("created_at", 0) or 0), reverse=True)
        return documents

    def _commit_doc_ok(self, doc: dict[str, object], name_digest: str) -> bool:
        """Validate a parsed commit marker's digest identity + cross-identity refs."""
        recorded = doc.get("commit_sha256")
        if not isinstance(recorded, str) or recorded != name_digest:
            return False
        # Commit digest == sha256 of content excluding its own commit_sha256 field.
        probe = {k: v for k, v in doc.items() if k != "commit_sha256"}
        if (
            hashlib.sha256(json.dumps(probe, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            != recorded
        ):
            return False
        return doc.get("stream_ref") is not None and doc.get("mask_ref") is not None

    def observation_group_ready(
        self,
        song_id: str,
        backbone: str,
        *,
        stream_record: StreamRecord | None = None,
    ) -> bool:
        """True only when a COMPLETE committed observation group verifies (fail-closed).

        This is the SINGLE shared group-level READY predicate — the same one the current
        stream/mask resolvers and reindex use.  It delegates to the filesystem-authoritative
        :meth:`_resolve_committed_observation` core (the newest VALID committed group wins),
        so a group is READY only when a digest-grammar commit marker AND its referenced
        current-format stream/mask manifests AND both payloads (bytes/size/SHA-256/dtype/
        shape/finite + identity/alignment/audio-fingerprint/mask-semantics checks) all
        verify ON DISK.  A registry row claiming ``ready`` is cache metadata only and NEVER
        makes a group READY on its own.  Partial states — stream only; stream+mask with no
        commit marker; a commit referencing a missing/corrupt/wrong-length/wrong-digest
        stream or mask — are never ready.  When *stream_record* is given, the resolved
        committed group must be the exact one that record references.
        """
        observation = self._resolve_committed_observation(song_id, backbone)
        if observation is None:
            return False
        return not (stream_record is not None and observation.identity.stream_ref != stream_record.artifact_ref)

    def _mask_record_from_doc(self, doc: dict[str, object]) -> MaskRecord:
        """Rehydrate a :class:`MaskRecord` from a parsed commit's referenced mask manifest."""
        mask_ref = str(doc.get("mask_ref"))
        manifest = read_json_manifest(self._path(payload_to_manifest_ref(mask_ref)))
        return MaskRecord(
            song_id=str(doc.get("song_id")),
            backbone=str(doc.get("backbone")),
            artifact_ref=mask_ref,
            mask_sha256=str(manifest.get("payload_sha256")),
            patch_count=int(manifest.get("patch_count")),
            dimension=int(manifest.get("dimension", 1)),
            dtype=str(manifest.get("dtype", "uint8")),
            format_version=str(manifest.get("format_version", "1")),
            mask_semantics_version=str(manifest.get("mask_semantics_version", "1")),
            algorithm=str(manifest.get("algorithm", "")),
            threshold_dbfs=manifest.get("threshold_dbfs"),
            min_silent_run_frames=manifest.get("min_silent_run_frames"),
            hysteresis_frames=manifest.get("hysteresis_frames"),
            params_id=str(manifest.get("params_id", "")),
            audio_content_sha256=str(manifest.get("audio_content_sha256", "")),
            preprocess_fn=str(manifest.get("preprocess_fn", "")),
            preprocess_version=str(manifest.get("preprocess_version", "")),
            provenance_source=str(manifest.get("provenance_source", "mask")),
            run_id=str(manifest.get("run_id", "")),
            created_at=manifest.get("created_at"),
            status=str(manifest.get("status", "ready")),
        )

    def ready_stream_record(self, song_id: str, backbone: str) -> StreamRecord | None:
        """Return the ready stream record for ``(song_id, backbone)`` or ``None``.

        Registry read only — does not touch any mask/commit artifact.  ``None`` when no
        row exists or the row is not ``ready``.
        """
        try:
            row = _reg.select_row(self._con, self._table, self._columns, song_id, backbone)
        except (ValueError, TypeError):
            return None
        if row is None:
            return None
        try:
            record = self._record_cls.from_row(tuple(row))
        except (ValueError, TypeError):
            return None
        return record if record.status == "ready" else None

    def read_committed_mask_audio_fingerprint(self, song_id: str, backbone: str) -> str | None:
        """Return the committed group's ``audio_content_sha256`` for a ready stream+mask group.

        Used by ``embed --regenerate-masks``: the regeneration may proceed only when the
        freshly decoded audio fingerprint equals this committed value.  Returns ``None`` when
        no committed/ready observation group exists for ``(song_id, backbone)``.
        """
        for doc in self._commit_documents(song_id, backbone):
            mask_ref = doc.get("mask_ref")
            if not isinstance(mask_ref, str):
                continue
            try:
                manifest = read_json_manifest(self._path(payload_to_manifest_ref(mask_ref)))
            except ValueError:
                continue
            if manifest.get("payload_sha256") and self._mask_payload_ok(self._mask_record_from_doc(doc)):
                audio_fp = manifest.get("audio_content_sha256") or doc.get("audio_content_sha256")
                if isinstance(audio_fp, str) and len(audio_fp) == 64:
                    return audio_fp
        return None

    # ── committed-group filesystem-authoritative read seam (P1-S2) ────────────
    # The resolvers / catalog / head consumers must read a stream and its silence
    # mask ONLY as ONE complete committed observation group.  ``load_committed_observation``
    # is that filesystem-authoritative seam: it validates the newest valid commit marker
    # filename grammar + content digest, the referenced current-format stream/mask
    # manifests, the payload bytes/size/SHA-256/dtype/shape/finite values, stream-mask
    # patch-count equality, the alignment token, the audio fingerprint and mask semantics
    # version that the mask manifest and marker agree on, and only then returns BOTH
    # payloads plus the immutable group identity.  Absent or invalid groups raise a typed
    # fail-closed refusal (``StreamValidationError``) — never a partial stream/mask and
    # never silence-as-absence.  The private :meth:`_resolve_committed_observation` is the
    # shared group-resolution helper later steps (P1-S3 shared predicate, catalog/head
    # consumers) reuse.

    @staticmethod
    def _ref_digest(artifact_ref: str, suffix: str) -> str:
        """The 64-hex payload digest parsed from a digest-grammar artifact ref (or refuse)."""
        from scripts.embedding_research.streams.publication import parse_artifact_name

        parsed = parse_artifact_name(artifact_ref.rsplit("/", 1)[-1], suffix)
        if parsed is None:
            raise StreamValidationError(f"{artifact_ref!r} is not a current-format digest artifact; group refused")
        return parsed.digest

    def _load_stream_payload(self, stream_ref: str, patch_count: int, dim: int) -> np.ndarray:
        """Load + fully validate the committed stream payload bytes (sha/dtype/shape/finite)."""
        path = self._path(stream_ref)
        if not path.is_file():
            raise StreamValidationError(f"committed stream payload missing: {stream_ref!r}; group refused")
        digest = self._ref_digest(stream_ref, ".npy")
        if _sha256_hex(path) != digest:
            raise StreamValidationError(f"committed stream SHA-256 mismatch for {stream_ref!r}; group refused")
        try:
            arr = np.load(str(path), allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise StreamValidationError(
                f"committed stream payload unreadable {stream_ref!r}: {exc}; group refused"
            ) from exc
        if not isinstance(arr, np.ndarray) or arr.dtype != np.dtype(STREAM_DTYPE):
            raise StreamValidationError(f"committed stream {stream_ref!r} is not float32; group refused")
        if arr.shape != (patch_count, dim):
            raise StreamValidationError(
                f"committed stream {stream_ref!r} shape {arr.shape} != ({patch_count}, {dim}); group refused"
            )
        if not np.isfinite(arr).all():
            raise StreamValidationError(f"committed stream {stream_ref!r} contains non-finite values; group refused")
        return np.asarray(arr, dtype=np.float32)

    def _load_mask_payload(self, mask_ref: str, patch_count: int) -> np.ndarray:
        """Load + fully validate the committed mask payload bytes (sha/dtype/shape/values)."""
        path = self._path(mask_ref)
        if not path.is_file():
            raise StreamValidationError(f"committed mask payload missing: {mask_ref!r}; group refused")
        digest = self._ref_digest(mask_ref, ".npy")
        if _sha256_hex(path) != digest:
            raise StreamValidationError(f"committed mask SHA-256 mismatch for {mask_ref!r}; group refused")
        try:
            arr = np.load(str(path), allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise StreamValidationError(
                f"committed mask payload unreadable {mask_ref!r}: {exc}; group refused"
            ) from exc
        if not isinstance(arr, np.ndarray) or arr.dtype != np.dtype("uint8"):
            raise StreamValidationError(f"committed mask {mask_ref!r} is not uint8; group refused")
        if arr.shape != (patch_count,):
            raise StreamValidationError(
                f"committed mask {mask_ref!r} shape {arr.shape} != ({patch_count},); group refused"
            )
        if arr.size and not np.isin(arr, (0, 1)).all():
            raise StreamValidationError(f"committed mask {mask_ref!r} contains non-0/1 values; group refused")
        return np.asarray(arr, dtype=np.uint8)

    def _observation_from_marker(self, doc: dict[str, object], song_id: str, backbone: str) -> CommittedObservation:
        """Validate one commit marker + its referenced group and materialize, or refuse.

        Raises :class:`StreamValidationError` (a typed fail-closed refusal) when the
        marker's format/identity/digest/alignment/audio-fingerprint/semantics chain or any
        referenced manifest/payload fails; on success returns the materialized
        :class:`CommittedObservation`.  Called per candidate marker from
        :meth:`_resolve_committed_observation` so the NEWEST VALID marker wins.
        """
        if str(doc.get("song_id")) != song_id or str(doc.get("backbone")) != backbone:
            raise StreamValidationError(
                f"commit marker identity ({doc.get('song_id')!r}, {doc.get('backbone')!r}) "
                f"!= request ({song_id!r}, {backbone!r}); group refused"
            )
        if str(doc.get("group_format_version")) != "1":
            raise StreamValidationError(
                f"unsupported group_format_version {doc.get('group_format_version')!r}; group refused"
            )
        stream_ref = doc.get("stream_ref")
        mask_ref = doc.get("mask_ref")
        if not isinstance(stream_ref, str) or not isinstance(mask_ref, str):
            raise StreamValidationError("commit marker missing stream_ref/mask_ref; group refused")
        if doc.get("alignment_token") != f"{stream_ref}:{mask_ref}":
            raise StreamValidationError(
                "commit marker alignment_token does not bind the referenced stream+mask; group refused"
            )
        mask_semantics = doc.get("mask_semantics_version")
        if mask_semantics != "1":
            raise StreamValidationError(f"unsupported mask_semantics_version {mask_semantics!r}; group refused")
        marker_audio = doc.get("audio_content_sha256")
        if not isinstance(marker_audio, str) or len(marker_audio) != 64:
            raise StreamValidationError("commit marker audio_content_sha256 is not a 64-hex fingerprint; group refused")
        stream_digest = self._ref_digest(stream_ref, ".npy")
        mask_digest = self._ref_digest(mask_ref, ".npy")

        # Referenced current-format stream manifest identity + payload.
        try:
            stream_manifest = read_json_manifest(self._path(payload_to_manifest_ref(stream_ref)))
        except ValueError as exc:
            raise StreamValidationError(f"committed stream manifest unreadable: {exc}; group refused") from exc
        if not (
            stream_manifest.get("kind") == "stream"
            and stream_manifest.get("schema_version") == "1"
            and stream_manifest.get("payload_sha256") == stream_digest
            and stream_manifest.get("song_id") == song_id
            and stream_manifest.get("backbone") == backbone
        ):
            raise StreamValidationError(
                f"committed stream manifest does not self-describe {stream_ref!r}; group refused"
            )
        try:
            stream_patch_count = int(stream_manifest.get("patch_count"))
            stream_dim = int(stream_manifest.get("dim"))
        except (TypeError, ValueError) as exc:
            raise StreamValidationError("committed stream manifest missing patch_count/dim; group refused") from exc

        # Referenced current-format mask manifest identity + payload.
        try:
            mask_manifest = read_json_manifest(self._path(payload_to_manifest_ref(mask_ref)))
        except ValueError as exc:
            raise StreamValidationError(f"committed mask manifest unreadable: {exc}; group refused") from exc
        if not (
            mask_manifest.get("kind") == "mask"
            and mask_manifest.get("schema_version") == "1"
            and mask_manifest.get("payload_sha256") == mask_digest
            and mask_manifest.get("song_id") == song_id
            and mask_manifest.get("backbone") == backbone
        ):
            raise StreamValidationError(f"committed mask manifest does not self-describe {mask_ref!r}; group refused")
        mask_patch_count = int(mask_manifest.get("patch_count"))
        # Stream-mask patch-count equality (supplemental alignment, never proof).
        if mask_patch_count != stream_patch_count:
            raise StreamValidationError(
                f"committed mask patch_count {mask_patch_count} != stream patch_count "
                f"{stream_patch_count}; group refused"
            )
        # Audio fingerprint + mask semantics must agree between mask manifest and marker.
        mask_manifest_audio = mask_manifest.get("audio_content_sha256")
        if mask_manifest_audio != marker_audio:
            raise StreamValidationError(
                "committed mask audio fingerprint does not match the commit marker; group refused"
            )
        mask_manifest_semantics = mask_manifest.get("mask_semantics_version")
        if mask_manifest_semantics != mask_semantics:
            raise StreamValidationError(
                f"committed mask mask_semantics_version {mask_manifest_semantics!r} != commit "
                f"marker {mask_semantics!r}; group refused"
            )

        stream = self._load_stream_payload(stream_ref, stream_patch_count, stream_dim)
        mask = self._load_mask_payload(mask_ref, mask_patch_count)
        identity = ObservationGroupIdentity(
            song_id=song_id,
            backbone=backbone,
            stream_ref=stream_ref,
            stream_digest=stream_digest,
            mask_ref=mask_ref,
            mask_digest=mask_digest,
            alignment_token=f"{stream_ref}:{mask_ref}",
            patch_count=stream_patch_count,
            audio_content_sha256=str(marker_audio),
            mask_semantics_version=str(mask_semantics),
            group_format_version=str(doc.get("group_format_version")),
            commit_sha256=str(doc.get("commit_sha256")),
        )
        return CommittedObservation(identity=identity, stream=stream, mask=mask)

    def _resolve_committed_observation(self, song_id: str, backbone: str) -> CommittedObservation | None:
        """The newest VALID committed group for ``(song_id, backbone)``, or ``None``.

        Iterates the digest-grammar commit markers newest-first (each already validated
        for marker filename grammar + content digest by :meth:`_commit_documents`) and
        returns the first whose full stream+mask group verifies.  A corrupt newer group
        does not poison resolution of an older fully-valid group.  ``None`` when no marker
        yields a fully-valid group.
        """
        for doc in self._commit_documents(song_id, backbone):
            try:
                return self._observation_from_marker(doc, song_id, backbone)
            except (StreamValidationError, ValueError, TypeError, KeyError, OSError):
                continue
        return None

    def load_committed_observation(self, song_id: str, backbone: str) -> CommittedObservation:
        """Filesystem-authoritative read of the newest VALID committed observation group.

        Returns the materialized :class:`CommittedObservation` (immutable identity + both
        validated payloads) for ``(song_id, backbone)``, or raises the typed fail-closed
        refusal :class:`StreamValidationError` when no complete committed group exists
        (stream-only / uncommitted / corrupt / wrong-length / wrong-digest / identity,
        alignment, audio-fingerprint, mask-semantics, or format-version defect).  NEVER
        returns a partial stream/mask and never interprets mask absence as no silence.
        """
        observation = self._resolve_committed_observation(song_id, backbone)
        if observation is None:
            raise StreamValidationError(
                f"no valid committed observation group for ({song_id!r}, {backbone!r}): a "
                "complete committed stream+mask+identity group is required and absent, "
                "corrupt, uncommitted, or mismatched groups are refused"
            )
        return observation

    def load_committed_identity(self, song_id: str, backbone: str) -> ObservationGroupIdentity:
        """The immutable committed observation identity for ``(song_id, backbone)``.

        Returns the validated :class:`ObservationGroupIdentity` (refs + digests +
        patch-count/alignment + audio fingerprint + mask semantics + group format +
        commit identity) of the newest VALID committed group, raising the typed
        :class:`StreamValidationError` when no complete committed group exists.  This is
        the authoritative identity-only reader a catalog-binding seam uses to compare the
        CURRENT committed group against the evidence a compact catalog recorded at build
        time (Plan A observation binding) — same filesystem-authoritative core as
        :meth:`load_committed_observation`.
        """
        return self.load_committed_observation(song_id, backbone).identity


class HeadStreamStore(_RegistryStore):
    """Complete, patch-aligned per-song classifier-head streams as digest-named ``.npz`` payloads.

    Immutable artifact layout contract: a digest-named zip ``.npz`` under ``heads/`` holding
    one float32 ``[T, dim_head]`` array per head id key, with ``T == backbone patch_count``
    and each dim matching ``dim_by_head``, plus a self-describing ``.json`` manifest.
    ``batch_gather`` returns float32 ``[N, total_dim]`` with columns concatenated in
    canonical (sorted) head order, where ``N == len(source_patch_indices)``.
    """

    _table = HEAD_STREAM_TABLE
    _columns = HEAD_STREAM_REGISTRY_COLUMNS
    _record_cls = HeadStreamRecord
    _default_subdir = "heads"
    _suffix = ".npz"
    _manifest_kind = "head"

    def _payload_ok(self, path: Path, record: HeadStreamRecord) -> bool:
        if _sha256_hex(path) != record.fingerprint_sha256:
            return False
        try:
            npz = np.load(str(path), allow_pickle=False)
            return self._validate_layout(npz, record)
        except (OSError, ValueError, KeyError, StreamValidationError):
            return False

    @staticmethod
    def _validate_layout(npz, record: HeadStreamRecord) -> bool:
        """Check the npz carries one float32 ``[patch_count, dim]`` array per head id."""
        dims = parse_dim_by_head(record.dim_by_head)
        ids = parse_head_ids(record.head_ids)
        if set(npz.keys()) != set(ids):
            return False
        for head in ids:
            arr = npz[head]
            expected = (record.patch_count, dims[head])
            if not isinstance(arr, np.ndarray) or arr.dtype != np.dtype(STREAM_DTYPE):
                return False
            if arr.shape != expected:
                return False
        return True

    def batch_gather(
        self, song_id: str, backbone: str, source_patch_indices, *, forbid_duplicates: bool = False
    ) -> np.ndarray:
        """Return float32 ``[N, total_dim]`` head rows for the given source patch indices.

        Validates the ready record, the per-head ``[patch_count, dim]`` layout, finite
        values and in-range indices, then concatenates each head's selected rows in
        canonical head order so ``N`` always equals the number of requested indices.
        Duplicates are permitted by default; ``forbid_duplicates=True`` rejects repeated
        source indices for uniqueness-required gather contracts.
        """
        record = self.lookup(song_id, backbone)
        path = self._path(record.artifact_ref)
        if not path.is_file():
            raise StreamValidationError(f"{self._table} artifact missing: {record.artifact_ref}")
        if _sha256_hex(path) != record.fingerprint_sha256:
            raise StreamValidationError(
                f"SHA-256 mismatch for {record.artifact_ref} (expected {record.fingerprint_sha256[:12]}…)"
            )
        try:
            npz = np.load(str(path), allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise StreamValidationError(f"failed to load {record.artifact_ref}: {exc}") from exc
        if not self._validate_layout(npz, record):
            raise StreamValidationError(
                f"{record.artifact_ref} layout does not match registry (patch_count={record.patch_count}, "
                f"head_ids={record.head_ids}, dim_by_head={record.dim_by_head})"
            )
        ids = parse_head_ids(record.head_ids)
        idx = _to_index_array(source_patch_indices, record.patch_count)
        _reject_duplicate_indices(idx, forbid=forbid_duplicates)
        gathered: list[np.ndarray] = []
        for head in ids:
            arr = np.asarray(npz[head])
            if not np.isfinite(arr).all():
                raise StreamValidationError(f"{record.artifact_ref} head {head!r} contains non-finite values")
            gathered.append(np.asarray(arr[idx], dtype=np.float32))
        return np.concatenate(gathered, axis=1)

    # ── immutable head-suite publication ─────────────────────────────────────
    def publish(
        self,
        song_id: str,
        backbone: str,
        head_arrays,
        *,
        run_id: str,
        patch_count: int,
        alignment_version: str,
        expected_head_ids=None,
        format_version: str = "1",
        preprocess_fn: str = "",
        preprocess_version: str = "",
        backbone_model_hash: str = "",
        stream_ref: str = "",
        dataset: str = "",
        head_set_semantics_version: str = "1",
        file_ops: FileOps | None = None,
    ) -> HeadStreamRecord:
        """Durably publish ONE complete, patch-aligned per-song head suite and register it ``pending``.

        *head_arrays* maps every head id to its float32 ``[T, dim]`` activation array.
        *patch_count* is the backbone stream's registered patch count, and
        *expected_head_ids* is the set of CONFIGURED heads for the backbone.  Publication
        REFUSES (never truncates/pads/recover) when an expected head is missing, an
        unconfigured head is present, any head's temporal length differs from
        *patch_count*, or a head array is not finite float32.

        *stream_ref* is the root-relative artifact ref of the committed backbone stream this
        suite is aligned to (``streams/<sid>.<bb>.<64hex>.npy``); it is recorded in the
        manifest as stream-alignment provenance along with the parsed ``stream_digest``.
        *dataset* names the dataset the heads were inferred over and
        *head_set_semantics_version* names the head-set/semantics contract.  These three are
        MANIFEST-ONLY provenance (optional; defaults leave existing callers unchanged): they
        are not part of the retained ``HEAD_STREAM_REGISTRY_COLUMNS``/``HeadStreamRecord``
        contract.  The manifest additionally carries the derived ``head_count`` and the
        ``head_set_fingerprint`` (sha256 over the canonical head-set identity), so the head
        set is fully described by manifest data, never derived from the digest filename.

        The suite is serialized to ``.npz`` bytes, written to the immutable digest-named
        ``heads/<sid>.<backbone>.<sha256>.npz`` artifact (never replacing bytes at an
        existing digest) followed by its self-describing ``.json`` manifest, and the
        ``(song_id, backbone)`` head row is replaced with a ``pending`` record.  A third
        durable write publishes the filesystem-authoritative CURRENT head-suite marker at
        ``heads/current/<song_id>.<backbone>.json`` (via ``publish_current_marker_for_record``),
        atomically replacing any prior marker so this freshly committed suite supersedes
        older generations for the identity (immutable payload/manifest bytes are never
        touched).  The caller reconciles the phase to promote to ``ready``.
        """
        ops = file_ops if file_ops is not None else FileOps()
        arrays: dict[str, np.ndarray] = {str(name): arr for name, arr in dict(head_arrays).items()}
        if not arrays:
            raise StreamValidationError(f"head suite for ({song_id!r}, {backbone!r}) is empty; nothing to publish")

        expected = set(canonical_head_ids(expected_head_ids).split(",")) if expected_head_ids is not None else None
        if expected is not None:
            actual = set(arrays)
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            if missing or extra:
                detail = []
                if missing:
                    detail.append(f"missing head(s) {missing}")
                if extra:
                    detail.append(f"unexpected head(s) {extra}")
                raise StreamValidationError(
                    f"head suite for ({song_id!r}, {backbone!r}) incomplete: {', '.join(detail)}"
                )

        # Validate every produced head array: exactly [patch_count, dim], finite float32.
        dims: dict[str, int] = {}
        for head in sorted(arrays):
            arr = np.asarray(arrays[head])
            if arr.ndim != 2:
                raise StreamValidationError(f"head {head!r} must be 2-D [T, dim]; got shape {arr.shape}")
            if arr.shape[0] != patch_count:
                raise StreamValidationError(
                    f"head {head!r} temporal length {arr.shape[0]} != backbone patch_count {patch_count}; "
                    "misaligned head stream refused"
                )
            if arr.shape[1] < 1:
                raise StreamValidationError(
                    f"head {head!r} must have at least one class column; got dim {arr.shape[1]}"
                )
            if not np.isfinite(arr).all():
                raise StreamValidationError(f"head {head!r} contains non-finite values")
            dims[head] = int(arr.shape[1])

        head_ids = canonical_head_ids(arrays)
        dim_by_head = canonical_dim_by_head(dims)
        payload = npz_bytes(arrays)
        fingerprint = hashlib.sha256(payload).hexdigest()
        artifact_ref = self._digest_ref(song_id, backbone, fingerprint)
        final_path = self._path(artifact_ref)
        durable_write_if_absent(final_path, payload, ops)
        now = now_ms()
        record = HeadStreamRecord(
            song_id=song_id,
            backbone=backbone,
            artifact_ref=artifact_ref,
            patch_count=patch_count,
            head_ids=head_ids,
            dim_by_head=dim_by_head,
            format_version=format_version,
            fingerprint_sha256=fingerprint,
            preprocess_fn=preprocess_fn,
            preprocess_version=preprocess_version,
            backbone_model_hash=backbone_model_hash,
            alignment_version=alignment_version,
            status="pending",
            run_id=run_id,
            created_at=now,
            updated_at=now,
        )
        self._write_head_manifest(
            record,
            payload,
            ops,
            stream_ref=stream_ref,
            dataset=dataset,
            head_set_semantics_version=head_set_semantics_version,
        )
        # Publish the filesystem-authoritative CURRENT head-suite marker (Plan C P1-S4):
        # a freshly inferred/committed suite supersedes any prior marker for this
        # (song_id, backbone).  The marker is a fixed-path atomic replace under
        # heads/current/ (never the immutable payload/manifest bytes above).  Imported
        # lazily to keep the module import graph acyclic (heads_current imports store).
        from scripts.embedding_research.streams.heads_current import publish_current_marker_for_record

        publish_current_marker_for_record(
            self._output_root,
            record,
            stream_ref=stream_ref,
            stream_digest=self._stream_digest_from_ref(stream_ref),
            head_set_fingerprint=self._head_set_fingerprint(record),
            head_set_semantics_version=head_set_semantics_version,
            model_suite_fingerprint=backbone_model_hash,
            file_ops=ops,
        )
        return self.replace(record, status="pending")

    # ── head-set provenance / fingerprint manifest helpers (P1-S4) ────────────
    # Mirror the S3 ``_mask_manifest`` precedent: the head manifest adds MANIFEST-ONLY
    # provenance/fingerprint fields (stream alignment identity, dataset, semantics, head
    # count and head-set fingerprint) that are NOT part of the retained
    # ``HEAD_STREAM_REGISTRY_COLUMNS`` / ``HeadStreamRecord`` contract.  The manifest
    # stays digest-deterministic (no ``created_at``/``updated_at``), so identical
    # re-publishes produce identical manifest bytes and the first-committed manifest is
    # authoritative (content-addressed no-replace).

    @staticmethod
    def _head_set_fingerprint(record: HeadStreamRecord) -> str:
        """A deterministic fingerprint of the canonical head-set identity.

        sha256 over the canonical serialized ``head_ids`` + ``dim_by_head`` texts, so two
        equal head sets (the same complete canonical inventory) fingerprint identically.
        This is manifest data — head-set identity is never derived from the digest filename.
        """
        return hashlib.sha256(f"{record.head_ids}|{record.dim_by_head}".encode()).hexdigest()

    @staticmethod
    def _stream_digest_from_ref(stream_ref: str) -> str:
        """The 64-hex stream payload digest parsed from a root-relative stream ref.

        A committed stream ref is ``streams/<sid>.<bb>.<64hex>.npy``; the digest is its
        final name component.  An empty ref (no committed stream supplied) yields ``""``; a
        non-empty ref that is not a digest-grammar stream artifact is refused (never
        silently accepted).
        """
        if not stream_ref:
            return ""
        from scripts.embedding_research.streams.publication import parse_artifact_name

        parsed = parse_artifact_name(stream_ref.rsplit("/", 1)[-1], ".npy")
        if parsed is None:
            raise ValueError(f"stream_ref must be a digest-grammar stream artifact; got {stream_ref!r}")
        return parsed.digest

    def _head_manifest(
        self,
        record: HeadStreamRecord,
        *,
        byte_size: int,
        stream_ref: str = "",
        dataset: str = "",
        head_set_semantics_version: str = "1",
    ) -> dict[str, object]:
        """The self-describing head manifest (base row + head-set provenance fields)."""
        data = self._manifest(record, byte_size=byte_size)
        data["head_count"] = len(parse_head_ids(record.head_ids))
        data["head_set_fingerprint"] = self._head_set_fingerprint(record)
        data["stream_ref"] = stream_ref
        data["stream_digest"] = self._stream_digest_from_ref(stream_ref)
        data["dataset"] = dataset
        data["head_set_semantics_version"] = head_set_semantics_version
        return data

    def _write_head_manifest(
        self,
        record: HeadStreamRecord,
        payload: bytes,
        ops: FileOps,
        *,
        stream_ref: str = "",
        dataset: str = "",
        head_set_semantics_version: str = "1",
    ) -> None:
        """Durably write the head ``.json`` manifest (immutable, first-write no-replace)."""
        manifest_path = self._manifest_path(record)
        if manifest_path.is_file():
            return
        manifest = self._head_manifest(
            record,
            byte_size=len(payload),
            stream_ref=stream_ref,
            dataset=dataset,
            head_set_semantics_version=head_set_semantics_version,
        )
        write_json_durable(manifest_path, manifest, ops)


@runtime_checkable
class CurrentStreamResolver(Protocol):
    """Store-backed current-stream read seam (Plan B P1-S1).

    ``load(song_id, backbone)`` returns the validated current float32 ``[patch_count, dim]``
    patch matrix for one logical ``(song_id, backbone)`` group, or ``None`` when no current
    payload is available.  It NEVER returns a filesystem path, never reconstructs a bare or
    versioned name, never scans/adopts/rehashes old files, and fails closed (returns ``None``)
    for absent, non-``ready``, or corrupt current groups.  Runtime readers construct one from
    their already-available ``con`` via :func:`make_current_stream_resolver`; direct helper
    tests inject a fake resolver explicitly (including existing ``con=None`` calls).
    """

    def load(self, song_id: str, backbone: str) -> np.ndarray | None: ...


class _StoreBackedCurrentStreamResolver:
    """Store-backed current-stream resolver over COMPLETE COMMITTED observation groups.

    ``load`` resolves the stream through :meth:`StreamStore.load_committed_observation` —
    the SAME filesystem-authoritative complete-group core the current-mask resolver and
    reindex use.  The newest digest-grammar commit marker plus its referenced current-format
    stream and mask manifests and BOTH payloads (bytes/size/SHA-256/dtype/shape/finite,
    identity, alignment, audio-fingerprint, mask-semantics) must fully verify before the
    stream is returned.  A registry ``ready`` row is cache metadata only and can NEVER
    authorise a stream by itself — a stream-only or otherwise incomplete group fails closed
    to ``None``.  There is NO mask-less fallback and NO old-format fallback.
    """

    __slots__ = ("_store",)

    def __init__(self, store: StreamStore) -> None:
        self._store = store

    def load(self, song_id: str, backbone: str) -> np.ndarray | None:
        try:
            observation = self._store.load_committed_observation(song_id, backbone)
        except StreamStoreError:
            return None
        return observation.stream

    def committed_identity(self, song_id: str, backbone: str) -> ObservationGroupIdentity | None:
        """The validated committed-group identity, or ``None`` when no complete group exists.

        Lets the compact catalog producer record the exact committed observation-version
        evidence (refs/digests/patch-count/alignment/audio-fingerprint/mask-semantics/
        group-format/commit) it built over — the same filesystem-authoritative group its
        ``load`` array came from.
        """
        try:
            observation = self._store.load_committed_observation(song_id, backbone)
        except StreamStoreError:
            return None
        return observation.identity


def make_current_stream_resolver(store: StreamStore) -> CurrentStreamResolver:
    """Return the store-backed :class:`CurrentStreamResolver` for *store*.

    ``load`` resolves ONLY a complete committed observation group (stream + aligned mask +
    valid commit/identity marker, all identity/digest/alignment/audio-fingerprint/semantics
    checks passing); a registry ``ready`` row is cache metadata and never authorises a
    stream by itself.  Absent/incomplete/corrupt groups fail closed to ``None``.
    """
    return _StoreBackedCurrentStreamResolver(store)


def observation_group_ready(
    store: StreamStore,
    song_id: str,
    backbone: str,
    *,
    stream_record: StreamRecord | None = None,
) -> bool:
    """Module-level shared complete-group READY predicate (P1-S3).

    Exactly the same complete-group predicate the current stream/mask resolvers and reindex
    use: it delegates to :meth:`StreamStore.observation_group_ready` (which in turn
    delegates to the ``_resolve_committed_observation`` filesystem-authoritative core).
    ``store`` must be a :class:`StreamStore` bound to the output root whose filesystem group
    is being checked — the predicate MUST reach the filesystem group check, so it needs a
    store handle.  A registry row claiming ``ready`` never makes a group READY by itself.
    """
    return store.observation_group_ready(song_id, backbone, stream_record=stream_record)


@dataclass(frozen=True)
class CommittedObservation:
    """A fully-validated committed stream + aligned mask + immutable group identity.

    Returned by :meth:`StreamStore.load_committed_observation`.  Carries the immutable
    :class:`~scripts.embedding_research.streams.records.ObservationGroupIdentity` plus the
    validated payload arrays: ``stream`` is the float32 ``[patch_count, dim]`` embedding
    patch matrix and ``mask`` is the aligned ``uint8[patch_count]`` silence mask
    (``1`` = searchable, ``0`` = silent).  A :class:`CommittedObservation` is never partial:
    it is materialized only after the marker, both current-format manifests and both
    payload bytes/size/SHA-256/dtype/shape/finite/alignment/audio-fingerprint/semantics
    checks all pass.
    """

    identity: ObservationGroupIdentity
    stream: np.ndarray
    mask: np.ndarray

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ObservationGroupIdentity):
            raise TypeError("CommittedObservation.identity must be an ObservationGroupIdentity")


class _StoreBackedCurrentMaskResolver:
    """Store-backed committed current-mask resolver over the observation-commit group.

    ``load`` resolves the mask from the SAME complete committed group that authorises the
    stream (``StreamStore.load_committed_observation``), so the group identity is always
    verified before a mask is returned.  Absent and corrupt/invalid groups both fail
    closed to ``None`` (the typed group refusal from ``load_committed_observation`` is
    caught) — never an implicit all-searchable mask, never a partial mask.
    """

    __slots__ = ("_store",)

    def __init__(self, store: StreamStore) -> None:
        self._store = store

    def load(self, song_id: str, backbone: str) -> np.ndarray | None:
        try:
            observation = self._store.load_committed_observation(song_id, backbone)
        except StreamStoreError:
            return None
        return None if observation is None else observation.mask


def make_current_mask_resolver(store: StreamStore) -> CurrentMaskResolver:
    """Return the sole store-backed :class:`CurrentMaskResolver` for *store*.

    This is the only mask-read seam for catalog/head consumers — it exposes no
    filesystem-path API and resolves masks only from complete committed observation
    groups.
    """
    return _StoreBackedCurrentMaskResolver(store)
