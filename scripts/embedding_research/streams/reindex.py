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

from scripts.embedding_research.db import stream_registry as _reg
from scripts.embedding_research.streams.heads_current import (
    CURRENT_SUBDIR,
    resolve_current_head_suite,
)
from scripts.embedding_research.streams.publication import parse_artifact_name, read_json_manifest
from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    HEAD_STREAM_TABLE,
    STREAM_REGISTRY_COLUMNS,
    STREAM_TABLE,
    HeadSuiteCurrentError,
    ReindexReport,
    StreamRecord,
    now_ms,
    payload_to_manifest_ref,
)
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

__all__ = ["reconcile_current_manifests", "reindex"]

#: Catalog sub-directory / current-pointer names under the output root (Plan C grammar).
_CATALOGS_DIR = "catalogs"
_CATALOGS_CURRENT = "current.json"
_CORPUS_DIR = "corpus"
#: Fixed-path per-identity CURRENT head-suite marker suffix (Plan C P1-S4).
_HEAD_CURRENT_SUFFIX = ".json"


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
    """Rebuild stream_registry cache rows ONLY from complete committed observation groups.

    Readiness is defined IDENTICALLY to the rest of the system: a ``(song_id, backbone)``
    group is rebuilt ``ready`` only when the shared complete-group predicate
    :meth:`StreamStore.observation_group_ready` (delegating to the filesystem-authoritative
    ``_resolve_committed_observation`` core) verifies a committed stream + aligned silence
    mask + commit/identity group on disk — the SAME predicate the current stream/mask
    resolvers use.  A registry row's cached ``ready`` status is never consulted (the
    registries are cleared first); every row is re-derived from the filesystem alone.

    Partial states are refused and reported, never rebuilt ready and never read as
    no-silence: stream-only; stream+mask without a valid commit marker; or a commit whose
    referenced stream/mask manifest/payload is missing, corrupt, wrong-length,
    wrong-digest, identity/alignment/audio-fingerprint/mask-semantics mismatched or
    uncommitted.  Reindex NEVER rebuilds a ready row from a stream-only artifact.
    """
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
        # THE readiness decision: the shared complete-committed-group predicate (the same
        # filesystem-authoritative core the current stream/mask resolvers use).  A group is
        # rebuilt ready only when the committed mask and commit marker are present and
        # valid; missing/corrupt/wrong-length/wrong-digest/uncommitted masks fail closed.
        if not store.observation_group_ready(song_id, backbone):  # type: ignore[attr-defined]  # private StreamStore method accessed within the streams package
            issues.append(
                f"stream group ({song_id!r}, {backbone!r}): no complete committed observation "
                "group on disk — committed mask/stream payload missing, corrupt, wrong-length, "
                "wrong-digest, uncommitted, or identity/alignment/audio-fingerprint/"
                "mask-semantics/commit-marker defect; refused"
            )
            continue
        # Ready: rebuild the cache row from the validated committed group's own stream
        # manifest (its row pre-image).  The manifest must self-describe the exact committed
        # artifact the predicate resolved — reindex never writes a cache row whose pre-image
        # disagrees with the on-disk digest ref it was resolved from (a tampered
        # ``artifact_ref``/``fingerprint_sha256`` is refused, never written ready).
        obs = store.load_committed_observation(song_id, backbone)  # type: ignore[attr-defined]  # private StreamStore method accessed within the streams package
        manifest_path = store.output_root / payload_to_manifest_ref(obs.identity.stream_ref)
        try:
            manifest = read_json_manifest(manifest_path)
            record = _record_from_doc(StreamRecord, STREAM_REGISTRY_COLUMNS, manifest)
        except (ValueError, TypeError) as exc:
            issues.append(f"stream group ({song_id!r}, {backbone!r}): stream manifest invalid: {exc}; refused")
            continue
        if record.fingerprint_sha256 != obs.identity.stream_digest:
            issues.append(
                f"stream group ({song_id!r}, {backbone!r}): committed stream payload/manifest digest mismatch; refused"
            )
            continue
        if record.artifact_ref != obs.identity.stream_ref or record.song_id != song_id or record.backbone != backbone:
            issues.append(
                f"stream group ({song_id!r}, {backbone!r}): stream manifest does not "
                "self-describe the committed stream/mask group; refused"
            )
            continue
        record = _with_status(record, "ready")
        _reg.insert_row(store._con, STREAM_TABLE, STREAM_REGISTRY_COLUMNS, record.row_tuple())  # type: ignore[attr-defined]  # store._con is a private StreamStore attr accessed within the package
        ready += 1
        rebuilt += 1
    return scanned, ready, rebuilt


