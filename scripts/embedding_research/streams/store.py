"""StreamStore / HeadStreamStore — the only downstream boundary to frozen observation streams.

This is the "thin interface" seam from the DD (``scripts/embedding_research`` A-prime design):

* :meth:`StreamStore.lookup` / :meth:`HeadStreamStore.lookup` — validated scalar metadata
  for one logical ``(song_id, backbone)``; returns an immutable record carrying an OPAQUE
  root-relative ``artifact_ref``.  Non-``ready`` rows are refused (raised), and the ref is
  never a path identity / SQL key / external result ID.
* :meth:`StreamStore.batch_gather` / :meth:`HeadStreamStore.batch_gather` — the only
  vector-read path.  Loads the artifact with ``allow_pickle=False``, checks SHA-256,
  dtype (``float32``), shape and finite values, then performs vectorized row selection.
* :meth:`StreamStore.register` / ``replace`` — persist a completed durable payload as a
  registry row (``pending`` by default) with the app-level duplicate guard; ``replace``
  is the transactional delete-then-insert primitive Phase 2 publication uses to repoint
  a logical identity at a newer immutable artifact.
* :meth:`StreamStore.reconcile` — promote ``pending`` rows whose artifact validates to
  ``ready``, demote ``ready`` rows whose artifact degrades to ``missing``/``corrupt``,
  detect orphan final files, and return a :class:`ReconcileReport`.

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
from dataclasses import replace
from pathlib import Path

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT
from scripts.embedding_research.db import stream_registry as _reg
from scripts.embedding_research.streams.publication import (
    STAGING_DIRNAME,
    FileOps,
    durable_write,
    npy_bytes,
    npz_bytes,
    parse_artifact_name,
    staging_path_for,
)
from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    HEAD_STREAM_TABLE,
    STREAM_DTYPE,
    STREAM_REGISTRY_COLUMNS,
    STREAM_TABLE,
    DuplicateStreamError,
    HeadStreamRecord,
    ReconcileReport,
    StreamNotFoundError,
    StreamNotReadyError,
    StreamRecord,
    StreamValidationError,
    VerifyFailureError,
    canonical_dim_by_head,
    canonical_head_ids,
    now_ms,
    parse_dim_by_head,
    parse_head_ids,
    validate_status,
)

__all__ = ["HeadStreamStore", "StreamStore"]


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

    def __init__(self, con, *, output_root: str | Path | None = None, scan_root: str | Path | None = None) -> None:
        self._con = con
        self._output_root = Path(output_root) if output_root is not None else Path(OUTPUT_ROOT)
        if scan_root is not None:
            self._scan_root = Path(scan_root)
        else:
            self._scan_root = self._output_root / self._default_subdir

    # ── path resolution (never exposed to callers) ───────────────────────────
    def _path(self, artifact_ref: str) -> Path:
        return self._output_root / artifact_ref

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

        Transactional delete-then-insert (never leaves a duplicate row).  Phase 2
        publication uses this when a logical identity is re-embedded.
        """
        return self._register_impl(record, status=status, replace_existing=True)

    def has_ready(self, song_id: str, backbone: str) -> bool:
        """True when the identity already has a verified ``ready`` registry row.

        Phase 2 embed skip semantics depend on this: a song/backbone is skipped only
        when the registry already holds a ``ready`` record (not merely because a file
        exists) and ``force`` is False.
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

    # ── immutable supersession versioning (shared by both publish paths) ──────
    def _family_versions(self, song_id: str, backbone: str) -> set[int]:
        """All artifact versions that already exist for an identity (bare == version 1).

        Immutable supersession rule: a NEW versioned artifact is published whenever any
        prior bytes exist at that identity (registry row *or* on-disk family file), so
        re-publishing never overwrites old immutable bytes.  The canonical bare name is
        used only for the very first artifact at an identity.
        """
        versions: set[int] = set()
        if self._scan_root.is_dir():
            for candidate in self._scan_root.glob(f"*{self._suffix}"):
                if candidate.name.endswith(".tmp"):
                    continue
                parsed = parse_artifact_name(candidate.name, self._suffix)
                if parsed is None:
                    continue
                f_sid, f_backbone, version = parsed
                if f_sid == song_id and f_backbone == backbone:
                    versions.add(version if version is not None else 1)
        row = _reg.select_row(self._con, self._table, self._columns, song_id, backbone)
        if row is not None:
            parsed = parse_artifact_name(Path(self._record_cls.from_row(tuple(row)).artifact_ref).name, self._suffix)
            if parsed is not None:
                _sid, _backbone, version = parsed
                versions.add(version if version is not None else 1)
        return versions

    def _next_artifact_ref(self, song_id: str, backbone: str) -> str:
        """Root-relative artifact ref for the next publish of ``(song_id, backbone)``.

        Bare canonical name when no prior bytes exist; otherwise the next monotonic
        versioned name (``{sid}.{backbone}.v{N}``).  The identity-encoding prefix is
        preserved in every name so reconcile can map rowless files back to identities.
        """
        versions = self._family_versions(song_id, backbone)
        if not versions:
            name = f"{song_id}.{backbone}{self._suffix}"
        else:
            name = f"{song_id}.{backbone}.v{max(versions) + 1}{self._suffix}"
        return f"{self._default_subdir}/{name}"

    # ── reconciliation ───────────────────────────────────────────────────────
    def _artifact_ok(self, path: Path, record) -> bool:
        """Subclass check: does the on-disk artifact validate against *record*?"""
        raise NotImplementedError

    def _classify(self, record) -> str:
        path = self._path(record.artifact_ref)
        if not path.is_file():
            return "missing"
        try:
            return "ready" if self._artifact_ok(path, record) else "corrupt"
        except (OSError, ValueError, StreamValidationError):
            return "corrupt"

    def _rowless_files(self, referenced: set[Path]) -> list[Path]:
        """Final artifact files under the scan root not referenced by any registry row.

        Excludes ``.tmp`` files and anything under a ``.staging`` directory (both are
        file-level conditions, never registry states).  The returned files are then
        classified as superseded/legacy/stray by :meth:`_classify_rowless`.
        """
        if not self._scan_root.is_dir():
            return []
        referenced_real = {str(p.resolve()) for p in referenced}
        rowless: list[Path] = []
        for candidate in self._scan_root.rglob(f"*{self._suffix}"):
            if not candidate.is_file():
                continue
            if candidate.name.endswith(".tmp"):
                continue
            if STAGING_DIRNAME in candidate.parts:
                continue
            if str(candidate.resolve()) not in referenced_real:
                rowless.append(candidate)
        return sorted(rowless)

    def _classify_rowless(self, path: Path, identities: set[tuple[str, str]]) -> str:
        """Classify one rowless final artifact as ``superseded``/``legacy``/``stray``.

        * ``superseded`` — its logical ``(song_id, backbone)`` is registered and the
          registry points at a NEWER artifact (this file is the preserved old bytes).
        * ``legacy`` — a canonical bare-name pre-registry file whose identity has never
          been registered.  Reported; never silently assigned historical provenance.
        * ``stray`` — unparseable or an unowned versioned file (a genuine orphan).
        """
        parsed = parse_artifact_name(path.name, self._suffix)
        if parsed is None:
            return "stray"
        song_id, backbone, version = parsed
        if (song_id, backbone) in identities:
            return "superseded"
        if version is None:
            return "legacy"
        return "stray"

    def reconcile(self, *, strict: bool = False) -> ReconcileReport:
        """Reconcile registry rows against on-disk final artifacts and report state.

        Applies only DD-allowed transitions: ``pending`` rows whose artifact validates
        promote to ``ready``; any non-``pending`` row adopts its file-derived state
        (``ready`` stays ``ready``, a missing file becomes ``missing``, a corrupt file
        becomes ``corrupt``, and a recovered file returns the row to ``ready``).  A
        ``pending`` row whose artifact is absent/corrupt stays ``pending`` (pending only
        promotes) and is reported as an issue rather than forced into a forbidden state.

        Unreferenced final files are reported and split into ``superseded`` (expected
        archived old immutable bytes), ``legacy`` (never-registered bare pre-registry
        files) and ``stray`` (genuine unowned orphans); ``orphan`` is their sum.
        """
        rows = _reg.list_rows(self._con, self._table, self._columns)
        identities: set[tuple[str, str]] = set()
        final_statuses: dict[tuple[str, str], str] = {}
        pre_ready: set[tuple[str, str]] = set()
        referenced: set[Path] = set()
        issues: list[str] = []

        for row in rows:
            record = self._record_cls.from_row(tuple(row))
            identity = (record.song_id, record.backbone)
            identities.add(identity)
            if record.status == "ready":
                pre_ready.add(identity)
            referenced.add(self._path(record.artifact_ref))
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

        superseded = legacy = stray = 0
        for path in self._rowless_files(referenced):
            category = self._classify_rowless(path, identities)
            if category == "superseded":
                superseded += 1
            elif category == "legacy":
                legacy += 1
            else:
                stray += 1
        orphan = superseded + legacy + stray
        if orphan:
            issues.append(
                f"{orphan} unreferenced final file(s): superseded={superseded}, legacy={legacy}, stray={stray}"
            )

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
            orphan=orphan,
            superseded=superseded,
            legacy=legacy,
            stray=stray,
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
          ``ready`` (missing/corrupt/never-promoted pending) OR any rowless final file
          is classified ``legacy`` or ``stray``.  Preserved SUPERSEDED archived bytes
          are NOT a strict failure (they are the designed immutable-supersession
          archival outcome, removed only by an explicit archival-scope cleanup).

        A fully verified corpus returns the report (``report.ready == report.scanned``
        and no legacy/stray files) without raising.
        """
        report = self.reconcile(strict=strict)
        if strict and not self._strict_clean(report):
            problems = report.issues or ("no issues recorded",)
            raise VerifyFailureError(
                f"{type(self).__name__} strict verify failed for {self._table}: "
                f"ready={report.ready}/{report.scanned}, pending={report.pending}, "
                f"missing={report.missing}, corrupt={report.corrupt}, legacy={report.legacy}, "
                f"stray={report.stray}; {'; '.join(problems)}"
            )
        return report

    @staticmethod
    def _strict_clean(report: ReconcileReport) -> bool:
        """True when *report* supports a strict ``--verify`` complete-corpus claim.

        Every scanned registry row must be ``ready`` (no missing/corrupt/unpromoted
        pending) and no rowless final file may be a genuine ``legacy``/``stray``
        orphan.  ``superseded`` archived immutable bytes are expected and allowed.
        """
        return report.scanned >= 1 and report.ready == report.scanned and report.legacy == 0 and report.stray == 0


