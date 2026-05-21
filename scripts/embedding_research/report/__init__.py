"""Embedding research report package.

Public API:
    run(con, out_path=None)  — build and write the HTML report.
"""

from __future__ import annotations

import datetime
import logging
import pathlib
import time

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

_log = logging.getLogger(__name__)

from ._base import CSS
from ._binned import section_bin_diversity, section_threshold_sweep
from ._corpus import disc_score_warning, section_corpus
from ._efficiency import section_efficiency
from ._heads import (
    section_flat_head_comparison,
    section_head_agreement,
    section_head_heatmap,
    section_head_sim_corr,
    section_ptc_ctp_alignment,
    section_ptc_ctp_retrieval_comparison,
)
from ._retrieval import (
    query_binned,
    query_flat,
    section_per_backbone,
    section_unified_table,
)

_NAV_LINKS = [
    ("corpus", "Corpus"),
    ("unified-table", "Unified Ranking"),
    ("per-backbone", "Per-Backbone"),
    ("threshold-sweep", "Threshold Sweep"),
    ("bin-diversity", "Bin Diversity"),
    ("head-heatmap", "Head \u00d7 Backbone Heatmap"),
    ("head-sim-corr", "Head \u00d7 Sim Correlation"),
    ("head-agreement-rate", "Head Agreement Rate"),
    ("flat-head-compare", "PTC vs CTP"),
    ("head-agreement", "PTC/CTP Divergence"),
    ("ptc-ctp-retrieval", "PTC vs CTP Retrieval"),
    ("efficiency", "Efficiency"),
]


def _shell(nav_html: str, body_html: str, run_ts: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Embedding Research Report</title>
  <style>{CSS}</style>
</head>
<body>
  <nav>
    <h3>Sections</h3>
    {nav_html}
  </nav>
  <main>
    <h1>Embedding Research Report</h1>
    <p class="subtitle">Generated {run_ts}</p>
    {body_html}
  </main>
</body>
</html>
"""


def run(con: "duckdb.DuckDBPyConnection", out_path: pathlib.Path | None = None) -> None:
    if out_path is None:
        from ..config import REPORT_DIR
        out_path = REPORT_DIR / "report.html"

    flat_df = query_flat(con)
    binned_df = query_binned(con)

    nav_html = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in _NAV_LINKS)

    def _step(label: str, fn, *args, **kwargs):
        _log.info("  [report] %s ...", label)
        t = time.perf_counter()
        result = fn(*args, **kwargs)
        _log.info("  [report] %s  done  (%.1fs)", label, time.perf_counter() - t)
        return result

    body_html = (
        _step("disc_score_warning",        disc_score_warning,          con)
        + _step("corpus",                  section_corpus,              con)
        + _step("unified table",           section_unified_table,       flat_df, binned_df)
        + _step("per-backbone",            section_per_backbone,        flat_df, binned_df)
        + _step("threshold sweep",         section_threshold_sweep,     binned_df, flat_df)
        + _step("bin diversity",           section_bin_diversity,       con)
        + _step("head heatmap",            section_head_heatmap,        con)
        + _step("head sim corr",           section_head_sim_corr,       con)
        + _step("head agreement",          section_head_agreement,      con)
        + _step("flat head comparison",    section_flat_head_comparison, con)
        + _step("ptc/ctp alignment",       section_ptc_ctp_alignment,   con)
        + _step("ptc/ctp retrieval",       section_ptc_ctp_retrieval_comparison, con, flat_df)
        + _step("efficiency",              section_efficiency,          con)
    )

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = _shell(nav_html, body_html, run_ts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