def _current_marker_identities(store: HeadStreamStore) -> set[tuple[str, str]]:
    """The ``(song_id, backbone)`` identities that HAVE a CURRENT head-suite marker.

    Marker files live at the fixed path ``heads/current/<song_id>.<backbone>.json`` (not a
    digest grammar name, so they are never parsed by ``parse_artifact_name`` and never
    collide with head manifests/payloads under ``heads/``).
    """
    identities: set[tuple[str, str]] = set()
    current_dir = store.output_root / CURRENT_SUBDIR
    if not current_dir.is_dir():
        return identities
    for path in current_dir.glob(f"*{_HEAD_CURRENT_SUFFIX}"):
        stem = path.name[: -len(_HEAD_CURRENT_SUFFIX)]
        parts = stem.split(".")
        if len(parts) == 2 and all(parts):
            identities.add((parts[0], parts[1]))
    return identities


def _head_manifests_without_marker(store: HeadStreamStore, marked: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Head identities whose current-format ``heads/*.json`` manifest has NO CURRENT marker.

    Such head suites were published before/detached from a CURRENT selection: they are
    superseded/unselected and reindex must never index them nor guess currency by mtime or
    lexical order.  They are reported as a refusal (never silently resolved).
    """
    present: set[tuple[str, str]] = set()
    head_dir = store.output_root / store._default_subdir  # type: ignore[attr-defined]  # private HeadStreamStore attr accessed within the streams package
    if head_dir.is_dir():
        for path in head_dir.glob("*.json"):
            parsed = parse_artifact_name(path.name, ".json")
            if parsed is not None:
                present.add((parsed.song_id, parsed.backbone))
    return present - marked


def _rebuild_head_registry(store: HeadStreamStore, issues: list[str]) -> tuple[int, int, int]:
    """Rebuild head_stream_registry cache rows from CURRENT marker-selected suites only.

    The ``heads/current/<song_id>.<backbone>.json`` CURRENT marker is the single
    filesystem-authoritative selection for which complete head suite is current: reindex
    NEVER guesses currency by mtime or lexical order and never picks among sibling head
    manifests.  Each marker identity is resolved through
    :func:`~scripts.embedding_research.streams.heads_current.resolve_current_head_suite`,
    which refuses a missing/malformed/stale/mismatched marker, a suite not aligned to the
    CURRENT committed stream, or a referenced head payload/manifest that is missing/
    corrupt/mismatched.  Head manifests present without a CURRENT marker are superseded and
    reported as a refusal (not indexed).  Returns ``(scanned, ready, rebuilt)``.
    """
    marked = _current_marker_identities(store)
    unmarked = _head_manifests_without_marker(store, marked)
    if unmarked:
        issues.append(
            f"{len(unmarked)} head manifest identity/identities with no CURRENT head-suite marker "
            "(superseded/unselected suite refused, not indexed)"
        )

    scanned = ready = rebuilt = 0
    root = store.output_root
    for song_id, backbone in sorted(marked):
        scanned += 1
        try:
            selection = resolve_current_head_suite(root, song_id, backbone)
        except HeadSuiteCurrentError as exc:
            issues.append(f"head ({song_id!r}, {backbone!r}): {exc}")
            continue
        record = _with_status(selection.record, "ready")
        _reg.insert_row(store._con, HEAD_STREAM_TABLE, HEAD_STREAM_REGISTRY_COLUMNS, record.row_tuple())  # type: ignore[attr-defined]  # store._con is a private HeadStreamStore attr accessed within the package
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
