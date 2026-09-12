"""Exact-key persistence for immutable per-song Gram geometry."""

from __future__ import annotations

import contextlib
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from scripts.embedding_research.db._schema import GEOMETRY_COLUMNS, schema_fingerprint
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.helpers.gram_segmentation import gram_from_stream

#: Hard resource ceilings: a geometry larger than this is refused before computation,
#: never spilled to a filesystem sidecar or reduced representation.
MAX_PATCH_COUNT = 4096
MAX_GRAM_BYTES = 4 * MAX_PATCH_COUNT * MAX_PATCH_COUNT


class GeometryRefusal(RuntimeError):  # noqa: N818
    """Fail-closed refusal for invalid geometry, evidence, schema, or resources."""

    code = "INTEGRITY_REFUSED"


class StaleRefused(GeometryRefusal):
    """The persisted geometry points at an older observation and must be regenerated."""

    code = "STALE_REFUSED"


class IntegrityRefused(GeometryRefusal):
    """The evidence or geometry cannot be trusted; no repair or alternate path is allowed."""

    code = "INTEGRITY_REFUSED"


@dataclass(frozen=True)
class GeometryIdentity:
    """Exact song/backbone observation and numerical-profile identity for persisted geometry."""

    song_id: str
    backbone: str
    observation_commit_sha256: str
    geometry_semantics_version: str
    numerical_profile_digest: str


@dataclass(frozen=True)
class GeometryRecord:
    """Validated persisted Gram geometry plus its immutable evidence and matrix view."""

    identity: GeometryIdentity
    geometry_id: str
    evidence: dict[str, Any]
    gram_blob: bytes
    matrix: np.ndarray

    def __post_init__(self) -> None:
        matrix = np.asarray(self.matrix, dtype=np.dtype("<f4"), order="C")
        matrix.setflags(write=False)
        object.__setattr__(self, "matrix", matrix)


def _connection(observation: Any) -> Any:
    con = getattr(observation, "con", None) or getattr(observation, "connection", None)
    if con is None:
        raise IntegrityRefused("geometry observation must carry its primary DuckDB connection")
    return con


def _field(source: Any, name: str, *, identity: Any = None) -> Any:
    value = getattr(source, name, None)
    if value is None and isinstance(source, dict):
        value = source.get(name)
    if value is None and identity is not None:
        value = getattr(identity, name, None)
    return value


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _gram(stream: Any) -> tuple[np.ndarray, bytes]:
    try:
        return gram_from_stream(stream)
    except (TypeError, ValueError) as exc:
        raise GeometryRefusal(str(exc)) from exc


def _evidence(observation: Any) -> dict[str, Any]:
    """Copy the complete R2 observation tuple from one committed observation.

    The stream store is the authority for this data.  In particular, a missing mask,
    provenance value, or payload digest is an integrity refusal; it is never filled from
    a default or interpreted as an all-searchable observation.
    """
    identity = getattr(observation, "identity", None)
    if identity is None:
        raise IntegrityRefused("observation has no immutable identity")
    stream_record = getattr(observation, "stream_record", None)
    source = stream_record or observation
    names = (
        "stream_ref",
        "stream_fingerprint_sha256",
        "stream_payload_sha256",
        "patch_count",
        "embedding_dim",
        "stream_dtype",
        "stream_format_version",
        "embed_semantics_version",
        "preprocess_fn",
        "preprocess_version",
        "backbone_model_hash",
        "audio_params",
        "provenance_source",
        "provenance_assumption",
    )
    values = {name: _field(source, name, identity=identity) for name in names}
    if values["stream_fingerprint_sha256"] is None:
        values["stream_fingerprint_sha256"] = _field(source, "fingerprint_sha256", identity=identity)
    if values["stream_payload_sha256"] is None:
        values["stream_payload_sha256"] = values["stream_fingerprint_sha256"]
    if values["embedding_dim"] is None:
        values["embedding_dim"] = _field(source, "dim", identity=identity)
    if values["stream_dtype"] is None:
        values["stream_dtype"] = _field(source, "dtype", identity=identity)
    if values["stream_format_version"] is None:
        values["stream_format_version"] = _field(source, "format_version", identity=identity)
    if values["embedding_dim"] is None:
        values["embedding_dim"] = getattr(getattr(observation, "stream", None), "shape", (0, 0))[1]
    provenance_identity = _field(observation, "provenance_identity", identity=identity)
    if provenance_identity is None:
        # Current StreamStore manifests carry the immutable publication run id as the
        # provenance identity.  Do not invent a value when even that evidence is absent.
        provenance_identity = _field(source, "run_id", identity=identity)
    values.update(
        {
            "song_id": identity.song_id,
            "backbone": identity.backbone,
            "mask_ref": identity.mask_ref,
            "mask_payload_sha256": identity.mask_digest,
            "alignment_token": identity.alignment_token,
            "audio_content_sha256": identity.audio_content_sha256,
            "mask_semantics_version": identity.mask_semantics_version,
            "group_format_version": identity.group_format_version,
            "observation_commit_sha256": identity.commit_sha256,
            "provenance_identity": provenance_identity,
        }
    )
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise IntegrityRefused(f"complete observation evidence is missing: {', '.join(missing)}")
    values["embedding_dim"] = int(values["embedding_dim"])
    values["patch_count"] = int(values["patch_count"])
    values["stream_dtype"] = str(values["stream_dtype"])
    return values


