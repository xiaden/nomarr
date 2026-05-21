"""Tests for query helper functions added to scripts/embedding_research/db.py."""

import duckdb
import pytest

from scripts.embedding_research.db import (
    query_analysis_done,
    query_binned_analysis_done,
    query_binned_classify_done,
    query_binned_configs,
    query_classify_done,
    query_embedded_configs,
)


class TestQueryEmbeddedConfigs:
    @pytest.mark.unit
    def test_returns_empty_set_when_table_missing(self) -> None:
        con = duckdb.connect(":memory:")
        assert query_embedded_configs(con) == set()

    @pytest.mark.unit
    def test_returns_all_configs_when_no_filter(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE pooled_vecs (backbone VARCHAR, strategy VARCHAR)")
        con.execute("INSERT INTO pooled_vecs VALUES ('effnet', 'mean'), ('mfcc', 'max')")
        result = query_embedded_configs(con)
        assert result == {("effnet", "mean"), ("mfcc", "max")}

    @pytest.mark.unit
    def test_filters_by_backbone(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE pooled_vecs (backbone VARCHAR, strategy VARCHAR)")
        con.execute("INSERT INTO pooled_vecs VALUES ('effnet', 'mean'), ('mfcc', 'max')")
        result = query_embedded_configs(con, backbone="effnet")
        assert result == {("effnet", "mean")}

    @pytest.mark.unit
    def test_returns_distinct_tuples(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE pooled_vecs (backbone VARCHAR, strategy VARCHAR)")
        con.execute("INSERT INTO pooled_vecs VALUES ('effnet', 'mean'), ('effnet', 'mean'), ('mfcc', 'max')")
        result = query_embedded_configs(con)
        assert result == {("effnet", "mean"), ("mfcc", "max")}

    @pytest.mark.unit
    def test_values_coerced_to_str(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE pooled_vecs (backbone VARCHAR, strategy VARCHAR)")
        con.execute("INSERT INTO pooled_vecs VALUES ('b1', 's1')")
        result = query_embedded_configs(con)
        (backbone, strategy) = next(iter(result))
        assert isinstance(backbone, str)
        assert isinstance(strategy, str)


class TestQueryAnalysisDone:
    @pytest.mark.unit
    def test_returns_empty_set_when_table_missing(self) -> None:
        con = duckdb.connect(":memory:")
        assert query_analysis_done(con) == set()

    @pytest.mark.unit
    def test_returns_correct_tuples(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE retrieval_rows (backbone VARCHAR, strategy VARCHAR, sim_metric VARCHAR, k INTEGER)")
        con.execute("INSERT INTO retrieval_rows VALUES ('effnet', 'mean', 'cosine', 10)")
        result = query_analysis_done(con)
        assert result == {("effnet", "mean", "cosine", 10)}

    @pytest.mark.unit
    def test_k_cast_to_int(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE retrieval_rows (backbone VARCHAR, strategy VARCHAR, sim_metric VARCHAR, k INTEGER)")
        con.execute("INSERT INTO retrieval_rows VALUES ('b', 's', 'm', 5)")
        result = query_analysis_done(con)
        (_, _, _, k) = next(iter(result))
        assert isinstance(k, int)


class TestQueryClassifyDone:
    @pytest.mark.unit
    def test_returns_empty_set_when_table_missing(self) -> None:
        con = duckdb.connect(":memory:")
        assert query_classify_done(con) == set()

    @pytest.mark.unit
    def test_returns_correct_tuples(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE head_results (song_id VARCHAR, backbone VARCHAR, head VARCHAR, strategy VARCHAR, pathway VARCHAR)"
        )
        con.execute("INSERT INTO head_results VALUES ('s1', 'effnet', 'linear', 'mean', 'direct')")
        result = query_classify_done(con)
        assert result == {("s1", "effnet", "linear", "mean", "direct")}

    @pytest.mark.unit
    def test_values_coerced_to_str(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE head_results (song_id VARCHAR, backbone VARCHAR, head VARCHAR, strategy VARCHAR, pathway VARCHAR)"
        )
        con.execute("INSERT INTO head_results VALUES ('id1', 'b', 'h', 's', 'p')")
        result = query_classify_done(con)
        row = next(iter(result))
        assert all(isinstance(v, str) for v in row)


class TestQueryBinnedConfigs:
    @pytest.mark.unit
    def test_returns_empty_set_when_cache_empty(self, monkeypatch) -> None:
        from scripts.embedding_research.strategy_binned import _cache as binned_cache

        monkeypatch.setattr(binned_cache, "list_configs", lambda _backbone=None: set())
        assert query_binned_configs() == set()

    @pytest.mark.unit
    def test_returns_all_configs_when_no_filter(self, monkeypatch) -> None:
        from scripts.embedding_research.strategy_binned import _cache as binned_cache

        fake = {("effnet", "hard", 1.5), ("mfcc", "soft", 2.0)}
        monkeypatch.setattr(
            binned_cache,
            "list_configs",
            lambda backbone=None: {c for c in fake if backbone is None or c[0] == backbone},
        )
        assert query_binned_configs() == fake

    @pytest.mark.unit
    def test_filters_by_backbone(self, monkeypatch) -> None:
        from scripts.embedding_research.strategy_binned import _cache as binned_cache

        fake = {("effnet", "hard", 1.5), ("mfcc", "soft", 2.0)}
        monkeypatch.setattr(
            binned_cache,
            "list_configs",
            lambda backbone=None: {c for c in fake if backbone is None or c[0] == backbone},
        )
        assert query_binned_configs(backbone="effnet") == {("effnet", "hard", 1.5)}

    @pytest.mark.unit
    def test_std_thresh_is_float(self, monkeypatch) -> None:
        from scripts.embedding_research.strategy_binned import _cache as binned_cache

        monkeypatch.setattr(binned_cache, "list_configs", lambda _backbone=None: {("b", "m", 1.0)})
        result = query_binned_configs()
        (_, _, thresh) = next(iter(result))
        assert isinstance(thresh, float)


class TestQueryBinnedAnalysisDone:
    @pytest.mark.unit
    def test_returns_empty_set_when_table_missing(self) -> None:
        con = duckdb.connect(":memory:")
        assert query_binned_analysis_done(con) == set()

    @pytest.mark.unit
    def test_returns_correct_8_tuple(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE binned_retrieval_rows "
            "(backbone VARCHAR, bin_mode VARCHAR, std_thresh DOUBLE, rep_a VARCHAR, rep_b VARCHAR, sim_metric VARCHAR, agg_method VARCHAR, k INTEGER)"
        )
        con.execute(
            "INSERT INTO binned_retrieval_rows VALUES ('effnet', 'hard', 1.5, 'r1', 'r2', 'cosine', 'mean', 10)"
        )
        result = query_binned_analysis_done(con)
        assert result == {("effnet", "hard", 1.5, "r1", "r2", "cosine", "mean", 10)}

    @pytest.mark.unit
    def test_type_coercions(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE binned_retrieval_rows "
            "(backbone VARCHAR, bin_mode VARCHAR, std_thresh DOUBLE, rep_a VARCHAR, rep_b VARCHAR, sim_metric VARCHAR, agg_method VARCHAR, k INTEGER)"
        )
        con.execute("INSERT INTO binned_retrieval_rows VALUES ('b', 'm', 2.5, 'a', 'b2', 's', 'ag', 5)")
        result = query_binned_analysis_done(con)
        row = next(iter(result))
        assert isinstance(row[2], float)  # std_thresh
        assert isinstance(row[7], int)  # k


class TestQueryBinnedClassifyDone:
    @pytest.mark.unit
    def test_returns_empty_set_when_table_missing(self) -> None:
        con = duckdb.connect(":memory:")
        assert query_binned_classify_done(con) == set()

    @pytest.mark.unit
    def test_returns_correct_6_tuple(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE binned_head_results "
            "(song_id VARCHAR, backbone VARCHAR, head VARCHAR, bin_mode VARCHAR, std_thresh DOUBLE, bin_id INTEGER)"
        )
        con.execute("INSERT INTO binned_head_results VALUES ('s1', 'effnet', 'linear', 'hard', 1.5, 3)")
        result = query_binned_classify_done(con)
        assert result == {("s1", "effnet", "linear", "hard", 1.5, 3)}

    @pytest.mark.unit
    def test_type_coercions(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE binned_head_results "
            "(song_id VARCHAR, backbone VARCHAR, head VARCHAR, bin_mode VARCHAR, std_thresh DOUBLE, bin_id INTEGER)"
        )
        con.execute("INSERT INTO binned_head_results VALUES ('x', 'b', 'h', 'm', 2.0, 7)")
        result = query_binned_classify_done(con)
        row = next(iter(result))
        assert isinstance(row[4], float)  # std_thresh
        assert isinstance(row[5], int)  # bin_id
