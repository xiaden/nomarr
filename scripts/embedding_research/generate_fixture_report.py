"""Deterministic synthetic geometry report fixture generator.

Builds an in-memory research database containing only synthetic committed geometry
evidence, publishes real ``song_patch_geometry`` rows through ``db.geometry.write_geometry``,
persists exact geometry analysis and head evidence through the geometry owner APIs, and
renders the seven-section report.  No audio, model, ONNX, CUDA, real corpus, copied
vector, or inferred provenance is used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_ROOT = _PKG_DIR.parents[1]
for _path in (_ROOT, _PKG_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


from typing import TYPE_CHECKING

from scripts.embedding_research.config import REPORT_DIR
from scripts.embedding_research.db._schema import schema_fingerprint
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.tests._report_seed import (
    EVALUATION_ID,
    EXECUTION_ID,
    EXPERIMENT,
    MATRICES,
    PHASE_NAMES,
    RUN_ID,
    SCORING_SEMANTICS_VERSION,
    SYNTHETIC_WARNING,
    THRESHOLD_IDS,
    build_seeded_con,
)

if TYPE_CHECKING:
    import duckdb

# Re-exported for callers/tests that imported the seed constant from this module.
_FIXTURE_RUN_ID = RUN_ID


def _identity_evidence_rows(rows: list[tuple]) -> list[dict]:
    """Map geometry identity rows to the report's identity-evidence records."""
    return [
        {
            "geometry_id": row[0],
            "observation_group_sha256": row[1],
            "geometry_semantics_version": row[2],
            "numerical_profile_digest": row[3],
            "threshold_id": THRESHOLD_IDS[0],
            "structural_identity": f"{EXPERIMENT}:{THRESHOLD_IDS[0]}",
            "search_representation_id": f"rep:{THRESHOLD_IDS[0]}",
            "evaluation_id": EVALUATION_ID,
            "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
            "execution_id": EXECUTION_ID,
        }
        for row in rows
    ]


def build_fixture_con() -> duckdb.DuckDBPyConnection:
    """Build the fully synthetic in-memory geometry report database."""
    return build_seeded_con(run_id=RUN_ID)


def main(report_dir: Path = REPORT_DIR) -> Path:
    """Generate the synthetic seven-section fixture report and its sibling HTML.

    Seeds an in-memory geometry database, renders the report through the exact
    geometry report contract, then augments ``report.json`` with the synthetic-only
    marker, geometry evidence, and refusal matrices.  Returns the JSON path.
    """
    con = build_fixture_con()
    try:
        schema_fingerprint(con)
        report_run(con, report_dir, run_id=RUN_ID)
        geometry_rows = con.execute(
            "SELECT geometry_id, observation_group_sha256, geometry_semantics_version, "
            "numerical_profile_digest FROM song_patch_geometry ORDER BY geometry_id"
        ).fetchall()
        head_rows = con.execute(
            "SELECT geometry_id, observation_id, geometry_semantics_version, "
            "numerical_profile_digest FROM geometry_head_evidence "
            "ORDER BY geometry_id, segment_id"
        ).fetchall()
    finally:
        con.close()

    report_path = report_dir / "report.json"
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data["synthetic_only"] = True
    data["geometry_evidence"] = {
        "geometry": _identity_evidence_rows(geometry_rows),
        "head": _identity_evidence_rows(head_rows),
        "phases": list(PHASE_NAMES),
    }
    data["matrices"] = MATRICES
    benchmark = {
        "n_songs": 8,
        "patch_distribution": {"songs": 8, "segments_per_song": 12, "row_distribution": "uniform"},
        "dimension": 16,
        "backbone": "synthetic_effnet_fixture",
        "model_hash": "7232c425660d7f24955beb1e975124b2a687c965b3b43bbaa43f35af77e05cbb",
        "hardware": "fixtures-only synthetic host",
        "software": "fixtures-only deterministic profile",
        "peak_rss_bytes": 0,
        "peak_tracemalloc_bytes": 0,
        "elapsed_ms": 0.0,
        "query_chunk_size": 2048,
        "candidate_chunk_size": 2048,
        "working_memory_bytes": 33554432,
        "fixtures_only": True,
        "no_empirical_statement": "FIXTURES-ONLY SYNTHETIC — deterministic fixture surface, no empirical corpus/model retrieval claim.",
        "k_rows": 48,
        "m_rows": 96,
        "full_product_bytes": 36864,
        "score": 0.5499724615544072,
        "finite": True,
    }
    data["corrective_evidence"] = {
        "retrieval": {
            "corpus_wide_leave_one_out": True,
            "self_candidate_count": 0,
            "segmentation_from_scorer_count": 0,
            "canonical_scorer": "max_per_candidate_segment",
        },
        "identity": {
            "collapse_requires_all_scoring_inputs": True,
            "structural_identity_separate": True,
            "search_representation_id_excludes_structural_identity": True,
        },
        "comparability": {
            "non_comparable_persisted": True,
            "explicit_reasons": ["alignment_failed", "no_searchable", "no_medoid", "no_candidates", "label_missing"],
            "reason_vocabulary_owner": "helpers.corpus_identity.classify_representation",
        },
        "rulers": ["artist", "genre", "frozen_head"],
        "threshold_map": {"count": 171, "first_index": 0, "last_index": 170},
        "corpus_map": {"candidate_population": "ordered_corpus_song_ids", "leave_one_out": True},
        "neighborhoods": {
            "winner": {"min": 0, "max": 100, "bounded": True},
            "baseline": {"min": 0, "max": 100, "same_population": True},
        },
        "numeric_profile": {
            "kernel": "numpy_row_normalize_float32_matmul",
            "serialization": "little_endian_c_order_float32",
            "zero_near_zero_centroid_fixtures": True,
            "ulp_boundary_fixtures": True,
        },
        "round_trips": ["geometry_blob", "report_json", "scientific_hashes"],
        "scientific_hash_retention": True,
        "benchmark": benchmark,
    }
    data.setdefault("warnings", []).append(SYNTHETIC_WARNING)
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fixture report written: {report_path}")
    return report_path


if __name__ == "__main__":
    main()