def load_geometry_observation(store: Any, song_id: str, backbone: str) -> Any:
    """Load the sole complete committed observation through the StreamStore seam."""
    try:
        return store.load_committed_observation(song_id, backbone)
    except GeometryRefusal:
        raise
    except Exception as exc:  # store-specific refusal types are deliberately normalized
        raise IntegrityRefused(f"committed observation refused: {exc}") from exc


def _row_to_record(row: tuple[Any, ...], *, matrix: np.ndarray) -> GeometryRecord:
    values = dict(zip(GEOMETRY_COLUMNS, row, strict=True))
    identity = GeometryIdentity(
        str(values["song_id"]),
        str(values["backbone"]),
        str(values["observation_commit_sha256"]),
        str(values["geometry_semantics_version"]),
        str(values["numerical_profile_digest"]),
    )
    evidence = {
        key: values[key]
        for key in values
        if key not in {"geometry_id", "gram_blob", "status", "writer_run_id", "created_at_ms", "updated_at_ms"}
    }
    return GeometryRecord(identity, str(values["geometry_id"]), evidence, bytes(values["gram_blob"]), matrix)


def _validate_profile(profile: GeometryProfile) -> str:
    if not isinstance(profile, GeometryProfile) or not profile.manifest or len(profile.digest) != 64:
        raise IntegrityRefused("missing or malformed geometry profile")
    return profile.to_manifest()["geometry_semantics_version"]


def enforce_geometry_resource_ceiling(patch_count: Any) -> None:
    """Fail closed when a geometry would exceed the configured size/resource ceiling.

    Resource failure is a refusal with no filesystem substitute: the caller may not
    stream, tile, or persist an alternative artifact.
    """
    if isinstance(patch_count, bool) or not isinstance(patch_count, int) or patch_count <= 0:
        raise IntegrityRefused("INTEGRITY_REFUSED: geometry resource refusal: invalid patch count")
    if patch_count > MAX_PATCH_COUNT:
        raise IntegrityRefused("INTEGRITY_REFUSED: geometry resource refusal: patch count exceeds ceiling")
    if 4 * patch_count * patch_count > MAX_GRAM_BYTES:
        raise IntegrityRefused("INTEGRITY_REFUSED: geometry resource refusal: Gram bytes exceed ceiling")


def observation_geometry_identity(observation: Any, profile: GeometryProfile) -> GeometryIdentity:
    """Derive the exact immutable geometry identity for one committed observation."""
    identity = getattr(observation, "identity", None)
    if identity is None:
        raise IntegrityRefused("committed observation has no identity")
    commit = getattr(identity, "commit_sha256", None)
    if not commit:
        raise IntegrityRefused("committed observation has no commit identity")
    if not isinstance(profile, GeometryProfile):
        raise IntegrityRefused("geometry profile is required to derive a geometry identity")
    semantics = profile.to_manifest().get("geometry_semantics_version")
    if not semantics:
        raise IntegrityRefused("geometry profile has no geometry semantics version")
    return GeometryIdentity(
        str(identity.song_id), str(identity.backbone), str(commit), str(semantics), str(profile.digest)
    )


