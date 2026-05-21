"""Tests for scripts.embedding_research.report HTML report helpers."""

from __future__ import annotations

import base64
from typing import cast

import duckdb
import pandas as pd
import pytest

from scripts.embedding_research import report

pytestmark = pytest.mark.unit


class TestFormatHelpers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "—"),
            (1.23456, "1.2346"),
            (7, "7"),
            ("abc", "abc"),
        ],
    )
    def test_fmt_formats_common_values(self, value: object, expected: str) -> None:
        assert report._fmt(value) == expected

    def test_table_returns_empty_markup_for_empty_rows(self) -> None:
        assert report._table([], title="Example") == ('<h4>Example</h4><p class="empty"><em>No data.</em></p>')

    def test_table_renders_headers_and_formatted_cells(self) -> None:
        html = report._table(
            [{"name": "alpha", "score": 1.23456, "missing": None}],
            title="Scores",
        )

        assert html.startswith("<h4>Scores</h4><table>")
        assert "<th>name</th>" in html
        assert "<th>score</th>" in html
        assert "<td>alpha</td>" in html
        assert "<td>1.2346</td>" in html
        assert "<td>—</td>" in html

    def test_shell_wraps_body_with_navigation(self) -> None:
        body = "<section id='demo'>demo</section>"

        html = report._shell(body)

        assert body in html
        assert "Embedding Research Report" in html
        assert "Unified flat + binned retrieval comparison across" in html
        for anchor, label in report._NAV_LINKS:
            assert f'href="#{anchor}"' in html
            assert label in html