class StreamStore(_RegistryStore):
    """Frozen per-song float32 patch streams over ``.npy`` sidecars."""

    _table = STREAM_TABLE
    _columns = STREAM_REGISTRY_COLUMNS
    _record_cls = StreamRecord
    _default_subdir = "patches"
    _suffix = ".npy"

    def _artifact_ok(self, path: Path, record: StreamRecord) -> bool:
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

    # ── Phase 2/3: immutable staged publication / legacy registration ─────────
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
        """Durably publish one frozen stream and register it ``pending`` atomically.

        Serializes *embeddings* to float32 C-order ``.npy`` bytes, fsync/rename/fsync's
        them into an immutable (versioned-when-any-prior-bytes-exist) artifact, then in
        one transaction replaces the ``(song_id, backbone)`` registry row with a
        ``pending`` record carrying full provenance.  Returns that pending record; the
        caller reconciles the phase to promote to ``ready``.  A ``force`` re-embed thus
        never overwrites the old bytes — the old artifact is left for reconcile to
        classify as superseded/archival.
        """
        arr = np.ascontiguousarray(embeddings, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"embeddings must be 2-D [patch_count, dim]; got shape {arr.shape}")
        if arr.shape[0] < 1:
            raise ValueError("embeddings must contain at least one patch row")
        if not np.isfinite(arr).all():
            raise ValueError("embeddings contain non-finite values")
        payload = npy_bytes(arr)
        fingerprint = hashlib.sha256(payload).hexdigest()
        artifact_ref = self._next_artifact_ref(song_id, backbone)
        final_path = self._path(artifact_ref)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = staging_path_for(final_path)
        durable_write(tmp_path, final_path, payload, file_ops if file_ops is not None else FileOps())
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
        return self.replace(record, status="pending")

    def register_legacy(
        self,
        song_id: str,
        backbone: str,
        *,
        run_id: str,
        provenance_assumption: str,
        preprocess_fn: str = "",
        preprocess_version: str = "",
        backbone_model_hash: str = "",
        audio_params: str = "",
        embed_semantics_version: int = 1,
        format_version: str = "1",
    ) -> StreamRecord:
        """Explicitly register a legacy pre-registry sidecar without claiming completeness.

        Only the canonical bare-name artifact (``{sid}.{backbone}{suffix}``) with no row
        ever registered can be adopted this way.  It records ``provenance_source='legacy'``
        plus the caller-supplied explicit ``provenance_assumption`` caveat text and refuses
        to be called provenance-complete (a consumer reading the record sees the legacy
        provenance source).  The file must already exist and validate as float32.
        """
        if not provenance_assumption or not provenance_assumption.strip():
            raise ValueError("provenance_assumption is required for an explicit legacy registration")
        artifact_ref = f"{self._default_subdir}/{song_id}.{backbone}{self._suffix}"
        path = self._path(artifact_ref)
        if not path.is_file():
            raise StreamValidationError(f"legacy artifact missing: {artifact_ref}")
        if _reg.identity_exists(self._con, self._table, song_id, backbone):
            raise DuplicateStreamError(
                f"Cannot register ({song_id!r}, {backbone!r}) as legacy: a {self._table} row already exists"
            )
        fingerprint = _sha256_hex(path)
        try:
            arr = np.load(str(path), allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise StreamValidationError(f"failed to load legacy artifact {artifact_ref}: {exc}") from exc
        if not isinstance(arr, np.ndarray) or arr.ndim != 2:
            raise StreamValidationError(f"legacy artifact {artifact_ref} is not a 2-D array")
        arr = np.asarray(arr)
        if arr.dtype != np.dtype(STREAM_DTYPE):
            raise StreamValidationError(f"legacy artifact {artifact_ref} dtype {arr.dtype} != {STREAM_DTYPE}")
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
            provenance_source="legacy",
            provenance_assumption=provenance_assumption,
            status="ready",
            run_id=run_id,
            created_at=now,
            updated_at=now,
        )
        return self._register_impl(record, status="ready", replace_existing=False)

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