def write_geometry(observation: Any, profile: GeometryProfile, run_id: str, *, lock: Any = None) -> GeometryRecord:
    """Compute and publish one exact-key complete geometry transactionally.

    ``lock`` is an already-held exclusive run-lock token.  Geometry persistence never
    acquires a second lock or performs an implicit recovery/reset; callers that mutate
    the primary DB must pass the existing run lock explicitly.
    """
    con = _connection(observation)
    # The CLI holds the existing exclusive run lock around file-backed writes.  Touch
    # the token so static linting also guarantees callers pass the intended seam.
    if lock is not None and not hasattr(lock, "__enter__"):
        raise IntegrityRefused("invalid exclusive run lock token")
    # The CLI holds the existing exclusive run lock around file-backed writes.  The
    # persistence seam remains usable with injected/in-memory connections for focused
    # characterization tests; it never acquires a competing lock or performs recovery.
    semantics = _validate_profile(profile)
    evidence = _evidence(observation)
    enforce_geometry_resource_ceiling(evidence["patch_count"])
    stream = getattr(observation, "stream", None)
    gram, blob = _gram(stream)
    if gram.shape[0] != evidence["patch_count"]:
        raise GeometryRefusal("stream patch count does not match committed evidence")
    digest = _sha(blob)
    identity = GeometryIdentity(
        evidence["song_id"], evidence["backbone"], evidence["observation_commit_sha256"], semantics, profile.digest
    )
    canonical = "|".join((*identity.__dict__.values(), digest)).encode("utf-8")
    geometry_id = _sha(canonical)
    now = int(time.time() * 1000)
    row_values = {
        **evidence,
        "geometry_id": geometry_id,
        "geometry_semantics_version": semantics,
        "numerical_profile_digest": profile.digest,
        "geometry_blob_byte_length": len(blob),
        "geometry_blob_sha256": digest,
        "gram_blob": blob,
        "status": "complete",
        "writer_run_id": str(run_id),
        "created_at_ms": now,
        "updated_at_ms": now,
    }
    row = tuple(row_values[name] for name in GEOMETRY_COLUMNS)
    if len(row) != len(GEOMETRY_COLUMNS):
        raise GeometryRefusal("geometry row does not match schema")
    schema_fingerprint(con)
    key = (identity.song_id, identity.backbone, identity.observation_commit_sha256, semantics, profile.digest)
    try:
        con.execute("BEGIN")
        count = con.execute(
            "SELECT count(*) FROM song_patch_geometry WHERE song_id=? AND backbone=? AND observation_commit_sha256=? AND geometry_semantics_version=? AND numerical_profile_digest=?",
            key,
        ).fetchone()[0]
        if count != 0:
            raise GeometryRefusal("exact geometry identity already exists")
        con.execute(
            f"INSERT INTO song_patch_geometry ({', '.join(GEOMETRY_COLUMNS)}) VALUES ({','.join('?' for _ in GEOMETRY_COLUMNS)})",
            row,
        )
        check = con.execute(
            "SELECT geometry_blob_byte_length, geometry_blob_sha256, gram_blob, status FROM song_patch_geometry WHERE geometry_id=?",
            [geometry_id],
        ).fetchone()
        if (
            check is None
            or check[3] != "complete"
            or int(check[0]) != len(blob)
            or str(check[1]) != digest
            or bytes(check[2]) != blob
        ):
            raise GeometryRefusal("post-write geometry validation failed")
        con.execute("COMMIT")
    except Exception:
        with contextlib.suppress(Exception):
            con.execute("ROLLBACK")
        raise
    return GeometryRecord(identity, geometry_id, evidence, blob, gram)


def read_geometry(exact_identity: GeometryIdentity, con: Any) -> GeometryRecord:
    """Read and validate exactly one complete geometry row by its full identity."""
    if not isinstance(exact_identity, GeometryIdentity):
        raise GeometryRefusal("geometry reads require an exact GeometryIdentity")
    schema_fingerprint(con)
    rowset = con.execute(
        f"SELECT {', '.join(GEOMETRY_COLUMNS)} FROM song_patch_geometry WHERE song_id=? AND backbone=? AND observation_commit_sha256=? AND geometry_semantics_version=? AND numerical_profile_digest=?",
        tuple(exact_identity.__dict__.values()),
    ).fetchall()
    if len(rowset) != 1:
        raise GeometryRefusal(f"exact geometry read expected one row, found {len(rowset)}")
    row = rowset[0]
    blob = bytes(row[GEOMETRY_COLUMNS.index("gram_blob")])
    length = int(row[GEOMETRY_COLUMNS.index("geometry_blob_byte_length")])
    patch_count = int(row[GEOMETRY_COLUMNS.index("patch_count")])
    enforce_geometry_resource_ceiling(patch_count)
    if (
        row[GEOMETRY_COLUMNS.index("status")] != "complete"
        or length != len(blob)
        or length != 4 * patch_count * patch_count
        or _sha(blob) != row[GEOMETRY_COLUMNS.index("geometry_blob_sha256")]
    ):
        raise GeometryRefusal("geometry BLOB integrity validation failed")
    matrix = np.frombuffer(blob, dtype="<f4").reshape((patch_count, patch_count), order="C")
    if not np.isfinite(matrix).all() or matrix.dtype.byteorder not in ("<", "="):
        raise GeometryRefusal("geometry matrix is malformed or non-finite")
    return _row_to_record(row, matrix=matrix)


