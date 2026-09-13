"""Shared declared-evidence emitter and synthetic fixtures for the retained R1-R13 matrix.

R1-R13 label the retained synthetic *behavior* evidence (schema, binding, retrieval,
medoid, silence/weight, collapse/scorer boundary, report identity, deleted surface,
phase timings, storage lifecycle, reset, and scope/synthetic-only checks).  Only R14 —
the Git/source-commit traceability replay — was hard-deleted by the corrective pass;
the R1-R13 scientific behavior tests and their ``rN-*.json`` artifacts are retained.

Every retained matrix test produces a deterministic synthetic artifact under a DECLARED
evidence path.  Nothing here reads audio, a model, ONNX, CUDA, or a real corpus: the
observations are pure in-memory numpy arrays; fixtures target the NumPy
production Gram kernel (row normalization plus float32 matmul).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT

#: Sole synthetic scientific JSON/hash root, shared with runtime configuration.
#: The retired artifacts/evidence fixture root is intentionally not a compatibility path.
EVIDENCE_ROOT = OUTPUT_ROOT


def emit_evidence(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Write one deterministic JSON evidence artifact and return it with its digest.

    Fixture names are deliberately narrow: they must be a single contained JSON
    filename, so synthetic evidence cannot escape the configured scientific root.
    The digest remains over the canonical payload BEFORE the digest field is added.
    """
    fixture = Path(name)
    if fixture.is_absolute() or fixture.suffix != ".json":
        raise ValueError("fixture evidence names must be contained .json paths")
    path = (EVIDENCE_ROOT / fixture).resolve()
    try:
        path.relative_to(EVIDENCE_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("fixture evidence path must be contained by OUTPUT_ROOT") from exc
    record = dict(payload)
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    record["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    normalized = json.loads(json.dumps(record, sort_keys=True))
    assert json.loads(path.read_text(encoding="utf-8")) == normalized, f"evidence round-trip failed: {path}"
    return record


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SyntheticIdentity:
    """Minimal immutable observation identity for the exact geometry binding tuple."""

    def __init__(
        self,
        song_id: str = "song-1",
        backbone: str = "backbone-a",
        *,
        commit: str = "commit-1",
        mask_digest: str | None = "mask-digest-a",
        mask_ref: str = "mask-ref-a",
        alignment_token: str = "alignment-a",
        audio_content_sha256: str = "audio-sha-a",
        mask_semantics_version: str = "mask-v1",
        group_format_version: str = "group-v1",
    ) -> None:
        self.song_id = song_id
        self.backbone = backbone
        self.mask_ref = mask_ref
        self.mask_digest = mask_digest
        self.alignment_token = alignment_token
        self.audio_content_sha256 = audio_content_sha256
        self.mask_semantics_version = mask_semantics_version
        self.group_format_version = group_format_version
        self.commit_sha256 = commit


class SyntheticStreamRecord:
    """Minimal committed stream-record evidence (no filesystem payload)."""

    def __init__(self, patch_count: int, embedding_dim: int, *, stream_dtype: str = "float32") -> None:
        self.stream_ref = "stream-ref-a"
        self.fingerprint_sha256 = "stream-fingerprint-a"
        self.stream_payload_sha256 = "stream-payload-a"
        self.patch_count = patch_count
        self.embedding_dim = embedding_dim
        self.stream_dtype = stream_dtype
        self.stream_format_version = "stream-v1"
        self.embed_semantics_version = 1
        self.preprocess_fn = "synthetic"
        self.preprocess_version = "1"
        self.backbone_model_hash = "model-hash-a"
        self.audio_params = "synthetic-audio-params"
        self.provenance_source = "synthetic"
        self.provenance_assumption = "fixture-only"
        self.run_id = "run-a"


class SyntheticObservation:
    """One committed synthetic observation bound to an open DuckDB connection."""

    def __init__(
        self,
        con: Any,
        *,
        song_id: str = "song-1",
        backbone: str = "backbone-a",
        commit: str = "commit-1",
        stream: np.ndarray | None = None,
        mask_digest: str | None = "mask-digest-a",
        stream_dtype: str = "float32",
        provenance_identity: str | None = "provenance-a",
    ) -> None:
        self.con = con
        self.stream = np.asarray(
            stream if stream is not None else [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
            dtype=np.float32,
        )
        self.identity = SyntheticIdentity(song_id, backbone, commit=commit, mask_digest=mask_digest)
        self.stream_record = SyntheticStreamRecord(
            self.stream.shape[0], self.stream.shape[1], stream_dtype=stream_dtype
        )
        self.provenance_identity = provenance_identity


def duplicate_geometry_row(con: Any, geometry_id: str) -> None:
    """Insert one raw duplicate-identity geometry row (new geometry_id) for refusal tests."""
    from scripts.embedding_research.db._schema import GEOMETRY_COLUMNS

    row = list(con.execute("SELECT * FROM song_patch_geometry LIMIT 1").fetchone())
    row[GEOMETRY_COLUMNS.index("geometry_id")] = geometry_id
    con.execute(
        f"INSERT INTO song_patch_geometry ({', '.join(GEOMETRY_COLUMNS)}) "
        f"VALUES ({','.join('?' for _ in GEOMETRY_COLUMNS)})",
        row,
    )


def update_geometry_blob(con: Any, geometry_id: str, blob: bytes, *, fix_digest: bool, fix_length: bool) -> None:
    """Rewrite one persisted geometry BLOB (optionally fixing digest/length) for tamper tests."""
    assignments = ["gram_blob = ?"]
    params: list[Any] = [blob]
    if fix_digest:
        assignments.append("geometry_blob_sha256 = ?")
        params.append(sha256_bytes(blob))
    if fix_length:
        assignments.append("geometry_blob_byte_length = ?")
        params.append(len(blob))
    params.append(geometry_id)
    con.execute(f"UPDATE song_patch_geometry SET {', '.join(assignments)} WHERE geometry_id = ?", params)
