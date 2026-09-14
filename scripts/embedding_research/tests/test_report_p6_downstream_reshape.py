"""Downstream class/baseline reshape: class-scoped and baseline windows stay separate."""

from __future__ import annotations

from scripts.embedding_research.report._retrieval import collect_report_frames
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def test_class_and_observed_baseline_are_partitioned_exactly():
    con = build_seeded_con()
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
    finally:
        con.close()

    assert frames.class_neighborhoods
    assert frames.baseline_neighborhoods

    class_rows = {
        (row["corpus_search_class_id"], row["query_song_id"], row["candidate_song_id"])
        for row in frames.class_neighborhoods
    }
    baseline_rows = {
        (row["backbone"], row["query_song_id"], row["candidate_song_id"]) for row in frames.baseline_neighborhoods
    }

    assert all(query != candidate for _class_id, query, candidate in class_rows)
    assert all(query != candidate for _backbone, query, candidate in baseline_rows)
    # Class-scoped rows carry no backbone; baseline rows carry no corpus class.
    assert not any("backbone" in row for row in frames.class_neighborhoods)
    assert all(row["backbone"] for row in frames.baseline_neighborhoods)
    assert class_rows
    assert baseline_rows