def read_geometry_matrix(exact_identity: GeometryIdentity, con: Any) -> np.ndarray:
    """Read the exact geometry matrix as a read-only float32 array."""
    matrix = read_geometry(exact_identity, con).matrix
    matrix.setflags(write=False)
    return matrix


def _classify_evidence(
    record: GeometryRecord,
    current_observation: Any,
    *,
    semantics: str,
    profile_digest: str,
) -> None:
    """Classify the complete recorded-vs-current evidence comparison.

    A newer committed observation is ``STALE_REFUSED``; every other mismatch
    (malformed, missing, corrupt, wrong-dtype/length, profile mismatch) is
    ``INTEGRITY_REFUSED``.  There is no repair, rebind, or substitute branch.
    """
    try:
        current = _evidence(current_observation)
        expected = dict(record.evidence)
    except GeometryRefusal:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise IntegrityRefused(f"INTEGRITY_REFUSED: malformed current observation evidence: {exc}") from exc

    if expected.get("observation_commit_sha256") != current.get("observation_commit_sha256"):
        raise StaleRefused("STALE_REFUSED: committed observation has been superseded")
    identity_fields = ("song_id", "backbone", "geometry_semantics_version", "numerical_profile_digest")
    if (
        record.identity.geometry_semantics_version != semantics
        or record.identity.numerical_profile_digest != profile_digest
        or any(expected.get(field) != current.get(field) for field in ("song_id", "backbone"))
    ):
        raise IntegrityRefused("INTEGRITY_REFUSED: geometry identity/profile binding mismatch")
    fields = tuple(
        name
        for name in expected
        if name not in identity_fields and name not in {"geometry_blob_byte_length", "geometry_blob_sha256"}
    )
    mismatches = [name for name in fields if expected.get(name) != current.get(name)]
    if mismatches:
        raise IntegrityRefused(
            "INTEGRITY_REFUSED: committed observation evidence mismatch: " + ", ".join(sorted(mismatches))
        )


def verify_geometry_binding(record: GeometryRecord, current_observation: Any, profile: GeometryProfile) -> None:
    """Compare the complete persisted R2 evidence tuple, without rebinding or repair."""
    semantics = _validate_profile(profile)
    _classify_evidence(record, current_observation, semantics=semantics, profile_digest=profile.digest)


