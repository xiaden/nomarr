"""Filesystem-authoritative ``heads/current/`` CURRENT head-suite marker owner (Plan C P1-S4).

Contract C requires a filesystem-authoritative CURRENT marker to select which complete
head suite (among possibly many immutable generations on disk for one logical
``(song_id, backbone)``) is the current one, with reindex and the current-head resolver
honouring ONLY the marker and NEVER guessing currency by mtime or lexical order.

This module owns that marker (the exact documented marker owner selected by the Plan C
implementation): one **fixed-path** marker per observation identity at
``heads/current/<song_id>.<backbone>.json`` — the head-suite analogue of the per-identity
observation-commit markers and of ``catalogs/current.json`` (a fixed path that is
atomically replaced on supersession rather than appended).  Each marker:

* is an immutable, self-validating :class:`~.records.HeadSuiteCurrentMarker` binding the
  selected head payload ref/digest, the committed stream ref/digest, the model-suite and
  head-set fingerprints/semantics, dimensions, the alignment token/version, a monotonic
  ``generation`` and a ``created_at`` timestamp;
* is published durably via the established staged-write / ``fsync`` / atomic-rename /
  ``fsync``-dir protocol (:func:`publication.durable_write`), atomically replacing the
  previous marker at the fixed path while NEVER touching immutable head payload bytes;
* is consumed by :func:`resolve_current_head_suite` and by ``reindex`` — a marker-selected
  suite is honoured only when it is a COMPLETE, validated suite aligned to the CURRENT
  committed stream (older valid suites are superseded and never selected).

This module is CPU-only / filesystem-only: it reads JSON markers/manifests and
``allow_pickle=False`` numpy head payloads and resolves committed-stream currency through
the same :class:`~.store.StreamStore` committed-group core the resolvers/reindex use.  It
never imports or touches audio/models/sessions/ONNX/CUDA.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path

from scripts.embedding_research.streams.publication import (
    FileOps,
    durable_write,
    parse_artifact_name,
    read_json_manifest,
    staging_path_for,
)
from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    HeadStreamRecord,
    HeadSuiteCurrentError,
    HeadSuiteCurrentMarker,
    HeadSuiteSelection,
    now_ms,
    payload_to_manifest_ref,
)
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

#: The heads/current directory under an output root (marker owner location).
CURRENT_SUBDIR = "heads/current"
#: Marker file suffix (fixed-path per identity, not a digest name).
MARKER_SUFFIX = ".json"
#: Marker schema/kind identity (matches :attr:`HeadSuiteCurrentMarker`).
MARKER_SCHEMA_VERSION = "1"
MARKER_KIND = "head-current"

__all__ = [
    "CURRENT_SUBDIR",
    "MARKER_KIND",
    "MARKER_SCHEMA_VERSION",
    "current_marker_path",
    "publish_current_marker_for_record",
    "publish_head_suite_current",
    "resolve_current_head_suite",
]


def current_marker_path(root: Path, song_id: str, backbone: str) -> Path:
    """The fixed-path CURRENT head-suite marker for ``(song_id, backbone)`` under *root*.

    ``heads/current/<song_id>.<backbone>.json`` — one authoritative mutable pointer per
    observation identity (song_id dot-free, backbone contains no dot), atomically replaced
    on supersession.  Path traversal is refused by the identity grammar checks.
    """
    if not song_id or "." in song_id or "/" in song_id or "\\" in song_id:
        raise ValueError(f"song_id must be a dot-free/slash-free token; got {song_id!r}")
    if not backbone or any(ch in backbone for ch in (".", "/", "\\")):
        raise ValueError(f"backbone must be a slash/dot-free token; got {backbone!r}")
    return Path(root) / CURRENT_SUBDIR / f"{song_id}.{backbone}{MARKER_SUFFIX}"


# ── marker JSON serialization (deterministic; immutable field set) ─────────────


def _marker_field_names() -> tuple[str, ...]:
    """The serialized marker field names (dataclass declaration order, deterministic)."""
    return tuple(f.name for f in fields(HeadSuiteCurrentMarker))


def marker_to_doc(marker: HeadSuiteCurrentMarker) -> dict[str, object]:
    """A deterministic JSON-safe document for a validated marker."""
    if not is_dataclass(marker) or not isinstance(marker, HeadSuiteCurrentMarker):
        raise TypeError("marker must be a HeadSuiteCurrentMarker")
    return {name: getattr(marker, name) for name in _marker_field_names()}


def marker_from_doc(doc: object) -> HeadSuiteCurrentMarker:
    """Rehydrate a :class:`HeadSuiteCurrentMarker` from a parsed JSON document (or refuse).

    Raises :class:`HeadSuiteCurrentError` when *doc* is not a plain object carrying exactly
    the current marker field vocabulary with valid types.
    """
    if not isinstance(doc, dict):
        raise HeadSuiteCurrentError("CURRENT head-suite marker must be a JSON object")
    unknown = sorted(set(doc) - set(_marker_field_names()))
    if unknown:
        raise HeadSuiteCurrentError(f"CURRENT marker carries unknown field(s): {unknown}")
    kwargs: dict[str, object] = {}
    for name in _marker_field_names():
        if name not in doc:
            raise HeadSuiteCurrentError(f"CURRENT marker is missing required field {name!r}")
        kwargs[name] = doc[name]
    try:
        return HeadSuiteCurrentMarker(**kwargs)
    except (TypeError, ValueError) as exc:
        raise HeadSuiteCurrentError(f"CURRENT marker is malformed: {exc}") from exc


def _publish_bytes(path: Path, doc: dict[str, object], ops: FileOps) -> None:
    """Atomically replace the CURRENT marker at the fixed *path* (staged durable write)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tmp_path = staging_path_for(path)
    durable_write(tmp_path, path, payload, ops)