class TestQueryHelpers:
    def test_table_exists_returns_true_for_existing_table(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE demo (id INTEGER)")

        assert report._table_exists(con, "demo") is True

    def test_table_exists_returns_false_for_missing_table(self) -> None:
        con = duckdb.connect(":memory:")

        assert report._table_exists(con, "missing_demo") is False

    def test_table_exists_returns_false_for_unexpected_errors(self) -> None:
        class BrokenConnection:
            def execute(self, _: str) -> None:
                raise RuntimeError("boom")

        assert report._table_exists(BrokenConnection(), "demo") is False

    def test_query_flat_returns_empty_df_when_table_missing(self) -> None:
        con = duckdb.connect(":memory:")

        result = report._query_flat(con)

        assert result.empty
        assert list(result.columns) == report._FLAT_COLUMNS

    def test_query_flat_returns_ranked_rows(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE retrieval_rows ("
            "backbone VARCHAR, strategy VARCHAR, sim_metric VARCHAR, k INTEGER, "
            "disc_score DOUBLE, map_k DOUBLE, mrr DOUBLE, ndcg_k DOUBLE)"
        )
        con.execute(
            "INSERT INTO retrieval_rows VALUES "
            "('effnet', 'flat_low', 'cosine', 10, 0.21, 0.11, 0.12, 0.13),"
            "('effnet', 'flat_best', 'cosine', 20, 0.92, 0.31, 0.32, 0.33)"
        )

        result = report._query_flat(con)

        assert result["strategy"].tolist() == ["flat_best", "flat_low"]
        assert result["disc_score"].tolist() == [0.92, 0.21]

    def test_query_binned_returns_empty_df_when_table_missing(self) -> None:
        con = duckdb.connect(":memory:")

        result = report._query_binned(con)

        assert result.empty
        assert list(result.columns) == report._BINNED_COLUMNS

    def test_query_binned_returns_ranked_rows(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE binned_retrieval_rows ("
            "backbone VARCHAR, bin_mode VARCHAR, std_thresh DOUBLE, rep_a VARCHAR, "
            "rep_b VARCHAR, sim_metric VARCHAR, agg_method VARCHAR, k INTEGER, "
            "disc_score DOUBLE, map_k DOUBLE, mrr DOUBLE, ndcg_k DOUBLE)"
        )
        con.execute(
            "INSERT INTO binned_retrieval_rows VALUES "
            "('effnet', 'soft', 2.0, 'r3', 'r4', 'cosine', 'max', 5, 0.12, 0.11, 0.10, 0.09),"
            "('effnet', 'hard', 1.5, 'r1', 'r2', 'cosine', 'mean', 10, 0.88, 0.21, 0.22, 0.23)"
        )

        result = report._query_binned(con)

        assert result["bin_mode"].tolist() == ["hard", "soft"]
        assert result["disc_score"].tolist() == [0.88, 0.12]

    def test_query_flat_returns_empty_df_when_query_raises_catalog_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class BrokenAfterExists:
            def execute(self, sql: str):
                raise duckdb.CatalogException("no catalog")

        monkeypatch.setattr(report, "_table_exists", lambda _con, _name: True)

        result = report._query_flat(BrokenAfterExists())

        assert result.empty
        assert list(result.columns) == report._FLAT_COLUMNS

    def test_query_binned_returns_empty_df_when_query_raises_catalog_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class BrokenAfterExists:
            def execute(self, sql: str):
                raise duckdb.CatalogException("no catalog")

        monkeypatch.setattr(report, "_table_exists", lambda _con, _name: True)

        result = report._query_binned(BrokenAfterExists())

        assert result.empty
        assert list(result.columns) == report._BINNED_COLUMNS

    def test_sort_backbones_uses_config_order_then_sorted_extras(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(report, "BACKBONES", ["b2", "b1"])
        flat_df = pd.DataFrame([{"backbone": "b1"}, {"backbone": "zzz"}])
        binned_df = pd.DataFrame([{"backbone": "b2"}, {"backbone": "aaa"}])

        result = report._sort_backbones(flat_df, binned_df)

        assert result == ["b2", "b1", "aaa", "zzz"]

    def test_binned_config_formats_threshold_and_missing_threshold(self) -> None:
        row = pd.Series(
            {
                "bin_mode": "hard",
                "std_thresh": 1.5,
                "rep_a": "r1",
                "rep_b": "r2",
                "agg_method": "mean",
            }
        )
        missing_thresh = pd.Series(
            {
                "bin_mode": "soft",
                "std_thresh": float("nan"),
                "rep_a": "x",
                "rep_b": "y",
                "agg_method": "max",
            }
        )

        assert report._binned_config(row) == "hard/1.5/r1xr2/mean"
        assert report._binned_config(missing_thresh) == "soft/—/xxy/max"


class TestSectionRendering:
    def test_section_unified_table_returns_empty_message_when_no_frames(self) -> None:
        html = report._section_unified_table(
            report._empty_df(report._FLAT_COLUMNS),
            report._empty_df(report._BINNED_COLUMNS),
        )

        assert "No retrieval data is available yet." in html

    def test_section_unified_table_combines_and_sorts_flat_and_binned_rows(self) -> None:
        flat_df = pd.DataFrame(
            [
                {
                    "backbone": "effnet",
                    "strategy": "flat_best",
                    "sim_metric": "cosine",
                    "k": 10,
                    "disc_score": 0.42,
                    "map_k": 0.1,
                    "mrr": 0.2,
                    "ndcg_k": 0.3,
                }
            ]
        )
        binned_df = pd.DataFrame(
            [
                {
                    "backbone": "effnet",
                    "bin_mode": "hard",
                    "std_thresh": 1.5,
                    "rep_a": "r1",
                    "rep_b": "r2",
                    "sim_metric": "cosine",
                    "agg_method": "agg",
                    "k": 20,
                    "disc_score": 0.91,
                    "map_k": 0.4,
                    "mrr": 0.5,
                    "ndcg_k": 0.6,
                }
            ]
        )

        html = report._section_unified_table(flat_df, binned_df)

        assert "hard/1.5/r1xr2/agg" in html
        assert "flat_best" in html
        assert html.index("hard/1.5/r1xr2/agg") < html.index("flat_best")

    def test_section_per_backbone_returns_empty_message_when_no_backbones(self) -> None:
        html = report._section_per_backbone(
            report._empty_df(report._FLAT_COLUMNS),
            report._empty_df(report._BINNED_COLUMNS),
        )

        assert "No backbone comparisons are available yet." in html

    def test_section_per_backbone_uses_best_flat_and_binned_rows(self) -> None:
        flat_df = pd.DataFrame(
            [
                {
                    "backbone": "effnet",
                    "strategy": "flat_low",
                    "sim_metric": "cosine",
                    "k": 10,
                    "disc_score": 0.20,
                    "map_k": 0.1,
                    "mrr": 0.1,
                    "ndcg_k": 0.1,
                },
                {
                    "backbone": "effnet",
                    "strategy": "flat_best",
                    "sim_metric": "cosine",
                    "k": 20,
                    "disc_score": 0.80,
                    "map_k": 0.2,
                    "mrr": 0.2,
                    "ndcg_k": 0.2,
                },
            ]
        )
        binned_df = pd.DataFrame(
            [
                {
                    "backbone": "effnet",
                    "bin_mode": "hard",
                    "std_thresh": 1.5,
                    "rep_a": "r1",
                    "rep_b": "r2",
                    "sim_metric": "cosine",
                    "agg_method": "mean",
                    "k": 30,
                    "disc_score": 0.90,
                    "map_k": 0.3,
                    "mrr": 0.3,
                    "ndcg_k": 0.3,
                },
                {
                    "backbone": "mfcc",
                    "bin_mode": "soft",
                    "std_thresh": 2.0,
                    "rep_a": "a",
                    "rep_b": "b",
                    "sim_metric": "l2",
                    "agg_method": "max",
                    "k": 15,
                    "disc_score": 0.50,
                    "map_k": 0.4,
                    "mrr": 0.4,
                    "ndcg_k": 0.4,
                },
            ]
        )

        html = report._section_per_backbone(flat_df, binned_df)

        assert "<h3>effnet</h3>" in html
        assert "flat_best" in html
        assert "flat_low" not in html
        assert "hard/1.5/r1xr2/mean" in html
        assert "<h3>mfcc</h3>" in html
        assert "soft/2/axb/max" in html

    def test_threshold_rows_groups_max_score_and_sorts_nan_last(self) -> None:
        group = pd.DataFrame(
            [
                {"std_thresh": 2.0, "disc_score": 0.3},
                {"std_thresh": 1.0, "disc_score": 0.8},
                {"std_thresh": 1.0, "disc_score": 0.9},
                {"std_thresh": float("nan"), "disc_score": 0.2},
            ]
        )

        rows = report._threshold_rows(group)

        assert rows["std_thresh"].iloc[0] == 1.0
        assert rows["disc_score"].iloc[0] == 0.9
        assert rows["std_thresh"].iloc[1] == 2.0
        assert pd.isna(rows["std_thresh"].iloc[2])

    def test_threshold_chart_returns_base64_png_img_tag(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class FakeAxes:
            def __init__(self) -> None:
                self.xlabel: str | None = None
                self.ylabel: str | None = None
                self.title: str | None = None
                self.grid_call: tuple[bool, float] | None = None
                self.plot_data: tuple[list[float], list[float]] | None = None

            def plot(
                self,
                xs: pd.Series,
                ys: pd.Series,
                marker: str,
                color: str,
            ) -> None:
                assert marker == "o"
                assert color == "#7ec8e3"
                self.plot_data = (list(xs), list(ys))

            def set_xlabel(self, label: str) -> None:
                self.xlabel = label

            def set_ylabel(self, label: str) -> None:
                self.ylabel = label

            def set_title(self, title: str) -> None:
                self.title = title

            def grid(self, enabled: bool, alpha: float) -> None:
                self.grid_call = (enabled, alpha)

        class FakeFigure:
            def __init__(self) -> None:
                self.tight_layout_called = False

            def tight_layout(self) -> None:
                self.tight_layout_called = True

            def savefig(
                self,
                buf,
                format: str,
                dpi: int,
                bbox_inches: str,
            ) -> None:
                assert format == "png"
                assert dpi == 120
                assert bbox_inches == "tight"
                buf.write(b"fake-png")

        class FakePyplot:
            def __init__(self) -> None:
                self.axes = FakeAxes()
                self.figure = FakeFigure()
                self.closed: list[FakeFigure] = []
                self.figsize: tuple[int, int] | None = None

            def subplots(self, figsize: tuple[int, int]) -> tuple[FakeFigure, FakeAxes]:
                self.figsize = figsize
                return self.figure, self.axes

            def close(self, fig: FakeFigure) -> None:
                self.closed.append(fig)

        fake_plt = FakePyplot()
        monkeypatch.setattr(report, "plt", fake_plt, raising=False)
        rows = pd.DataFrame([{"std_thresh": 1.0, "disc_score": 0.5}, {"std_thresh": 2.0, "disc_score": 0.8}])

        html = report._threshold_chart("effnet", "hard", rows)

        assert fake_plt.figsize == (6, 3)
        assert fake_plt.axes.xlabel == "std_thresh"
        assert fake_plt.axes.ylabel == "best disc_score"
        assert fake_plt.axes.title == "effnet / hard"
        assert fake_plt.axes.grid_call == (True, 0.2)
        assert fake_plt.axes.plot_data == ([1.0, 2.0], [0.5, 0.8])
        assert fake_plt.figure.tight_layout_called is True
        assert fake_plt.closed == [fake_plt.figure]
        assert base64.b64encode(b"fake-png").decode() in html
        assert 'alt="threshold sweep effnet/hard"' in html

    def test_section_threshold_sweep_returns_empty_message_for_empty_df(self) -> None:
        html = report._section_threshold_sweep(report._empty_df(report._BINNED_COLUMNS))

        assert "No binned data yet." in html

    def test_section_threshold_sweep_falls_back_to_table_when_plotting_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(report, "_HAS_MPL", False)
        binned_df = pd.DataFrame(
            [
                {
                    "backbone": "effnet",
                    "bin_mode": "hard",
                    "std_thresh": 1.0,
                    "rep_a": "r1",
                    "rep_b": "r2",
                    "sim_metric": "cosine",
                    "agg_method": "mean",
                    "k": 10,
                    "disc_score": 0.5,
                    "map_k": 0.1,
                    "mrr": 0.2,
                    "ndcg_k": 0.3,
                },
                {
                    "backbone": "mfcc",
                    "bin_mode": "soft",
                    "std_thresh": 2.0,
                    "rep_a": "a",
                    "rep_b": "b",
                    "sim_metric": "l2",
                    "agg_method": "max",
                    "k": 20,
                    "disc_score": 0.7,
                    "map_k": 0.2,
                    "mrr": 0.3,
                    "ndcg_k": 0.4,
                },
            ]
        )

        html = report._section_threshold_sweep(binned_df)

        assert "<details open>" in html
        assert html.count("<details") == 2
        assert "<summary>effnet / hard</summary>" in html
        assert "<summary>mfcc / soft</summary>" in html
        assert "<table>" in html
        assert "data:image/png;base64" not in html

    def test_section_threshold_sweep_renders_chart_when_plotting_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(report, "_HAS_MPL", True)
        monkeypatch.setattr(report, "_threshold_chart", lambda *_args: "<img-stub/>")
        binned_df = pd.DataFrame(
            [
                {
                    "backbone": "effnet",
                    "bin_mode": "hard",
                    "std_thresh": 1.0,
                    "rep_a": "r1",
                    "rep_b": "r2",
                    "sim_metric": "cosine",
                    "agg_method": "mean",
                    "k": 10,
                    "disc_score": 0.5,
                    "map_k": 0.1,
                    "mrr": 0.2,
                    "ndcg_k": 0.3,
                },
                {
                    "backbone": "effnet",
                    "bin_mode": "hard",
                    "std_thresh": 2.0,
                    "rep_a": "r1",
                    "rep_b": "r2",
                    "sim_metric": "cosine",
                    "agg_method": "mean",
                    "k": 20,
                    "disc_score": 0.7,
                    "map_k": 0.2,
                    "mrr": 0.3,
                    "ndcg_k": 0.4,
                },
            ]
        )

        html = report._section_threshold_sweep(binned_df)

        assert "<img-stub/>" in html
        assert "<table>" not in html

    def test_section_head_agreement_returns_placeholder_when_table_missing(self) -> None:
        con = duckdb.connect(":memory:")

        html = report._section_head_agreement(con)

        assert "Head agreement data not available yet." in html

    def test_section_head_agreement_returns_placeholder_for_empty_table(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE head_agreement_rows ("
            "backbone VARCHAR, head VARCHAR, bin_mode VARCHAR, std_thresh DOUBLE, "
            "agreement_rate DOUBLE, n_songs INTEGER)"
        )

        html = report._section_head_agreement(con)

        assert "Head agreement data not available yet." in html

    def test_section_head_agreement_returns_placeholder_when_query_raises_catalog_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class BrokenAfterExists:
            def execute(self, sql: str):
                raise duckdb.CatalogException("no catalog")

        monkeypatch.setattr(report, "_table_exists", lambda _con, _name: True)

        html = report._section_head_agreement(BrokenAfterExists())

        assert "Head agreement data not available yet." in html

    def test_section_head_agreement_renders_grouped_tables(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE head_agreement_rows ("
            "backbone VARCHAR, head VARCHAR, bin_mode VARCHAR, std_thresh DOUBLE, "
            "agreement_rate DOUBLE, n_songs INTEGER)"
        )
        con.execute(
            "INSERT INTO head_agreement_rows VALUES "
            "('effnet', 'linear', 'hard', 1.5, 0.90, 25),"
            "('effnet', 'linear', 'soft', 2.0, 0.85, 30),"
            "('mfcc', 'mlp', 'hard', 1.0, 0.80, 18)"
        )

        html = report._section_head_agreement(con)

        assert "<h3>effnet / linear</h3>" in html
        assert "<h3>mfcc / mlp</h3>" in html
        assert "0.9000" in html
        assert "30" in html


class TestRun:
    def test_run_builds_and_writes_report_html(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        output_dir = tmp_path / "nested" / "reports"
        con = cast("duckdb.DuckDBPyConnection", object())
        calls: list[tuple[str, object]] = []

        def fake_query_flat(got_con: object) -> str:
            calls.append(("query_flat", got_con))
            return "flat-df"

        def fake_query_binned(got_con: object) -> str:
            calls.append(("query_binned", got_con))
            return "binned-df"

        def fake_section_unified(flat_df: str, binned_df: str) -> str:
            calls.append(("section_unified", (flat_df, binned_df)))
            return "<unified/>"

        def fake_section_per_backbone(flat_df: str, binned_df: str) -> str:
            calls.append(("section_per_backbone", (flat_df, binned_df)))
            return "<per-backbone/>"

        def fake_section_threshold_sweep(binned_df: str) -> str:
            calls.append(("section_threshold_sweep", binned_df))
            return "<threshold-sweep/>"

        def fake_section_head_agreement(got_con: object) -> str:
            calls.append(("section_head_agreement", got_con))
            return "<head-agreement/>"

        def fake_shell(body: str) -> str:
            calls.append(("shell", body))
            return f"<html>{body}</html>"

        monkeypatch.setattr(report, "REPORT_DIR", output_dir)
        monkeypatch.setattr(report, "_query_flat", fake_query_flat)
        monkeypatch.setattr(report, "_query_binned", fake_query_binned)
        monkeypatch.setattr(report, "_section_unified_table", fake_section_unified)
        monkeypatch.setattr(report, "_section_per_backbone", fake_section_per_backbone)
        monkeypatch.setattr(report, "_section_threshold_sweep", fake_section_threshold_sweep)
        monkeypatch.setattr(report, "_section_head_agreement", fake_section_head_agreement)
        monkeypatch.setattr(report, "_shell", fake_shell)

        report.run(con)

        assert output_dir.joinpath("index.html").read_text(encoding="utf-8") == (
            "<html><unified/><per-backbone/><threshold-sweep/><head-agreement/></html>"
        )
        assert calls == [
            ("query_flat", con),
            ("query_binned", con),
            ("section_unified", ("flat-df", "binned-df")),
            ("section_per_backbone", ("flat-df", "binned-df")),
            ("section_threshold_sweep", "binned-df"),
            ("section_head_agreement", con),
            (
                "shell",
                "<unified/><per-backbone/><threshold-sweep/><head-agreement/>",
            ),
        ]
