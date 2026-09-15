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

from scripts.embedding_research.config import REPORT_DIR, RUNTIME_ROOT
from scripts.embedding_research.db._schema import schema_fingerprint
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.tests._report_seed import (
    MATRICES,
    PHASE_NAMES,
    RUN_ID,
    SYNTHETIC_WARNING,
    THRESHOLD_IDS,
    build_seeded_con,
)

if TYPE_CHECKING:
    import duckdb

# Re-exported for callers/tests that imported the seed constant from this module.
_FIXTURE_RUN_ID = RUN_ID


def _identity_evidence_rows(rows: list[tuple]) -> list[dict]:
    """Map exact geometry rows to the normalized report identity surface."""
    return [
        {
            "geometry_id": row[0],
            "observation_group_sha256": row[1],
            "geometry_semantics_version": row[2],
            "numerical_profile_digest": row[3],
        }
        for row in rows
    ]


def build_fixture_con() -> duckdb.DuckDBPyConnection:
    """Build the fully synthetic in-memory geometry report database."""
    return build_seeded_con(run_id=RUN_ID)


def main(report_dir: Path = REPORT_DIR, *, html_out_path: Path | None = None) -> Path:
    """Generate the synthetic seven-section fixture report and its sibling HTML.

    Seeds an in-memory geometry database, renders the report through the exact
    geometry report contract, then augments ``report.json`` with the synthetic-only
    marker, geometry evidence, and refusal matrices.  Returns the JSON path.
    """
    con = build_fixture_con()
    try:
        schema_fingerprint(con)
        report_run(
            con,
            report_dir,
            run_id=RUN_ID,
            html_out_path=html_out_path
            or (
                RUNTIME_ROOT / "docs" / "embedding-research-report.html"
                if report_dir.resolve() == REPORT_DIR.resolve()
                else report_dir.resolve().parent / "docs" / "embedding-research-report.html"
            ),
        )
        geometry_rows = con.execute(
            "SELECT geometry_id, observation_group_sha256, geometry_semantics_version, "
            "numerical_profile_digest FROM song_patch_geometry ORDER BY geometry_id"
        ).fetchall()
        head_rows = con.execute(
            "SELECT geometry_id, observation_group_sha256, geometry_semantics_version, "
            "numerical_profile_digest FROM geometry_head_evidence "
            "ORDER BY geometry_id, segment_id"
        ).fetchall()
        threshold_rows = con.execute(
            "SELECT threshold_index, threshold_id, corpus_search_class_id, comparable "
            "FROM geometry_threshold_class_map WHERE run_id=? ORDER BY threshold_index",
            (RUN_ID,),
        ).fetchall()
        class_rows = con.execute(
            "SELECT DISTINCT corpus_search_class_id FROM geometry_class_aggregate_metrics "
            "WHERE run_id=? ORDER BY corpus_search_class_id",
            (RUN_ID,),
        ).fetchall()
        class_metric_rows = con.execute(
            "SELECT DISTINCT corpus_search_class_id, ruler, metric FROM geometry_class_aggregate_metrics "
            "WHERE run_id=? ORDER BY corpus_search_class_id, ruler, metric",
            (RUN_ID,),
        ).fetchall()
        class_value_rows = con.execute(
            "SELECT corpus_search_class_id, value FROM geometry_class_aggregate_metrics "
            "WHERE run_id=? ORDER BY corpus_search_class_id, ruler, metric",
            (RUN_ID,),
        ).fetchall()
        class_neighborhood_rows = con.execute(
            "SELECT corpus_search_class_id, query_song_id, candidate_song_id "
            "FROM geometry_class_neighborhoods WHERE run_id=?",
            (RUN_ID,),
        ).fetchall()
        baseline_rows = con.execute(
            "SELECT DISTINCT backbone FROM geometry_baseline_aggregate_metrics WHERE run_id=?",
            (RUN_ID,),
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
        "analysis_backbone": "effnet",
        "synthetic_only": True,
        "normalized_surfaces": [
            "geometry_threshold_class_map",
            "geometry_threshold_structural",
            "geometry_class_aggregate_metrics",
            "geometry_class_query_metrics",
            "geometry_class_neighborhoods",
            "geometry_baseline_aggregate_metrics",
            "geometry_baseline_query_metrics",
            "geometry_baseline_neighborhoods",
            "geometry_evaluation_corpus",
            "geometry_head_label_provenance",
            "geometry_result_provenance",
        ],
        "threshold_points": len(threshold_rows),
        "classes": [row[0] for row in class_rows],
        "class_metric_cells": [list(row) for row in class_metric_rows],
        "class_neighborhood_key_count": len({tuple(row) for row in class_neighborhood_rows}),
        "baseline_backbones": [row[0] for row in baseline_rows],
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
        "numerical_kernel_version": "numpy_row_normalize_float32_matmul_v1",
    }
    configured_threshold_count = len(threshold_rows)
    if configured_threshold_count < 2:
        raise AssertionError("fixture requires at least two threshold points")
    if len({row[2] for row in threshold_rows}) < 2:
        raise AssertionError("fixture requires distinct threshold classes")
    if len({row[1] for row in class_value_rows}) < 2:
        raise AssertionError("fixture requires distinct expected class metrics")
    if configured_threshold_count != len(THRESHOLD_IDS):
        raise AssertionError("threshold map count does not match configured threshold count")
    if len(baseline_rows) != 1:
        raise AssertionError("fixture requires exactly one fixed baseline block")
    # This is the compact normalized evidence summary; all detailed result data
    # remains in the normalized report tables and is never nested in this payload.
    data["corrective_evidence"] = {
        "threshold_map": {
            "count": configured_threshold_count,
            "first_index": threshold_rows[0][0],
            "last_index": threshold_rows[-1][0],
        },
        "class_collapse_context": [
            {
                "corpus_search_class_id": row[0],
                "threshold_indices": [item[0] for item in threshold_rows if item[2] == row[0]],
                "comparable": all(item[3] for item in threshold_rows if item[2] == row[0]),
            }
            for row in class_rows
        ],
        "per_ruler_metric_availability": {
            ruler: sorted({row[2] for row in class_metric_rows if row[1] == ruler})
            for ruler in sorted({row[1] for row in class_metric_rows})
        },
        "baseline_once": {
            "count": len(baseline_rows),
            "fixed": True,
            "control": "observed whole-song source-medoid baseline",
            "same_population": True,
        },
        "class_scoped_neighborhood_uniqueness": {
            "key": ["corpus_search_class_id", "query_song_id", "candidate_song_id"],
            "unique": len(class_neighborhood_rows) == len({tuple(row) for row in class_neighborhood_rows}),
            "self_candidate_count": sum(row[1] == row[2] for row in class_neighborhood_rows),
        },
        "reason_vocabulary_owner": "helpers.corpus_identity.classify_representation",
        "observed_baseline_control": "observed whole-song source-medoid baseline",
        "scientific_hash_retention": True,
        "benchmark": benchmark,
    }
    data.setdefault("warnings", []).append(SYNTHETIC_WARNING)
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fixture report written: {report_path}")
    return report_path


if __name__ == "__main__":
    main()
