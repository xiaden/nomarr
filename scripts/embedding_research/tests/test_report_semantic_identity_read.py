"""Semantic identity read: exact run-scoped evidence, no blend or substitution."""

from __future__ import annotations

import pytest

from scripts.embedding_research.report._retrieval import (
    GEOMETRY_ANALYSIS_COLUMNS,
    IDENTITY_COLUMNS,
    query_analyze_metrics,
    query_geometry_identity,
)
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def test_query_analyze_metrics_reads_exact_run_scope():
    con = build_seeded_con()
    try:
        frame = query_analyze_metrics(con, run_id=RUN_ID)
        other = query_analyze_metrics(con, run_id="no-such-run")
    finally:
        con.close()

    assert list(frame.columns) == GEOMETRY_ANALYSIS_COLUMNS
    assert not frame.empty
    assert set(frame["run_id"]) == {RUN_ID}
    assert other.empty


def test_query_analyze_metrics_requires_exact_run_id():
    con = build_seeded_con()
    try:
        with pytest.raises(ValueError):
            query_analyze_metrics(con, run_id="")
        with pytest.raises(ValueError):
            query_analyze_metrics(con, run_id=None)
    finally:
        con.close()


def test_query_geometry_identity_exposes_complete_axes():
    con = build_seeded_con()
    try:
        identity = query_geometry_identity(con, run_id=RUN_ID)
    finally:
        con.close()

    for column in ("run_id", *IDENTITY_COLUMNS):
        assert column in identity.columns
    assert not identity.empty
    assert set(identity["run_id"]) == {RUN_ID}
    for column in IDENTITY_COLUMNS:
        assert identity[column].notna().all()
