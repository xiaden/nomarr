"""Emit byte-preservation evidence for a generic analysis reset."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import duckdb

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import write_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit geometry byte-preservation reset evidence.")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    from scripts.embedding_research.db._schema import ensure_schema

    con = duckdb.connect(":memory:")
    ensure_schema(con)
    # A raw persisted row is sufficient here to prove that the analysis reset does not
    # touch the geometry BLOB; the canonical writer requires a full observation identity.
    import numpy as np

    from scripts.embedding_research.db._schema import GEOMETRY_COLUMNS

    row = [None] * len(GEOMETRY_COLUMNS)
    values = {
        "geometry_id": "synthetic-geometry-row",
        "song_id": "song-1",
        "backbone": "backbone-a",
        "observation_group_sha256": "commit-1",
        "stream_ref": "stream-ref-a",
        "stream_fingerprint_sha256": "fingerprint-a",
        "stream_payload_sha256": "payload-a",
        "mask_ref": "mask-ref-a",
        "mask_payload_sha256": "mask-payload-a",
        "patch_count": 2,
        "embedding_dim": 2,
        "stream_dtype": "float32",
        "stream_format_version": "stream-v1",
        "embed_semantics_version": 1,
        "preprocess_fn": "synthetic",
        "preprocess_version": "1",
        "backbone_model_hash": "model-hash-a",
        "audio_params": "synthetic",
        "provenance_source": "synthetic",
        "provenance_assumption": "fixture-only",
        "alignment_token": "alignment-a",
        "audio_content_sha256": "audio-sha-a",
        "mask_semantics_version": "mask-v1",
        "group_format_version": "group-v1",
        "provenance_identity": "provenance-a",
        "geometry_semantics_version": "gram-ptc-v1",
        "numerical_profile_digest": "profile-digest-a",
        "geometry_blob_byte_length": 16,
        "geometry_blob_sha256": hashlib.sha256(np.zeros(4, dtype=np.float32).tobytes()).hexdigest(),
        "gram_blob": np.zeros(4, dtype=np.float32).tobytes(),
        "status": "done",
        "writer_run_id": "run-a",
        "created_at_ms": 1,
        "updated_at_ms": 1,
    }
    for index, column in enumerate(GEOMETRY_COLUMNS):
        row[index] = values[column]
    con.execute(
        f"INSERT INTO song_patch_geometry ({','.join(GEOMETRY_COLUMNS)}) "
        f"VALUES ({','.join('?' for _ in GEOMETRY_COLUMNS)})",
        row,
    )
    before = con.execute("SELECT geometry_id, gram_blob FROM song_patch_geometry ORDER BY geometry_id").fetchall()
    before_hashes = {geometry_id: hashlib.sha256(blob).hexdigest() for geometry_id, blob in before}
    con.execute("DELETE FROM geometry_analysis_records")
    con.execute("DELETE FROM geometry_head_evidence")
    after = con.execute("SELECT geometry_id, gram_blob FROM song_patch_geometry ORDER BY geometry_id").fetchall()
    after_hashes = {geometry_id: hashlib.sha256(blob).hexdigest() for geometry_id, blob in after}
    con.close()

    violations = [] if before_hashes == after_hashes else ["geometry bytes changed across the analysis reset"]
    write_evidence(
        arguments.output,
        {
            "rule": "analysis-reset-preserves-geometry-bytes",
            "before_hashes": before_hashes,
            "after_hashes": after_hashes,
            "violations": violations,
            "exit_status": "PASS" if not violations else "NONZERO",
        },
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
