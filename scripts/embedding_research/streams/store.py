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
from dataclasses import replace
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT
from scripts.embedding_research.db import stream_registry as _reg
from scripts.embedding_research.streams.masks import (
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
    "CurrentStreamResolver",
    "HeadStreamStore",
    "StreamStore",
    "make_current_stream_resolver",
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
        """True only when the FULL observation group verifies: marker + stream + mask all valid.

        Registry-ready for an observation group requires the commit marker AND the referenced
        stream manifest+payload AND the referenced mask manifest+payload all to verify, with
        matching logical identity.  Partial states (stream only; stream+mask with no commit;
        a commit referencing a missing/corrupt stream or mask) are never ready.
        """
        for doc in self._commit_documents(song_id, backbone):
            if stream_record is not None and doc.get("stream_ref") != stream_record.artifact_ref:
                continue
            stream_ref = doc.get("stream_ref")
            mask_ref = doc.get("mask_ref")
            if not isinstance(stream_ref, str) or not isinstance(mask_ref, str):
                continue
            try:
                stream_record_obj = (
                    stream_record
                    if stream_record is not None
                    else self._record_cls.from_row(
                        tuple(_reg.select_row(self._con, self._table, self._columns, song_id, backbone))
                    )  # type: ignore[arg-type]  # row values come from untyped duckdb-backed registry select; cast at from_row boundary
                )
            except (TypeError, ValueError, StreamStoreError):
                continue
            if stream_record_obj is None or stream_record_obj.artifact_ref != stream_ref:
                continue
            try:
                mask_ok = self._mask_payload_ok(self._mask_record_from_doc(doc))
            except (ValueError, TypeError, OSError):
                mask_ok = False
            if not mask_ok:
                continue
            if not self._stream_group_ok(song_id, backbone, stream_ref):
                continue
            return True
        return False

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

    def _stream_group_ok(self, song_id: str, backbone: str, stream_ref: str) -> bool:
        """Does the referenced stream manifest + payload verify on disk (no registry read)?"""
        path = self._path(stream_ref)
        if not path.is_file():
            return False
        try:
            row = _reg.select_row(self._con, self._table, self._columns, song_id, backbone)
        except Exception:
            row = None
        try:
            if row is not None:
                record = self._record_cls.from_row(tuple(row))
                return record.artifact_ref == stream_ref and self._artifact_ok(path, record)
        except (ValueError, TypeError):
            return False
        # No registry row (e.g. DB-less check): validate the manifest + payload directly.
        try:
            manifest = read_json_manifest(self._path(payload_to_manifest_ref(stream_ref)))
        except ValueError:
            return False
        return bool(
            manifest.get("kind") == self._manifest_kind
            and manifest.get("song_id") == song_id
            and manifest.get("backbone") == backbone
        ) and _sha256_hex(path) == str(manifest.get("payload_sha256"))

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
        ``(song_id, backbone)`` head row is replaced with a ``pending`` record.  The caller
        reconciles the phase to promote to ``ready``.
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
    """Store-backed resolver over the CURRENT (pre-observation-commit) store surface.

    Resolution consumes the retained registry ``artifact_ref`` only as a cache/index lookup:
    ``StreamStore.lookup`` gates on a ``ready`` row, and ``StreamStore.batch_gather`` validates
    the on-disk payload (SHA-256, dtype, shape, finite values, ``allow_pickle=False``) before
    returning rows.  The whole-matrix read is expressed as a full source-index gather so every
    validation in the store surface runs; any store error fails closed to ``None``.  The
    resolver gates only on a ``ready`` registry row plus current manifest/payload validation
    through ``lookup``/``batch_gather`` — it does NOT check observation-commit groups.
    Observation-commit group authority is enforced by the ``observation_group_ready`` flow and
    by reindex, not by this resolver; production embed publishes the observation group before
    reconcile, so every production-ready row is group-committed.
    """

    __slots__ = ("_store",)

    def __init__(self, store: StreamStore) -> None:
        self._store = store

    def load(self, song_id: str, backbone: str) -> np.ndarray | None:
        try:
            record = self._store.lookup(song_id, backbone)
        except StreamStoreError:
            return None
        try:
            return self._store.batch_gather(song_id, backbone, range(record.patch_count))
        except StreamStoreError:
            return None


def make_current_stream_resolver(store: StreamStore) -> CurrentStreamResolver:
    """Return the transitional store-backed :class:`CurrentStreamResolver` for *store*."""
    return _StoreBackedCurrentStreamResolver(store)
