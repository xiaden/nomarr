"""Generate a deterministic in-memory fixture report through the REAL report builders.

This environment has no ONNX models (``/app/models`` is absent) and no audio corpus
(``/workspace/.devcontainer/test-media`` is empty), so the real ingest->embed->stratify->
segment->classify->analyze pipeline cannot run end-to-end.  The pre-existing
``research.duckdb`` is stale for the current report contract: its ``analyze_metrics``
lacks the explicit ``global_pool:{backbone}:medoid`` baseline rows and every weighted
directional aggregate (``target_weighted`` / ``bidirectional_weighted`` /
``normalized_mean_pair_weighted``), and its per-backbone row counts (100 vs 116) show
non-matching corpora — so it cannot produce a valid report.

This script therefore builds a **fully deterministic in-memory DuckDB** feeding the
REAL report entry point (``report.run``) and every section builder with:

* EffNet **and** MusicNN rows (independent populations),
* explicit ``global_pool:{backbone}:medoid`` baseline rows per backbone,
* the three weighted directional aggregate strategies,
* per-backbone matching-corpus manifests (corpus_hash + corpus_size),
* winner/delta and factor-summary tables (computed by the real builders),
* a complete supporting set of corpus / timing / segmentation / head / truncation rows
  so every con-based section renders.

It then writes ``report.json`` + ``report.html`` to the configured report output
directory (``{OUTPUT_ROOT}/report``).

.. warning::
   This is a deterministic DEMO / fixture report.  Every metric value is synthetic.
   It must NOT be read as a measured corpus conclusion.  No embed / segment /
   classify / analyze step was executed.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import duckdb

# Make the repository-root ``scripts`` package importable, like run.py does.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.embedding_research.config import REPORT_DIR
from scripts.embedding_research.corpus import MatchingCorpusManifest
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.report import run as report_run

BACKBONES = ["effnet", "musicnn"]

FLAT_STRATEGIES = ["medoid", "mean", "max_norm", "l2norm_mean", "trimmed_10"]
PTC_BIN_MODES = ["temporal_global", "temporal_perdim"]
PTC_THRESHOLDS = [1.0, 1.1]
CTP_HEADS = ["genre", "mood_happy"]
CTP_THRESHOLDS = [0.10]
AGG_METHODS = ["target_weighted", "bidirectional_weighted", "normalized_mean_pair_weighted"]
REP_COMBOS = [("medoid", "medoid"), ("median", "median")]
K_VALUES = [5, 10]
SIM_METRIC = "cosine"

# Metric columns inserted into analyze_metrics (drives the decoded pivot).
METRICS = [
    "disc_general",
    "disc_artist",
    "disc_genre",
    "disc_head",
    "disc_score",
    "mean_within",
    "mean_cross",
    "map_k",
    "mrr",
    "ndcg_k",
    "recall_k",
    "recall_k_genre",
    "precision_k_genre",
    "map_k_artist",
    "ndcg_k_artist",
    "recall_k_artist",
    "map_k_genre",
    "mrr_genre",
    "ndcg_k_genre",
    "map_k_head",
    "mrr_head",
    "ndcg_k_head",
    "recall_k_head",
    "map_k_general",
    "flat_binned_spearman",
    "flat_binned_beneficial_reorder_rate",
]


# The metric family a column belongs to (used to pick a deterministic winner so
# every aggregate wins at least one family -> a non-trivial factor summary).
def _metric_family(metric: str) -> str:
    if metric.startswith("disc_"):
        return "discrimination"
    if metric.startswith("map"):
        return "MAP"
    if metric.startswith("mrr"):
        return "MRR"
    if metric.startswith("ndcg"):
        return "NDCG"
    if metric.startswith(("recall", "precision")):
        return "Recall"
    if metric.startswith(("mean", "var", "kurt")):
        return "similarity"
    return "other"


# The aggregate engineered to win each metric family.
_FAMILY_WINNER: dict[str, str] = {
    "MAP": "target_weighted",
    "MRR": "bidirectional_weighted",
    "NDCG": "normalized_mean_pair_weighted",
    "Recall": "target_weighted",
    "discrimination": "normalized_mean_pair_weighted",
}


# Deterministic per-backbone base values for each metric family + K.
def _base_value(backbone: str, family: str, k: int) -> float:
    seed = int(hashlib.sha256(f"{backbone}|{family}|{k}".encode()).hexdigest()[:8], 16)
    return 0.35 + 0.35 * (seed % 1000) / 1000.0  # deterministic in [0.35, 0.70]


def _metric_value(backbone: str, metric: str, k: int) -> float:
    """A plausible metric value; flat_binned correlation columns are binned-only."""
    return round(_base_value(backbone, _metric_family(metric), k), 4)


def _load_flat_global_pool(con) -> None:
    """Insert flat global_pool rows (medoid baseline + other flat strategies)."""
    for backbone in BACKBONES:
        for strategy in FLAT_STRATEGIES:
            for k in K_VALUES:
                key = f"global_pool:{backbone}:{strategy}"
                for metric in METRICS:
                    if metric in ("flat_binned_spearman", "flat_binned_beneficial_reorder_rate"):
                        continue
                    # Non-medoid flat strategies sit slightly below the medoid baseline.
                    offset = 0.0 if strategy == "medoid" else -0.012
                    value = round(_metric_value(backbone, metric, k) + offset, 4)
                    con.execute(
                        "INSERT INTO analyze_metrics (strategy_key, strategy_type, sim_metric, k, metric, value) VALUES (?,?,?,?,?,?)",
                        [key, "global_pool", SIM_METRIC, k, metric, value],
                    )


def _load_binned(con) -> None:
    """Insert PTC + CTP weighted-aggregate rows (the weighted directional reductions)."""
    for backbone in BACKBONES:
        # PTC
        for bin_mode in PTC_BIN_MODES:
            for thresh in PTC_THRESHOLDS:
                for rep_a, rep_b in REP_COMBOS:
                    for agg in AGG_METHODS:
                        key = f"ptc:{backbone}:{bin_mode}:{thresh:.2f}:{rep_a}:{rep_b}:{agg}"
                        for k in K_VALUES:
                            for metric in METRICS:
                                offset = 0.055 if _FAMILY_WINNER.get(_metric_family(metric)) == agg else 0.02
                                value = round(_metric_value(backbone, metric, k) + offset, 4)
                                con.execute(
                                    "INSERT INTO analyze_metrics (strategy_key, strategy_type, sim_metric, k, metric, value) VALUES (?,?,?,?,?,?)",
                                    [key, "ptc", SIM_METRIC, k, metric, value],
                                )
        # CTP (one head + one threshold keeps the grid compact but complete)
        for head in CTP_HEADS:
            for thresh in CTP_THRESHOLDS:
                for rep_a, rep_b in REP_COMBOS:
                    for agg in AGG_METHODS:
                        key = f"ctp:{backbone}:{head}:{thresh:.2f}:{rep_a}:{rep_b}:{agg}"
                        for k in K_VALUES:
                            for metric in METRICS:
                                offset = 0.05 if _FAMILY_WINNER.get(_metric_family(metric)) == agg else 0.018
                                value = round(_metric_value(backbone, metric, k) + offset, 4)
                                con.execute(
                                    "INSERT INTO analyze_metrics (strategy_key, strategy_type, sim_metric, k, metric, value) VALUES (?,?,?,?,?,?)",
                                    [key, "ctp", SIM_METRIC, k, metric, value],
                                )


def _load_songs(con) -> None:
    """A small non-degenerate corpus: multiple artists with >1 song each."""
    songs = [
        ("aa11", "/m/effnet/one.m4a", "Artist A", "Album A", "Song One", "rock"),
        ("aa12", "/m/effnet/two.m4a", "Artist A", "Album A", "Song Two", "rock"),
        ("bb21", "/m/effnet/three.m4a", "Artist B", "Album B", "Song Three", "jazz"),
        ("bb22", "/m/effnet/four.m4a", "Artist B", "Album B", "Song Four", "jazz"),
        ("cc31", "/m/effnet/five.m4a", "Artist C", "Album C", "Song Five", "classical"),
    ]
    con.executemany(
        "INSERT INTO songs (song_id, path, artist, album, title, genre) VALUES (?,?,?,?,?,?)",
        songs,
    )


def _load_phase_timings(con) -> None:
    rows = [
        ("fixture-run-2026", "ingest", 12.0),
        ("fixture-run-2026", "embed", 301.5),
        ("fixture-run-2026", "stratify", 2.3),
        ("fixture-run-2026", "segment", 88.7),
        ("fixture-run-2026", "classify", 45.2),
        ("fixture-run-2026", "analyze", 19.8),
        ("fixture-run-2026", "report", 3.1),
    ]
    con.executemany("INSERT INTO phase_timings (run_ts, phase, elapsed_s) VALUES (?,?,?)", rows)


def _load_bin_stats(con) -> None:
    rows = [
        (f"s{i}", backbone, bin_mode, thresh, 4 + int(thresh * 2), 40, 2, 2, 8, 6.0)
        for backbone in BACKBONES
        for bin_mode in PTC_BIN_MODES
        for thresh in PTC_THRESHOLDS
        for i in range(5)
    ]
    con.executemany(
        "INSERT INTO binned_song_stats (song_id, backbone, bin_mode, std_thresh, n_bins, "
        "n_patches, n_outliers, min_bin_size, max_bin_size, mean_bin_size) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _load_binned_classify_ctp(con) -> None:
    rows = [
        (f"s{i}", backbone, head, bin_mode, thresh, bid, b"\x00", 10)
        for backbone in BACKBONES
        for head in CTP_HEADS
        for bin_mode in PTC_BIN_MODES
        for thresh in CTP_THRESHOLDS
        for i in range(5)
        for bid in range(4)
    ]
    con.executemany(
        "INSERT INTO binned_classify_ctp (song_id, backbone, head, bin_mode, std_thresh, bin_id, act, weight) "
        "VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )


def _load_head_sim_corr(con) -> None:
    rows = [
        (backbone, bin_mode, 0.10, "medoid", "medoid", SIM_METRIC, agg, 10, head, 0.42)
        for backbone in BACKBONES
        for head in CTP_HEADS
        for bin_mode in PTC_BIN_MODES
        for agg in AGG_METHODS
    ]
    con.executemany(
        "INSERT INTO head_sim_corr_rows (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, "
        "agg_method, k, head, corr) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _load_ptc_ctp_rows(con) -> None:
    rows = []
    for backbone in BACKBONES:
        for head in CTP_HEADS:
            for agg in AGG_METHODS:
                label = f"ctp:{head}:temporal_global:0.10:medoid:medoid:{agg}"
                ptc_d = 0.55
                ctp_d = 0.60
                rows.append((backbone, head, label, ptc_d, ctp_d, ctp_d - ptc_d, 0.5, 0.58, 0.08))
    con.executemany(
        "INSERT INTO ptc_ctp_rows (backbone, head, strategy, ptc_disc, ctp_disc, delta_disc, "
        "ptc_map, ctp_map, delta_map) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _load_truncation(con) -> None:
    rows = [
        (backbone, bin_mode, thresh, 0.5, 0.62, 0.12)
        for backbone in BACKBONES
        for bin_mode in PTC_BIN_MODES
        for thresh in PTC_THRESHOLDS
    ]
    con.executemany(
        "INSERT INTO truncation_robustness_rows (backbone, bin_mode, std_thresh, flat_mean_sim, "
        "binned_mean_sim, truncation_robustness_delta) VALUES (?,?,?,?,?,?)",
        rows,
    )


def _manifests() -> dict[str, MatchingCorpusManifest]:
    """Deterministic per-backbone matching-corpus manifests (5-song fixture corpus)."""
    song_ids = ("aa11", "aa12", "bb21", "bb22", "cc31")
    out: dict[str, MatchingCorpusManifest] = {}
    for backbone in BACKBONES:
        corpus_hash = hashlib.sha256(f"fixture-matching-corpus:{backbone}".encode()).hexdigest()[:16]
        out[backbone] = MatchingCorpusManifest(
            song_ids=song_ids,
            corpus_hash=corpus_hash,
            backbone=backbone,
        )
    return out


def main() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    # ensure_schema does not create ptc_ctp_rows; create it for section_head_value.
    con.execute(
        "CREATE TABLE IF NOT EXISTS ptc_ctp_rows ("
        "backbone VARCHAR, head VARCHAR, strategy VARCHAR, ptc_disc DOUBLE, ctp_disc DOUBLE, "
        "delta_disc DOUBLE, ptc_map DOUBLE, ctp_map DOUBLE, delta_map DOUBLE)"
    )

    _load_flat_global_pool(con)
    _load_binned(con)
    _load_songs(con)
    _load_phase_timings(con)
    _load_bin_stats(con)
    _load_binned_classify_ctp(con)
    _load_head_sim_corr(con)
    _load_ptc_ctp_rows(con)
    _load_truncation(con)

    matching_corpora = _manifests()

    report_dir = REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_run(con, report_dir, matching_corpora=matching_corpora)

    print("Fixture report written to:", report_dir)
    print("  report.json ->", report_dir / "report.json")
    print("  report.html ->", report_dir / "report.html")
    con.close()


if __name__ == "__main__":
    main()
