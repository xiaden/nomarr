"""Semantic identity read: exact run-scoped normalized evidence, no blend or substitution."""

from __future__ import annotations

import pytest

from scripts.embedding_research.report._retrieval import IDENTITY_COLUMNS, query_normalized_result
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def test_query_normalized_result_reads_exact_run_scope():
    con = build_seeded_con()
    try:
        result = query_normalized_result(con, run_id=RUN_ID)
    finally:
        con.close()

    assert result.run_id == RUN_ID
    assert result.evaluation_corpus
    assert result.threshold_class_map
    assert result.baseline_aggregate_metrics
    assert result.provenance.evaluation_id


def test_query_normalized_result_requires_exact_run_id():
    con = build_seeded_con()
    try:
        with pytest.raises(ValueError):
            query_normalized_result(con, run_id="")
        with pytest.raises(ValueError):
            query_normalized_result(con, run_id=None)
    finally:
        con.close()


def test_query_normalized_result_refuses_absent_run():
    con = build_seeded_con()
    try:
        with pytest.raises(ValueError):
            query_normalized_result(con, run_id="no-such-run")
    finally:
        con.close()


def test_normalized_identity_axes_are_complete():
    con = build_seeded_con()
    try:
        result = query_normalized_result(con, run_id=RUN_ID)
    finally:
        con.close()

    provenance = result.provenance
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
    assert provenance.geometry_axes
    for axis in provenance.geometry_axes:
        for column in ("geometry_id", "observation_group_sha256", "numerical_profile_digest"):
            assert axis[column]
