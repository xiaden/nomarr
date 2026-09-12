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
    return [
        {
            "geometry_id": row[0],
            "observation_id": row[1],
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
            "SELECT geometry_id, observation_commit_sha256, geometry_semantics_version, "
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
    data.setdefault("warnings", []).append(SYNTHETIC_WARNING)
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fixture report written: {report_path}")
    return report_path


if __name__ == "__main__":
    main()
