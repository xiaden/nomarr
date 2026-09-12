"""Downstream winners/baseline reshape: winners and observed baseline stay separate."""

from __future__ import annotations

from scripts.embedding_research.report._retrieval import (
    BASELINE_EVIDENCE_ROLE,
    query_geometry_winners,
    query_observed_baselines,
)
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def test_winners_and_observed_baseline_are_partitioned_exactly():
    con = build_seeded_con()
    try:
        winners = query_geometry_winners(con, run_id=RUN_ID)
        baselines = query_observed_baselines(con, run_id=RUN_ID)
    finally:
        con.close()

    assert not winners.empty and not baselines.empty
    assert not winners["evidence_json"].astype(str).str.contains(BASELINE_EVIDENCE_ROLE, regex=False).any()
    assert baselines["evidence_json"].astype(str).str.contains(BASELINE_EVIDENCE_ROLE, regex=False).all()
    assert all(str(threshold).startswith("observed-baseline:") for threshold in baselines["threshold_id"])
    assert not set(winners["geometry_id"] + "|" + winners["threshold_id"]).intersection(
        set(baselines["geometry_id"] + "|" + baselines["threshold_id"])
    )