def _next_generation(root: Path, song_id: str, backbone: str) -> int:
    """A monotonic per-identity marker generation (1 on first publish, else prior+1)."""
    path = current_marker_path(root, song_id, backbone)
    if not path.is_file():
        return 1
    try:
        doc = read_json_manifest(path)
    except ValueError:
        return 1
    generation = doc.get("generation")
    if isinstance(generation, int) and not isinstance(generation, bool) and generation >= 1:
        return generation + 1
    return 1


def publish_current_marker_for_record(
    root: Path,
    record: HeadStreamRecord,
    *,
    stream_ref: str = "",
    stream_digest: str = "",
    head_set_fingerprint: str,
    head_set_semantics_version: str = "1",
    model_suite_fingerprint: str = "",
    file_ops: FileOps | None = None,
) -> HeadSuiteCurrentMarker:
    """Build + durably publish the CURRENT marker for a freshly-published head suite.

    *record* is the just-published (pending) :class:`HeadStreamRecord` whose immutable
    payload + manifest are already durable.  The marker binds the record's artifact
    ref/digest/dimensions to the committed *stream_ref*/*stream_digest* alignment and the
    head-set/model-suite provenance, with a monotonic ``generation``.  The fixed-path
    marker is atomically replaced (older suites are superseded); immutable payload bytes
    are never touched.
    """
    ops = file_ops if file_ops is not None else FileOps()
    alignment_token = f"{stream_ref}:{record.artifact_ref}"
    marker = HeadSuiteCurrentMarker(
        song_id=record.song_id,
        backbone=record.backbone,
        head_payload_ref=record.artifact_ref,
        head_payload_sha256=record.fingerprint_sha256,
        stream_ref=stream_ref,
        stream_digest=stream_digest,
        model_suite_fingerprint=model_suite_fingerprint,
        head_set_fingerprint=head_set_fingerprint,
        head_set_semantics_version=head_set_semantics_version,
        alignment_token=alignment_token,
        alignment_version=record.alignment_version,
        head_ids=record.head_ids,
        dim_by_head=record.dim_by_head,
        patch_count=record.patch_count,
        generation=_next_generation(Path(root), record.song_id, record.backbone),
        created_at=now_ms(),
        marker_schema_version=MARKER_SCHEMA_VERSION,
        kind=MARKER_KIND,
    )
    publish_head_suite_current(root, marker, file_ops=ops)
    return marker