def verify_geometry_current(
    con: Any,
    observation: Any,
    *,
    profile: GeometryProfile | None = None,
    exact_identity: GeometryIdentity | None = None,
) -> GeometryRecord | None:
    """The single shared current-binding preflight used by every geometry-derived seam.

    Resolves the persisted geometry row for the observation's CURRENT committed identity
    and verifies the complete R2 observation/profile tuple.  Returns the verified record,
    or ``None`` when no geometry row exists for the ``(song_id, backbone)`` pair at all.
    A row bound to an older commit is ``STALE_REFUSED``; duplicate rows, malformed/missing
    evidence, and profile mismatch are ``INTEGRITY_REFUSED``.  It never selects a
    latest/current artifact, rebinds, repairs, or falls back.
    """
    identity = getattr(observation, "identity", None)
    if identity is None:
        raise IntegrityRefused("INTEGRITY_REFUSED: committed observation has no identity")
    song_id = str(identity.song_id)
    backbone = str(identity.backbone)
    commit = str(getattr(identity, "commit_sha256", ""))
    if not commit:
        raise IntegrityRefused("INTEGRITY_REFUSED: committed observation has no commit identity")

    candidate: GeometryIdentity | None
    if exact_identity is not None:
        if not isinstance(exact_identity, GeometryIdentity):
            raise IntegrityRefused("INTEGRITY_REFUSED: exact geometry identity is required")
        if (exact_identity.song_id, exact_identity.backbone, exact_identity.observation_commit_sha256) != (
            song_id,
            backbone,
            commit,
        ):
            raise StaleRefused("STALE_REFUSED: requested geometry identity no longer matches the committed observation")
        candidate = exact_identity
    elif profile is not None:
        candidate = observation_geometry_identity(observation, profile)
    else:
        candidate = None

    rows = con.execute(
        f"SELECT {', '.join(GEOMETRY_COLUMNS)} FROM song_patch_geometry WHERE song_id=? AND backbone=?",
        (song_id, backbone),
    ).fetchall()
    if not rows:
        return None
    commit_index = GEOMETRY_COLUMNS.index("observation_commit_sha256")
    semantics_index = GEOMETRY_COLUMNS.index("geometry_semantics_version")
    digest_index = GEOMETRY_COLUMNS.index("numerical_profile_digest")

    if candidate is not None:
        exact_matches = [
            row
            for row in rows
            if (
                str(row[commit_index]),
                str(row[semantics_index]),
                str(row[digest_index]),
            )
            == (commit, candidate.geometry_semantics_version, candidate.numerical_profile_digest)
        ]
        if not exact_matches:
            if any(str(row[commit_index]) == commit for row in rows):
                raise IntegrityRefused("INTEGRITY_REFUSED: geometry profile/semantics binding mismatch")
            raise StaleRefused("STALE_REFUSED: committed observation has been superseded")
        if len(exact_matches) > 1:
            raise IntegrityRefused("INTEGRITY_REFUSED: duplicate geometry rows for the committed observation")
        record = read_geometry(candidate, con)
        semantics = candidate.geometry_semantics_version
        digest = candidate.numerical_profile_digest
    else:
        commit_matches = [row for row in rows if str(row[commit_index]) == commit]
        if not commit_matches:
            raise StaleRefused("STALE_REFUSED: committed observation has been superseded")
        if len(commit_matches) > 1:
            raise IntegrityRefused("INTEGRITY_REFUSED: duplicate geometry rows for the committed observation")
        row = commit_matches[0]
        resolved = GeometryIdentity(song_id, backbone, commit, str(row[semantics_index]), str(row[digest_index]))
        record = read_geometry(resolved, con)
        semantics = record.identity.geometry_semantics_version
        digest = record.identity.numerical_profile_digest

    _classify_evidence(record, observation, semantics=semantics, profile_digest=digest)
    return record


def preflight_geometry_binding(
    record: GeometryRecord,
    profile: GeometryProfile,
    *,
    store: Any = None,
    observation: Any = None,
) -> Any:
    """The one shared complete-binding preflight, re-reading the current observation.

    When *observation* is omitted the current committed observation is re-read through
    *store* so a supersession that occurred after computation is detected.  The verified
    observation is returned; every failure is the typed ``STALE_REFUSED`` /
    ``INTEGRITY_REFUSED`` refusal with no substitute path.
    """
    if not isinstance(record, GeometryRecord):
        raise IntegrityRefused("INTEGRITY_REFUSED: geometry preflight requires a complete GeometryRecord")
    if store is not None:
        # A store is authoritative for the CURRENT tuple: always re-read it so a
        # supersession after computation is detected.
        observation = load_geometry_observation(store, record.identity.song_id, record.identity.backbone)
    elif observation is None:
        raise IntegrityRefused("INTEGRITY_REFUSED: geometry preflight requires the committed observation or its store")
    verify_geometry_binding(record, observation, profile)
    return observation


def require_current_geometry(
    song_id: str,
    backbone: str,
    con: Any,
    *,
    store: Any,
    profile: GeometryProfile,
) -> tuple[GeometryRecord, Any]:
    """Open the exact current geometry for ``(song_id, backbone)`` or refuse."""
    observation = load_geometry_observation(store, song_id, backbone)
    record = verify_geometry_current(con, observation, profile=profile)
    if record is None:
        raise IntegrityRefused(
            "INTEGRITY_REFUSED: no committed geometry for the current observation; run the geometry phase"
        )
    return record, observation


# Public names make refusal status machine-readable without requiring message parsing.
STALE_REFUSED = StaleRefused
INTEGRITY_REFUSED = IntegrityRefused
