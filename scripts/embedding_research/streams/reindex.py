"""Filesystem-authoritative reindex over current-format manifests (Plan B P1-S5).

Plan B makes the current digest-named filesystem manifests, payloads and
observation-commit markers authoritative; the ``stream_registry`` /
``head_stream_registry`` tables are deliberately retained ONLY as a rebuildable
index/cache for downstream C/E consumers.  :func:`reconcile_current_manifests`
and its public maintenance wrapper :func:`reindex` rebuild those registry rows
from the filesystem alone:

* **walk** the current-format digest manifests under ``streams/``, ``heads/``,
  ``audio_masks/`` and the ``observation_commits/`` markers (plus optional
  ``corpus/`` and ``catalogs/`` current manifests when present);
* **validate** current refs, digests, shapes, finite values, stream/mask
  alignment and observation-commit readiness, and catalog close/WAL state;
* **rebuild** the retained registry index/cache rows after a DB deletion.

Refused without any fallback: corrupt / incomplete / mismatched /
WAL-bearing state, plus anything that would need old-format parsing, audio,
models, sessions, ONNX/CUDA, path-derived IDs or segmentation recomputation.
This module never imports or touches those surfaces — it reads JSON manifests
and ``allow_pickle=False`` numpy payloads only, and it never reconstructs a
bare/``.vN`` name from a filename.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from scripts.embedding_research.db import stream_registry as _reg
from scripts.embedding_research.streams.publication import (
    _file_sha256_hex,
    parse_artifact_name,
    read_json_manifest,
)
from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    HEAD_STREAM_TABLE,
    STREAM_DTYPE,
    STREAM_REGISTRY_COLUMNS,
    STREAM_TABLE,
    HeadStreamRecord,
    ReindexReport,
    StreamRecord,
    now_ms,
    parse_dim_by_head,
    parse_head_ids,
    payload_to_manifest_ref,
)
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

__all__ = ["reconcile_current_manifests", "reindex"]

#: Catalog sub-directory / current-pointer names under the output root (Plan C grammar).
_CATALOGS_DIR = "catalogs"
_CATALOGS_CURRENT = "current.json"
_CORPUS_DIR = "corpus"


def _record_from_doc(record_cls, columns: tuple[str, ...], doc: dict[str, object]):
    """Rehydrate a frozen registry record from a self-describing manifest doc.

    The manifest stores every registry column except ``created_at`` /
    ``updated_at`` (deliberately excluded at publish so a reindex regenerates
    them as publish-time cache-row bookkeeping).  Returns a validated record
    whose timestamps are ``now_ms()``.
    """
    now = now_ms()
    values: list[object] = []
    for column in columns:
        if column in ("created_at", "updated_at"):
            values.append(now)
        else:
            values.append(doc.get(column))
    return record_cls.from_row(tuple(values))


def _stream_payload_ok(path: Path, record) -> bool:
    """Digest + dtype + shape + finite validation of a float32 stream payload."""
    if not path.is_file():
        return False
    if _file_sha256_hex(path) != record.fingerprint_sha256:
        return False
    try:
        arr = np.load(str(path), allow_pickle=False)
    except (OSError, ValueError):
        return False
    return bool(
        isinstance(arr, np.ndarray)
        and arr.dtype == np.dtype(STREAM_DTYPE)
        and arr.shape == (record.patch_count, record.dim)
        and np.isfinite(arr).all()
    )


def _head_payload_ok(path: Path, record) -> bool:
    """Digest + npz layout (head_ids/dim_by_head) + finite validation of a head payload."""
    if not path.is_file():
        return False
    if _file_sha256_hex(path) != record.fingerprint_sha256:
        return False
    try:
        npz = np.load(str(path), allow_pickle=False)
        dims = parse_dim_by_head(record.dim_by_head)
        ids = parse_head_ids(record.head_ids)
    except (OSError, ValueError, KeyError):
        return False
    if set(npz.keys()) != set(ids):
        return False
    for head in ids:
        arr = npz[head]
        expected = (record.patch_count, dims[head])
        if not isinstance(arr, np.ndarray) or arr.dtype != np.dtype(STREAM_DTYPE):
            return False
        if arr.shape != expected or not bool(np.isfinite(arr).all()):
            return False
    return True


def _digest_subdir_payloads(root: Path, subdir: str, suffix: str) -> list[Path]:
    """Sorted digest-grammar payload files under ``<root>/<subdir>`` with a sibling manifest."""
    payload_dir = root / subdir
    out: list[Path] = []
    if not payload_dir.is_dir():
        return out
    for path in sorted(payload_dir.glob(f"*{suffix}")):
        if parse_artifact_name(path.name, suffix) is None:
            continue  # not a current-format digest payload — never interpreted here
        sibling = path.with_suffix(".json")
        if not sibling.is_file():
            out.append(path)  # orphan: digest payload with no manifest sibling
    return out


def _scan_corpus_state(root: Path) -> list[str]:
    """Validate optional current-format ``corpus/`` manifests when present.

    ``corpus/manifest.json`` / ``corpus/songs.json`` are Plan C-owned producers;
    when absent reindex succeeds untouched (a fresh or not-yet-ingested root is
    valid).  When present they must at least parse as JSON objects — malformed
    corpus manifests are refused (never silently ignored).
    """
    issues: list[str] = []
    corpus_dir = root / _CORPUS_DIR
    if not corpus_dir.is_dir():
        return issues
    for name in ("manifest.json", "songs.json"):
        path = corpus_dir / name
        if not path.is_file():
            continue
        try:
            doc = read_json_manifest(path)
        except ValueError as exc:
            issues.append(f"corpus/{name} refused: {exc}")
            continue
        if not isinstance(doc, dict) and name != "songs.json":
            issues.append(f"corpus/{name} must be a JSON object")
    return issues


def _scan_catalog_state(root: Path) -> list[str]:
    """Validate optional current-format ``catalogs/`` state (Plan C grammar).

    Reindex never builds or deletes catalog artifacts.  When no corrected-grammar
    catalog exists yet this returns no issues (absence is not a failure).  When a
    current pointer exists it must resolve to a current-format catalog whose
    clean ``catalog.duckdb`` is present and NOT WAL-bearing.
    """
    issues: list[str] = []
    catalogs_dir = root / _CATALOGS_DIR
    if not catalogs_dir.is_dir():
        return issues
    current_path = catalogs_dir / _CATALOGS_CURRENT
    if not current_path.is_file():
        return issues
    try:
        current = read_json_manifest(current_path)
    except ValueError as exc:
        issues.append(f"catalogs/current.json refused: {exc}")
        return issues
    catalog_id = current.get("catalog_id")
    if not isinstance(catalog_id, str) or not catalog_id or "/" in catalog_id or catalog_id in (".", ".."):
        issues.append(f"catalogs/current.json must carry a bare current catalog_id; got {catalog_id!r}")
        return issues
    cat_dir = catalogs_dir / catalog_id
    manifest_path = cat_dir / "catalog.manifest.json"
    db_path = cat_dir / "catalog.duckdb"
    if not manifest_path.is_file() or not db_path.is_file():
        issues.append(
            f"catalog {catalog_id!r} is incomplete: manifest={manifest_path.is_file()} duckdb={db_path.is_file()}"
        )
        return issues
    try:
        manifest = read_json_manifest(manifest_path)
    except ValueError as exc:
        issues.append(f"catalog {catalog_id!r} manifest refused: {exc}")
        return issues
    if manifest.get("kind") != "catalog" or str(manifest.get("schema_version")) != "1":
        issues.append(f"catalog {catalog_id!r} manifest is not current-format (kind/schema_version)")
    wal_path = Path(str(db_path) + ".wal")
    if wal_path.is_file():
        issues.append(f"catalog {catalog_id!r} is WAL-bearing (catalog.duckdb.wal present); refused")
    return issues


def _clear_registries(con) -> None:
    """Drop every retained registry cache row so reindex reflects current FS truth."""
    con.execute(f"DELETE FROM {STREAM_TABLE}")
    con.execute(f"DELETE FROM {HEAD_STREAM_TABLE}")


def _rebuild_stream_registry(store: StreamStore, issues: list[str]) -> tuple[int, int, int]:
    """Rebuild stream_registry from committed observation groups; returns (scanned, ready, rebuilt)."""
    scanned = ready = rebuilt = 0
    commit_dir = store.output_root / store._commit_subdir  # type: ignore[attr-defined]  # private StreamStore attr accessed within the streams package
    identities: set[tuple[str, str]] = set()
    if commit_dir.is_dir():
        for path in commit_dir.glob("*.json"):
            parsed = parse_artifact_name(path.name, ".json")
            if parsed is not None:
                identities.add((parsed.song_id, parsed.backbone))

    stream_dir = store.output_root / store._default_subdir  # type: ignore[attr-defined]  # private StreamStore attr accessed within the streams package
    uncommitted = 0
    if stream_dir.is_dir():
        for path in stream_dir.glob("*.json"):
            parsed = parse_artifact_name(path.name, ".json")
            if parsed is not None and (parsed.song_id, parsed.backbone) not in identities:
                uncommitted += 1
    if uncommitted:
        issues.append(
            f"{uncommitted} current stream manifest(s) without a valid observation-commit marker "
            "(partial/uncommitted group refused)"
        )

    for song_id, backbone in sorted(identities):
        scanned += 1
        docs = store._commit_documents(song_id, backbone)  # type: ignore[attr-defined]  # private StreamStore method accessed within the streams package
        if not docs:
            issues.append(f"stream group ({song_id!r}, {backbone!r}): no valid commit marker; refused")
            continue
        doc = docs[0]  # newest-first -> current committed group
        stream_ref = doc.get("stream_ref")
        mask_ref = doc.get("mask_ref")
        if not isinstance(stream_ref, str) or not isinstance(mask_ref, str):
            issues.append(f"stream group ({song_id!r}, {backbone!r}): commit refs malformed; refused")
            continue
        if not (
            stream_ref.startswith(f"{store._default_subdir}/")  # type: ignore[attr-defined]  # private StreamStore attr accessed within the streams package
            and mask_ref.startswith(f"{store._mask_subdir}/")
        ):  # type: ignore[attr-defined]  # store._mask_subdir is a private StreamStore attr within the package
            issues.append(f"stream group ({song_id!r}, {backbone!r}): non-current refs; refused")
            continue
        # Reconstruct the stream record from its self-describing manifest.
        manifest_path = store.output_root / payload_to_manifest_ref(stream_ref)
        if not manifest_path.is_file():
            issues.append(f"stream group ({song_id!r}, {backbone!r}): stream manifest missing; refused")
            continue
        try:
            manifest = read_json_manifest(manifest_path)
            record = _record_from_doc(StreamRecord, STREAM_REGISTRY_COLUMNS, manifest)
        except (ValueError, TypeError) as exc:
            issues.append(f"stream group ({song_id!r}, {backbone!r}): stream manifest invalid: {exc}")
            continue
        if (
            manifest.get("kind") != "stream"
            or manifest.get("schema_version") != "1"
            or record.song_id != song_id
            or record.backbone != backbone
            or record.artifact_ref != stream_ref
        ):
            issues.append(f"stream group ({song_id!r}, {backbone!r}): manifest/commit mismatch; refused")
            continue
        # Stream payload: digest + shape + dtype + finite.
        payload_path = store.output_root / stream_ref
        if not _stream_payload_ok(payload_path, record):
            issues.append(f"stream group ({song_id!r}, {backbone!r}): stream payload corrupt/mismatched; refused")
            continue
        # Mask referenced by the commit: digest + uint8[pc] + identity/alignment.
        try:
            mask_record = store._mask_record_from_doc(doc)  # type: ignore[attr-defined]  # private StreamStore method accessed within the streams package
            mask_ok = store._mask_payload_ok(mask_record)  # type: ignore[attr-defined]  # private StreamStore method accessed within the streams package
        except (ValueError, TypeError, OSError):
            mask_ok = False
        if not mask_ok:
            issues.append(f"stream group ({song_id!r}, {backbone!r}): committed mask corrupt/missing; refused")
            continue
        if (
            mask_record.song_id != song_id
            or mask_record.backbone != backbone
            or mask_record.patch_count != record.patch_count
        ):
            issues.append(f"stream group ({song_id!r}, {backbone!r}): stream/mask alignment mismatch; refused")
            continue
        record = _with_status(record, "ready")
        _reg.insert_row(store._con, STREAM_TABLE, STREAM_REGISTRY_COLUMNS, record.row_tuple())  # type: ignore[attr-defined]  # store._con is a private StreamStore attr accessed within the package
        ready += 1
        rebuilt += 1
    return scanned, ready, rebuilt


def _rebuild_head_registry(store: HeadStreamStore, issues: list[str]) -> tuple[int, int, int]:
    """Rebuild head_stream_registry from current head manifests; returns (scanned, ready, rebuilt)."""
    scanned = ready = rebuilt = 0
    head_dir = store.output_root / store._default_subdir  # type: ignore[attr-defined]  # private HeadStreamStore attr accessed within the streams package
    manifests_by_id: dict[tuple[str, str], list[Path]] = {}
    if head_dir.is_dir():
        for path in sorted(head_dir.glob("*.json")):
            parsed = parse_artifact_name(path.name, ".json")
            if parsed is not None:
                manifests_by_id.setdefault((parsed.song_id, parsed.backbone), []).append(path)

    for identity, paths in sorted(manifests_by_id.items()):
        scanned += 1
        song_id, backbone = identity
        if len(paths) != 1:
            issues.append(
                f"head identity ({song_id!r}, {backbone!r}): {len(paths)} current head manifests — "
                "ambiguous current artifact without a marker; refused"
            )
            continue
        manifest_path = paths[0]
        try:
            manifest = read_json_manifest(manifest_path)
            record = _record_from_doc(HeadStreamRecord, HEAD_STREAM_REGISTRY_COLUMNS, manifest)
        except (ValueError, TypeError) as exc:
            issues.append(f"head ({song_id!r}, {backbone!r}): manifest invalid: {exc}")
            continue
        if (
            manifest.get("kind") != "head"
            or manifest.get("schema_version") != "1"
            or record.song_id != song_id
            or record.backbone != backbone
        ):
            issues.append(f"head ({song_id!r}, {backbone!r}): manifest mismatch; refused")
            continue
        if not _head_payload_ok(store.output_root / record.artifact_ref, record):
            issues.append(f"head ({song_id!r}, {backbone!r}): payload corrupt/mismatched; refused")
            continue
        record = _with_status(record, "ready")
        _reg.insert_row(store._con, HEAD_STREAM_TABLE, HEAD_STREAM_REGISTRY_COLUMNS, record.row_tuple())  # type: ignore[attr-defined]  # store._con is a private StreamStore attr accessed within the package
        ready += 1
        rebuilt += 1
    return scanned, ready, rebuilt


def reconcile_current_manifests(root: Path, con) -> ReindexReport:
    """Filesystem-only consistency/rebuild walk over current manifests (Plan B P1-S5).

    Walks current-format digest manifests + observation-commit markers under
    *root* and rebuilds the retained ``stream_registry`` / ``head_stream_registry``
    cache/index rows from them.  Validates current refs, digests, shapes, finite
    values, stream/mask alignment, observation-commit readiness and optional
    catalog WAL state.  Refuses corrupt / incomplete / mismatched / WAL-bearing
    state without old-format parsing, audio, models, sessions, ONNX/CUDA,
    path-derived IDs or segmentation recomputation.  Never opens audio/models.

    Args:
        root: the OUTPUT_ROOT whose ``streams/``, ``heads/``, ``audio_masks/``,
            ``observation_commits/`` (and optional ``corpus/``, ``catalogs/``)
            current manifests are walked.
        con: an open DuckDB connection with the schema applied.

    Returns:
        :class:`ReindexReport` describing the walk.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"reindex root is not a directory: {root_path}")

    issues: list[str] = []
    orphan: list[str] = []
    issues.extend(_scan_corpus_state(root_path))
    issues.extend(_scan_catalog_state(root_path))

    stream_store = StreamStore(con, output_root=root_path)
    head_store = HeadStreamStore(con, output_root=root_path)

    # orphan payloads (digest payload whose sibling current manifest is missing)
    orphan.extend(_digest_subdir_payloads(root_path, stream_store._default_subdir, stream_store._suffix))  # type: ignore[attr-defined]  # private StreamStore attrs accessed within the package
    orphan.extend(_digest_subdir_payloads(root_path, head_store._default_subdir, head_store._suffix))  # type: ignore[attr-defined]  # private HeadStreamStore attrs accessed within the package
    orphan.extend(_digest_subdir_payloads(root_path, stream_store._mask_subdir, ".npy"))  # type: ignore[attr-defined]  # private StreamStore attr accessed within the package

    _clear_registries(con)

    scanned = ready = rebuilt = 0
    s_scanned, s_ready, s_rebuilt = _rebuild_stream_registry(stream_store, issues)
    h_scanned, h_ready, h_rebuilt = _rebuild_head_registry(head_store, issues)
    scanned += s_scanned + h_scanned
    ready += s_ready + h_ready
    rebuilt += s_rebuilt + h_rebuilt

    return ReindexReport(
        scanned=scanned,
        rows_rebuilt=rebuilt,
        ready=ready,
        orphan_payloads=len(orphan),
        issues=tuple(issues),
    )


def reindex(root: Path, con) -> ReindexReport:
    """Public maintenance reindex: a thin wrapper over :func:`reconcile_current_manifests`.

    Idempotent and safe to call on a freshly recreated (post-deletion) database.
    """
    return reconcile_current_manifests(root, con)


def _with_status(record, status: str):
    """Return a copy of *record* with the status replaced (ready)."""
    from dataclasses import replace

    return replace(record, status=status)