def publish_head_suite_current(root: Path, marker: HeadSuiteCurrentMarker, *, file_ops: FileOps | None = None) -> None:
    """Durably publish/replace the CURRENT head-suite marker for *marker* at *root*.

    Writes ``heads/current/<song_id>.<backbone>.json`` through the staged durable protocol
    (write-all bytes, ``fsync`` file, close, atomic rename, ``fsync`` dir), atomically
    replacing any prior marker.  Immutable head payload/manifest bytes are preserved.  The
    marker must be a valid :class:`HeadSuiteCurrentMarker` (self-validated at construction).
    """
    ops = file_ops if file_ops is not None else FileOps()
    path = current_marker_path(root, marker.song_id, marker.backbone)
    _publish_bytes(path, marker_to_doc(marker), ops)


# ── resolution / selection (marker-only, fail-closed) ──────────────────────────


def _current_committed_stream(root: Path, song_id: str, backbone: str) -> tuple[str, str] | None:
    """The CURRENT committed stream ``(stream_ref, stream_digest)`` for the identity.

    Resolves through the same filesystem-authoritative committed-observation core the
    stream/mask resolvers and reindex use (:meth:`StreamStore.load_committed_observation`
    — the newest VALID committed group).  ``None`` when no complete committed observation
    group exists on disk.
    """
    store = StreamStore(None, output_root=root)
    try:
        observation = store.load_committed_observation(song_id, backbone)
    except Exception:
        return None
    return observation.identity.stream_ref, observation.identity.stream_digest


def _rehydrate_record(root: Path, marker: HeadSuiteCurrentMarker) -> HeadStreamRecord:
    """Rehydrate the marker-referenced head suite record from its manifest (or refuse).

    Cross-checks the manifest's current-format identity, payload digest and logical
    identity against the marker before returning a validated :class:`HeadStreamRecord`.
    """
    manifest_path = Path(root) / payload_to_manifest_ref(marker.head_payload_ref)
    if not manifest_path.is_file():
        raise HeadSuiteCurrentError(
            f"head manifest missing for CURRENT marker-selected suite {marker.head_payload_ref!r}"
        )
    try:
        manifest = read_json_manifest(manifest_path)
    except ValueError as exc:
        raise HeadSuiteCurrentError(f"head manifest unreadable for CURRENT suite: {exc}") from exc
    if manifest.get("kind") != "head" or manifest.get("schema_version") != "1":
        raise HeadSuiteCurrentError(
            f"CURRENT marker-selected head manifest is not current-format "
            f"(kind={manifest.get('kind')!r}, schema_version={manifest.get('schema_version')!r})"
        )
    name_digest = parse_artifact_name(marker.head_payload_ref.rsplit("/", 1)[-1], ".npz")
    if name_digest is None or name_digest.digest != marker.head_payload_sha256:
        raise HeadSuiteCurrentError("CURRENT marker head_payload_ref is not digest-named to its bound digest")
    if (
        manifest.get("song_id") != marker.song_id
        or manifest.get("backbone") != marker.backbone
        or manifest.get("payload_sha256") != marker.head_payload_sha256
    ):
        raise HeadSuiteCurrentError("CURRENT marker-selected head manifest does not match the marker identity/digest")

    now = now_ms()
    values: list[object] = []
    for column in HEAD_STREAM_REGISTRY_COLUMNS:
        if column in ("created_at", "updated_at"):
            values.append(now)
        else:
            values.append(manifest.get(column))
    try:
        record = HeadStreamRecord.from_row(tuple(values))
    except (TypeError, ValueError, KeyError) as exc:
        raise HeadSuiteCurrentError(f"CURRENT marker-selected head manifest is invalid: {exc}") from exc

    # Cross-check the marker's bound identity/dimensions/alignment/fingerprints.
    if record.artifact_ref != marker.head_payload_ref:
        raise HeadSuiteCurrentError("CURRENT marker-selected head manifest ref disagrees with the marker")
    if record.patch_count != marker.patch_count:
        raise HeadSuiteCurrentError("CURRENT marker patch_count disagrees with the head manifest")
    if record.head_ids != marker.head_ids or record.dim_by_head != marker.dim_by_head:
        raise HeadSuiteCurrentError("CURRENT marker head set/dimensions disagree with the head manifest")
    if (
        str(manifest.get("stream_ref")) != marker.stream_ref
        or str(manifest.get("stream_digest")) != marker.stream_digest
    ):
        raise HeadSuiteCurrentError("CURRENT marker stream alignment disagrees with the head manifest")
    if str(manifest.get("head_set_semantics_version")) != marker.head_set_semantics_version:
        raise HeadSuiteCurrentError("CURRENT marker head-set semantics disagree with the head manifest")
    return record


