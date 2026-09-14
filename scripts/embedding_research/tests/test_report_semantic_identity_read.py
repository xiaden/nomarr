"""Semantic identity read: exact run-scoped normalized evidence, no blend or substitution."""

from __future__ import annotations

import pytest

from scripts.embedding_research.report._retrieval import IDENTITY_COLUMNS, collect_report_frames
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def test_collect_report_frames_reads_exact_run_scope():
    con = build_seeded_con()
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
    finally:
        con.close()

    assert frames.run_id == RUN_ID
    assert frames.evaluation_corpus
    assert frames.threshold_class_map
    assert frames.baseline_aggregate_metrics
    assert frames.provenance["evaluation_id"]


def test_collect_report_frames_requires_exact_run_id():
    con = build_seeded_con()
    try:
        with pytest.raises(ValueError):
            collect_report_frames(con, run_id="")
        with pytest.raises(ValueError):
            collect_report_frames(con, run_id=None)
    finally:
        con.close()


def test_collect_report_frames_refuses_absent_run():
    con = build_seeded_con()
    try:
        with pytest.raises(ValueError):
            collect_report_frames(con, run_id="no-such-run")
    finally:
        con.close()


def test_normalized_identity_axes_are_complete():
    con = build_seeded_con()
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
    finally:
        con.close()

    provenance = frames.provenance
    assert set(IDENTITY_COLUMNS) == {
        "geometry_id",
        "observation_group_sha256",
        "geometry_semantics_version",
        "numerical_profile_digest",
        "threshold_id",
        "structural_identity",
        "search_representation_id",
        "evaluation_id",
        "scoring_semantics_version",
        "execution_id",
    }
    assert provenance["geometry_axes"]
    for axis in provenance["geometry_axes"]:
        for column in ("geometry_id", "observation_group_sha256", "numerical_profile_digest"):
            assert axis[column]