class HeadStreamStore(_RegistryStore):
    """Complete, patch-aligned per-song classifier-head streams over ``.npz`` sidecars.

    Phase-1 artifact layout contract (documented; the Phase-3 ``infer-heads`` writer must
    honour it): a zip ``.npz`` holding one float32 ``[T, dim_head]`` array per head id key,
    with ``T == backbone patch_count`` and each dim matching ``dim_by_head``.  ``batch_gather``
    returns float32 ``[N, total_dim]`` with columns concatenated in canonical (sorted) head
    order, where ``N == len(source_patch_indices)`` (complete and patch aligned).
    """

    _table = HEAD_STREAM_TABLE
    _columns = HEAD_STREAM_REGISTRY_COLUMNS
    _record_cls = HeadStreamRecord
    _default_subdir = "heads"
    _suffix = ".npz"

    def _artifact_ok(self, path: Path, record: HeadStreamRecord) -> bool:
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
        parse_dim_by_head(record.dim_by_head)
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

    # ── Phase 3: immutable head-suite publication (P3-S1/S2) ──────────────────
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
        file_ops: FileOps | None = None,
    ) -> HeadStreamRecord:
        """Durably publish ONE complete, patch-aligned per-song head suite and register it ``pending``.

        *head_arrays* maps every head id to its float32 ``[T, dim]`` activation array
        (the Phase-1 documented npz layout).  *patch_count* is the backbone stream's
        registered patch count, and *expected_head_ids* is the set of CONFIGURED heads
        for the backbone.  Publication REFUSES (P3-S2, never truncates/pads/recover) when:

        * an expected configured head is missing from *head_arrays* (or an unconfigured
          head is present) — a partial suite is never accepted;
        * any head's temporal length differs from *patch_count* (wrong ``T``);
        * any head's activation array is not finite float32.

        It then serializes the suite to ``.npz`` bytes, fsync/rename/fsync's it into an
        immutable (versioned-when-any-prior-bytes-exist) ``heads/`` artifact, computes its
        fingerprint and canonical ``head_ids``/``dim_by_head``, and in one transaction
        replaces the ``(song_id, backbone)`` head row with a ``pending`` record carrying
        the alignment/provenance fields.  The caller reconciles the phase to promote to
        ``ready``.  A force re-run thus never overwrites old head bytes — the prior
        artifact is left for reconcile to classify as superseded/archival.
        """
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
        artifact_ref = self._next_artifact_ref(song_id, backbone)
        final_path = self._path(artifact_ref)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = staging_path_for(final_path)
        durable_write(tmp_path, final_path, payload, file_ops if file_ops is not None else FileOps())
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
        return self.replace(record, status="pending")