def _head_payload_ok(root: Path, record: HeadStreamRecord) -> bool:
    """Digest + npz layout (head_ids/dim_by_head) + finite validation of a head payload.

    Delegates to the store's own current-format head payload validator
    (:meth:`HeadStreamStore._payload_ok`) so selection/reindex and the registry reconcile
    share ONE validator (no parallel duplicate machinery).
    """
    store = HeadStreamStore(None, output_root=root)
    return store._payload_ok(Path(root) / record.artifact_ref, record)


def resolve_current_head_suite(root: Path, song_id: str, backbone: str) -> HeadSuiteSelection:
    """Resolve the CURRENT complete head suite for ``(song_id, backbone)`` (fail-closed).

    Accepts ONLY the marker-selected complete suite aligned to the current committed
    stream: reads ``heads/current/<song_id>.<backbone>.json``, validates the marker, verifies
    the referenced head payload + manifest verify against the marker's bound identity/digest/
    dimensions/alignment, and requires the marker's bound stream to BE the current committed
    stream.  A missing, malformed, stale, or mismatched marker — or a marker that references a
    superseded (no-longer-current) committed stream — raises :class:`HeadSuiteCurrentError`;
    selection NEVER falls back to mtime/lexical ordering of sibling head artifacts.

    Returns a :class:`HeadSuiteSelection` carrying the validated marker + rehydrated
    :class:`HeadStreamRecord` + the current committed stream alignment.
    """
    root_path = Path(root)
    path = current_marker_path(root_path, song_id, backbone)
    if not path.is_file():
        raise HeadSuiteCurrentError(
            f"no CURRENT head-suite marker for ({song_id!r}, {backbone!r}); current head selection refused"
        )
    try:
        doc = read_json_manifest(path)
    except ValueError as exc:
        raise HeadSuiteCurrentError(
            f"CURRENT head-suite marker for ({song_id!r}, {backbone!r}) is malformed JSON: {exc}"
        ) from exc
    try:
        marker = marker_from_doc(doc)
    except HeadSuiteCurrentError as exc:
        raise HeadSuiteCurrentError(
            f"CURRENT head-suite marker for ({song_id!r}, {backbone!r}) refused: {exc}"
        ) from exc
    if marker.song_id != song_id or marker.backbone != backbone:
        raise HeadSuiteCurrentError(
            f"CURRENT head-suite marker identity ({marker.song_id!r}, {marker.backbone!r}) "
            f"!= request ({song_id!r}, {backbone!r}); refused"
        )

    # The suite is selected ONLY when aligned to the CURRENT committed stream.
    current = _current_committed_stream(root_path, song_id, backbone)
    if current is None:
        raise HeadSuiteCurrentError(
            f"CURRENT head-suite marker for ({song_id!r}, {backbone!r}) references no current "
            "committed stream group; suite superseded/unselected, selection refused"
        )
    committed_ref, committed_digest = current
    if committed_ref != marker.stream_ref or committed_digest != marker.stream_digest:
        raise HeadSuiteCurrentError(
            f"CURRENT head-suite marker for ({song_id!r}, {backbone!r}) references stream "
            f"{marker.stream_ref!r} which is no longer the current committed stream "
            f"({committed_ref!r}); suite superseded, selection refused"
        )

    record = _rehydrate_record(root_path, marker)
    if not _head_payload_ok(root_path, record):
        raise HeadSuiteCurrentError(
            f"CURRENT marker-selected head payload {record.artifact_ref!r} is missing/corrupt/"
            "mismatched; selection refused"
        )
    return HeadSuiteSelection(
        song_id=song_id,
        backbone=backbone,
        marker=marker,
        record=record,
        stream_ref=committed_ref,
        stream_digest=committed_digest,
    )
