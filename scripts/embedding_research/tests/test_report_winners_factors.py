"""Winner/baseline row projection factors and class-scoped uniqueness."""

from __future__ import annotations

from types import SimpleNamespace

from scripts.embedding_research.report._winners import (
    BASELINE_NEIGHBORHOOD_COLUMNS,
    CLASS_NEIGHBORHOOD_COLUMNS,
    baseline_neighborhood_rows,
    class_neighborhood_rows,
)


def _frames() -> SimpleNamespace:
    return SimpleNamespace(
        class_neighborhoods=(
            {
                "corpus_search_class_id": "class:t-000",
                "query_song_id": "s1",
                "candidate_song_id": "s2",
                "rank": 0,
                "score": 0.9,
            },
            {
                "corpus_search_class_id": "class:t-001",
                "query_song_id": "s1",
                "candidate_song_id": "s2",
                "rank": 0,
                "score": 0.8,
            },
        ),
        baseline_neighborhoods=(
            {
                "backbone": "effnet",
                "query_song_id": "s1",
                "candidate_song_id": "s2",
                "rank": 0,
                "score": 0.7,
            },
        ),
    )


def test_class_and_baseline_projections_have_exact_columns():
    frames = _frames()
    class_rows = class_neighborhood_rows(frames)
    baseline_rows = baseline_neighborhood_rows(frames)

    assert list(class_rows[0]) == CLASS_NEIGHBORHOOD_COLUMNS
    assert list(baseline_rows[0]) == BASELINE_NEIGHBORHOOD_COLUMNS


def test_neighborhood_uniqueness_is_class_scoped():
    frames = _frames()
    # The same (query, candidate) under two different classes is never collapsed.
    assert len(class_neighborhood_rows(frames)) == 2

    duplicate = SimpleNamespace(
        class_neighborhoods=(
            {
                "corpus_search_class_id": "class:t-000",
                "query_song_id": "s1",
                "candidate_song_id": "s2",
                "rank": 0,
                "score": 0.9,
            },
            {
                "corpus_search_class_id": "class:t-000",
                "query_song_id": "s1",
                "candidate_song_id": "s2",
                "rank": 1,
                "score": 0.5,
            },
        ),
        baseline_neighborhoods=(),
    )
    assert len(class_neighborhood_rows(duplicate)) == 1


def test_empty_inputs_return_empty_projections():
    assert class_neighborhood_rows(None) == []
    assert baseline_neighborhood_rows(None) == []
