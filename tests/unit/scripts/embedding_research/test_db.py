"""Unit tests for embedding research DuckDB query helpers."""

from __future__ import annotations

import duckdb
import pytest

from scripts.embedding_research import db


@pytest.fixture
def con():
    """Return an isolated in-memory DuckDB connection for each test."""
    connection = duckdb.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.unit
class TestEmbeddingResearchQueryHelpers:
    """Covers cache-check helpers used by the embedding research scripts."""

    @pytest.mark.parametrize(
        ("query_fn", "kwargs"),
        [
            (db.query_embedded_configs, {}),
            (db.query_analysis_done, {}),
            (db.query_binned_analysis_done, {}),
            (db.query_classify_done, {}),
            (db.query_binned_classify_done, {}),
        ],
    )
    def test_returns_empty_set_when_source_table_is_missing(self, con, query_fn, kwargs) -> None:
        """Missing source tables should be treated as no cached work."""
        assert query_fn(con, **kwargs) == set()

    def test_query_binned_configs_returns_empty_set_when_cache_empty(self, con, monkeypatch) -> None:
        """query_binned_configs returns empty set when cache has no files."""
        from scripts.embedding_research.strategy_binned import _cache as binned_cache

        monkeypatch.setattr(binned_cache, "list_configs", lambda _backbone=None: set())
        assert db.query_binned_configs() == set()

    def test_query_embedded_configs_returns_distinct_configs_and_filters_backbone(self, con) -> None:
        """Embedded config queries should deduplicate rows and honor the backbone filter."""
        con.execute("CREATE TABLE pooled_vecs (song_id TEXT, backbone TEXT, strategy TEXT)")
        con.executemany(
            "INSERT INTO pooled_vecs VALUES (?, ?, ?)",
            [
                ("song-1", "effnet", "median"),
                ("song-2", "effnet", "median"),
                ("song-3", "effnet", "mean"),
                ("song-4", "musicnn", "median"),
            ],
        )

        assert db.query_embedded_configs(con) == {
            ("effnet", "mean"),
            ("effnet", "median"),
            ("musicnn", "median"),
        }
        assert db.query_embedded_configs(con, backbone="effnet") == {
            ("effnet", "mean"),
            ("effnet", "median"),
        }

    def test_query_binned_configs_returns_distinct_configs_and_filters_backbone(
        self, con, monkeypatch, tmp_path
    ) -> None:
        """Binned config queries should delegate to the filesystem cache."""
        from scripts.embedding_research.strategy_binned import _cache as binned_cache

        fake_configs = {
            ("effnet", "quantile", 1.0),
            ("effnet", "std", 0.5),
            ("musicnn", "std", 0.25),
        }
        monkeypatch.setattr(
            binned_cache,
            "list_configs",
            lambda backbone=None: {c for c in fake_configs if backbone is None or c[0] == backbone},
        )

        assert db.query_binned_configs() == fake_configs
        assert db.query_binned_configs(backbone="effnet") == {
            ("effnet", "quantile", 1.0),
            ("effnet", "std", 0.5),
        }

    def test_query_analysis_done_returns_expected_typed_tuples(self, con) -> None:
        """Analysis-complete queries should return unique tuple keys with integer k values."""
        con.execute("CREATE TABLE retrieval_rows (backbone TEXT, strategy TEXT, sim_metric TEXT, k INTEGER)")
        con.executemany(
            "INSERT INTO retrieval_rows VALUES (?, ?, ?, ?)",
            [
                ("effnet", "median", "cosine", 10),
                ("effnet", "median", "cosine", 10),
                ("musicnn", "mean", "l2", 20),
            ],
        )

        assert db.query_analysis_done(con) == {
            ("effnet", "median", "cosine", 10),
            ("musicnn", "mean", "l2", 20),
        }

    def test_query_binned_analysis_done_returns_expected_typed_tuples(self, con) -> None:
        """Binned analysis-complete queries should preserve the full cache key shape."""
        con.execute(
            "CREATE TABLE binned_retrieval_rows ("
            "backbone TEXT, bin_mode TEXT, std_thresh DOUBLE, rep_a TEXT, rep_b TEXT, "
            "sim_metric TEXT, agg_method TEXT, k INTEGER)"
        )
        con.executemany(
            "INSERT INTO binned_retrieval_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("effnet", "std", 0.5, "mean", "median", "cosine", "avg", 10),
                ("effnet", "std", 0.5, "mean", "median", "cosine", "avg", 10),
                ("musicnn", "quantile", 1.0, "max", "min", "l2", "max", 5),
            ],
        )

        assert db.query_binned_analysis_done(con) == {
            ("effnet", "std", 0.5, "mean", "median", "cosine", "avg", 10),
            ("musicnn", "quantile", 1.0, "max", "min", "l2", "max", 5),
        }

    def test_query_classify_done_returns_expected_typed_tuples(self, con) -> None:
        """Classification-complete queries should return unique song/head cache keys."""
        con.execute("CREATE TABLE head_results (song_id TEXT, backbone TEXT, head TEXT, strategy TEXT, pathway TEXT)")
        con.executemany(
            "INSERT INTO head_results VALUES (?, ?, ?, ?, ?)",
            [
                ("song-1", "effnet", "mood", "median", "ptc"),
                ("song-1", "effnet", "mood", "median", "ptc"),
                ("song-2", "musicnn", "genre", "mean", "ctp"),
            ],
        )

        assert db.query_classify_done(con) == {
            ("song-1", "effnet", "mood", "median", "ptc"),
            ("song-2", "musicnn", "genre", "mean", "ctp"),
        }

    def test_query_binned_classify_done_returns_expected_typed_tuples(self, con) -> None:
        """Binned classification-complete queries should include threshold and bin id."""
        con.execute(
            "CREATE TABLE binned_head_results ("
            "song_id TEXT, backbone TEXT, head TEXT, bin_mode TEXT, std_thresh DOUBLE, bin_id INTEGER)"
        )
        con.executemany(
            "INSERT INTO binned_head_results VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("song-1", "effnet", "mood", "std", 0.5, 0),
                ("song-1", "effnet", "mood", "std", 0.5, 0),
                ("song-2", "musicnn", "genre", "quantile", 1.0, 3),
            ],
        )

        assert db.query_binned_classify_done(con) == {
            ("song-1", "effnet", "mood", "std", 0.5, 0),
            ("song-2", "musicnn", "genre", "quantile", 1.0, 3),
        }
