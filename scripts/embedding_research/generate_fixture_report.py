"""Generate a deterministic in-memory NARROW primary fixture report via the REAL builders.

This environment has no ONNX models (``/app/models`` is absent) and no audio corpus
(``/workspace/.devcontainer/test-media`` is empty), so the real ingest->embed->stratify->
segment->classify->analyze pipeline cannot run end-to-end.  The pre-existing
``research.duckdb`` is stale for the current report contract, so this script builds a
**fully deterministic in-memory DuckDB** feeding the REAL report entry point
(``report.run``) and every section builder.

The default primary fixture is NARROW (follow-on contract):

* backbone: ``effnet`` only;
* flat baseline: ``medoid`` only (``flat_strategies=["medoid"]``) — the explicit
  ``global_pool:effnet:medoid`` baseline;
* PTC representation: ``rep=medoid`` only (no median / no alternative reps);
* PTC boundary configurations: every configured (bin_mode, threshold), each reported
  separately — never collapsed or averaged across thresholds;
* primary score variant: ``max_per_candidate_segment`` (carried in the strategy-key
  ``agg_method`` position, i.e. ``ptc:effnet:{bin_mode}:{thresh:.2f}:medoid:medoid:max_per_candidate_segment``);
* similarity: cosine on unit vectors;
* comparison: every PTC configuration versus the observed ``global_pool:effnet:medoid``
  baseline for the same backbone.

MusicNN and CTP are **excluded from the default primary fixture**.  They are added only
under the explicit opt-in flag ``--include-musicnn-ctp`` (or
``build_fixture_con(include_musicnn_ctp=True)``).  CTP ``analyze_metrics`` rows, when
present, are never primary winner candidates — ``report._winners.section_winners``
filters ``strategy_type == "ctp"`` out of winner selection.  Archival CTP reference
tables (``ptc_ctp_rows``, ``head_sim_corr``, ``binned_classify_ctp``, ``truncation``)
remain loaded as archival data for the archival note / head-sim sections, but CTP never
appears as a primary ``analyze_metrics`` row in the DEFAULT fixture and never as a winner
row anywhere.

Every primary PTC row carries the primary score-variant identity in the strategy key and
the full bounded trace-summary scalars (``trace_n_pairs`` … ``trace_finite``) as
``analyze_metrics`` metric rows — mirroring ``score_variant_trace_summary``'s flattened
shape — so decoded winner rows carry finite trace fields.  A shared-boundary head-phase
provenance record (``boundary_source="effnet_ptc"``,
``head_pool_variant="shared_effnet_ptc_boundary"``) is written so the
``head-output-shared-ptc-boundary`` section renders a real per-threshold coverage table.

It then writes ``report.json`` + ``report.html`` to the configured report output
directory (``{OUTPUT_ROOT}/report``).

.. warning::
   This is a deterministic DEMO / fixture report.  Every metric value is synthetic.
   It must NOT be read as a measured corpus conclusion.  No embed / segment /
   classify / analyze step was executed.
"""

from __future__ import annotations

import argparse
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
from scripts.embedding_research.db._schema import ensure_schema, require_supported_duckdb
from scripts.embedding_research.db.head_phase import HeadPhaseProvenanceRow, write_head_phase_provenance
from scripts.embedding_research.report import run as report_run

# Primary backbone in the DEFAULT fixture (follow-on contract: effnet only).
DEFAULT_BACKBONES = ["effnet"]

# Flat strategies in the DEFAULT fixture: medoid only.
FLAT_STRATEGIES = ["medoid"]

# PTC boundary configurations: every configured (bin_mode, threshold), reported separately.
PTC_BIN_MODES = ["temporal_global", "temporal_perdim"]
PTC_THRESHOLDS = [1.0, 1.1]

# Primary score-variant identity carried in the strategy-key agg position.
PRIMARY_SCORE_VARIANT = "max_per_candidate_segment"

# Reps in the DEFAULT primary fixture: medoid only.
REP_MEDOID = "medoid"

# Explicit opt-in dimensions (never in the DEFAULT primary fixture).
MUSICNN_BACKBONES = ["musicnn"]
CTP_HEADS = ["genre", "mood_happy"]
CTP_THRESHOLDS = [0.10]

# Evaluation K values.
K_VALUES = [5, 10]
SIM_METRIC = "cosine"

# Heads for the shared-boundary head-phase provenance record (effnet only).
HEAD_PHASE_HEADS = ["genre", "mood_happy"]

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

# Bounded trace-summary scalars persisted alongside the primary PTC rows (mirrors the
# shape of ``score_variant_trace_summary``).  All finite, deterministic synthetic values.
TRACE_METRICS = {
    "trace_n_pairs": 10.0,
    "trace_numerator_sum": 8.5,
    "trace_denominator_sum": 9.0,
    "trace_numerator_mean": 0.9444,
    "trace_denominator_mean": 1.0,
    "trace_collision_count": 1.0,
    "trace_winner_count": 3.0,
    "trace_retained_contributions": 3.0,
    "trace_dropped_contributions": 0.0,
    "trace_finite": 1.0,
}


# The metric family a column belongs to (used to pick a deterministic winner so every
# configured PTC (bin_mode, threshold) wins at least one family -> non-trivial factor summary).
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


# Which configured PTC (bin_mode, threshold) is engineered to win each metric family.
# Each of the four (bin_mode, threshold) configs wins at least one family, so every
# configured threshold appears across the winner rows (per-threshold non-collapse).
_CONFIG_WINNER_FAMILY: dict[tuple[str, float], frozenset[str]] = {
    ("temporal_global", 1.0): frozenset({"MAP"}),
    ("temporal_global", 1.1): frozenset({"MRR"}),
    ("temporal_perdim", 1.0): frozenset({"NDCG"}),
    ("temporal_perdim", 1.1): frozenset({"Recall", "discrimination"}),
}


# Deterministic per-backbone base values for each metric family + K.
def _base_value(backbone: str, family: str, k: int) -> float:
    seed = int(hashlib.sha256(f"{backbone}|{family}|{k}".encode()).hexdigest()[:8], 16)
    return 0.35 + 0.35 * (seed % 1000) / 1000.0  # deterministic in [0.35, 0.70]


def _metric_value(backbone: str, metric: str, k: int) -> float:
    """A plausible metric value; flat_binned correlation columns are binned-only."""
    return round(_base_value(backbone, _metric_family(metric), k), 4)


def _insert_metrics(con, strategy_key: str, strategy_type: str, k: int, metric_values: dict) -> None:
    """Insert analyze_metrics rows for every non-None (metric, value) pair."""
    rows = []
    for name, value in metric_values.items():
        if value is None:
            continue
        rows.append((strategy_key, strategy_type, SIM_METRIC, k, name, float(value)))
    con.executemany(
        "INSERT INTO analyze_metrics (strategy_key, strategy_type, sim_metric, k, metric, value) VALUES (?,?,?,?,?,?)",
        rows,
    )


def _load_flat_global_pool(con, backbones: list[str]) -> None:
    """Insert flat global_pool medoid baseline rows (the explicit per-backbone baseline)."""
    for backbone in backbones:
        for strategy in FLAT_STRATEGIES:
            for k in K_VALUES:
                key = f"global_pool:{backbone}:{strategy}"
                metrics = {
                    m: _metric_value(backbone, m, k)
                    for m in METRICS
                    if m not in ("flat_binned_spearman", "flat_binned_beneficial_reorder_rate")
                }
                _insert_metrics(con, key, "global_pool", k, metrics)


def _load_binned(con, backbones: list[str]) -> None:
    """Insert PTC primary rows: every (bin_mode, threshold) at rep=medoid with the
    primary ``max_per_candidate_segment`` score-variant identity in the strategy key,
    plus the bounded finite trace-summary scalars."""
    for backbone in backbones:
        for bin_mode in PTC_BIN_MODES:
            for thresh in PTC_THRESHOLDS:
                key = f"ptc:{backbone}:{bin_mode}:{thresh:.2f}:{REP_MEDOID}:{REP_MEDOID}:{PRIMARY_SCORE_VARIANT}"
                winning = _CONFIG_WINNER_FAMILY[(bin_mode, thresh)]
                for k in K_VALUES:
                    metrics: dict = {
                        m: round(
                            _metric_value(backbone, m, k) + (0.055 if _metric_family(m) in winning else 0.02),
                            4,
                        )
                        for m in METRICS
                        if m not in ("flat_binned_spearman", "flat_binned_beneficial_reorder_rate")
                    }
                    metrics.update(TRACE_METRICS)
                    _insert_metrics(con, key, "ptc", k, metrics)


def _load_ctp_analyze(con, backbones: list[str]) -> None:
    """OPT-IN archival CTP analyze rows (never primary winner candidates).

    section_winners filters ``strategy_type == 'ctp'`` out of winner selection, so these
    rows are never primary winner/delta candidates even when present.
    """
    for backbone in backbones:
        for head in CTP_HEADS:
            for thresh in CTP_THRESHOLDS:
                key = f"ctp:{backbone}:{head}:{thresh:.2f}:{REP_MEDOID}:{REP_MEDOID}:{PRIMARY_SCORE_VARIANT}"
                for k in K_VALUES:
                    metrics: dict = {
                        m: round(_metric_value(backbone, m, k) + 0.03, 4)
                        for m in METRICS
                        if m not in ("flat_binned_spearman", "flat_binned_beneficial_reorder_rate")
                    }
                    metrics.update(TRACE_METRICS)
                    _insert_metrics(con, key, "ctp", k, metrics)


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
        for backbone in ["effnet"]
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
        (f"s{i}", "effnet", head, bin_mode, thresh, bid, b"\x00", 10)
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
        ("effnet", bin_mode, 0.10, "medoid", "medoid", SIM_METRIC, agg, 10, head, 0.42)
        for head in CTP_HEADS
        for bin_mode in PTC_BIN_MODES
        for agg in ["max_per_candidate_segment"]
    ]
    con.executemany(
        "INSERT INTO head_sim_corr_rows (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, "
        "agg_method, k, head, corr) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _load_ptc_ctp_rows(con) -> None:
    rows = []
    for head in CTP_HEADS:
        for agg in ["max_per_candidate_segment"]:
            label = f"ctp:{head}:temporal_global:0.10:medoid:medoid:{agg}"
            ptc_d = 0.55
            ctp_d = 0.60
            rows.append(("effnet", head, label, ptc_d, ctp_d, ctp_d - ptc_d, 0.5, 0.58, 0.08))
    con.executemany(
        "INSERT INTO ptc_ctp_rows (backbone, head, strategy, ptc_disc, ctp_disc, delta_disc, "
        "ptc_map, ctp_map, delta_map) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _load_truncation(con) -> None:
    rows = [("effnet", bin_mode, thresh, 0.5, 0.62, 0.12) for bin_mode in PTC_BIN_MODES for thresh in PTC_THRESHOLDS]
    con.executemany(
        "INSERT INTO truncation_robustness_rows (backbone, bin_mode, std_thresh, flat_mean_sim, "
        "binned_mean_sim, truncation_robustness_delta) VALUES (?,?,?,?,?,?)",
        rows,
    )


def _manifests(include_musicnn_ctp: bool) -> dict[str, MatchingCorpusManifest]:
    """Deterministic per-backbone matching-corpus manifests (5-song fixture corpus)."""
    song_ids = ("aa11", "aa12", "bb21", "bb22", "cc31")
    out: dict[str, MatchingCorpusManifest] = {}
    for backbone in DEFAULT_BACKBONES:
        corpus_hash = hashlib.sha256(f"fixture-matching-corpus:{backbone}".encode()).hexdigest()[:16]
        out[backbone] = MatchingCorpusManifest(
            song_ids=song_ids,
            corpus_hash=corpus_hash,
            backbone=backbone,
        )
    if include_musicnn_ctp:
        for backbone in MUSICNN_BACKBONES:
            corpus_hash = hashlib.sha256(f"fixture-matching-corpus:{backbone}".encode()).hexdigest()[:16]
            out[backbone] = MatchingCorpusManifest(
                song_ids=song_ids,
                corpus_hash=corpus_hash,
                backbone=backbone,
            )
    return out


def _load_head_phase_provenance(con, effnet_hash: str) -> None:
    """Write the canonical shared-boundary head-phase provenance (effnet only).

    Canonical current rows (D3): boundary_source="effnet_ptc",
    head_pool_variant="shared_effnet_ptc_boundary", status=done, finite, the legacy
    threshold NULL, reference_corpus_hash == the effnet fixture corpus hash, and
    n_pooled <= n_songs.  A deterministic synthetic ``seg_config`` id is used per
    (bin_mode, threshold_configured/threshold_effective) so rows render as canonical.
    """
    # Deterministic synthetic config ids per (bin_mode, threshold).
    config_ids: dict[tuple[str, float], int] = {
        pair: idx for idx, pair in enumerate(((b, t) for b in PTC_BIN_MODES for t in PTC_THRESHOLDS), start=1)
    }
    rows = [
        HeadPhaseProvenanceRow(
            run_id="fixture",
            config_id=config_ids[(bin_mode, thresh)],
            backbone="effnet",
            head=head,
            bin_mode=bin_mode,
            threshold_configured=thresh,
            threshold_effective=thresh,
            semantics="direct_l2",
            status="done",
            n_songs=5,
            n_pooled=5,
            finite=True,
            reference_corpus_hash=effnet_hash,
        )
        for head in HEAD_PHASE_HEADS
        for bin_mode in PTC_BIN_MODES
        for thresh in PTC_THRESHOLDS
    ]
    write_head_phase_provenance(con, rows)


def build_fixture_con(include_musicnn_ctp: bool = False) -> duckdb.DuckDBPyConnection:
    """Build the fully deterministic in-memory DuckDB for the (narrow) fixture.

    Default: effnet-only primary (medoid flat + medoid PTC with the primary
    max_per_candidate_segment score).  With ``include_musicnn_ctp=True`` it also adds the
    MusicNN independent primary rows and archival CTP analyze rows (never winners).
    """
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    # ensure_schema does not create ptc_ctp_rows; create it for section_head_value.
    con.execute(
        "CREATE TABLE IF NOT EXISTS ptc_ctp_rows ("
        "backbone VARCHAR, head VARCHAR, strategy VARCHAR, ptc_disc DOUBLE, ctp_disc DOUBLE, "
        "delta_disc DOUBLE, ptc_map DOUBLE, ctp_map DOUBLE, delta_map DOUBLE)"
    )

    backbones = list(DEFAULT_BACKBONES)
    if include_musicnn_ctp:
        backbones += MUSICNN_BACKBONES

    _load_flat_global_pool(con, backbones)
    _load_binned(con, backbones)
    if include_musicnn_ctp:
        _load_ctp_analyze(con, DEFAULT_BACKBONES)
    _load_songs(con)
    _load_phase_timings(con)
    _load_bin_stats(con)
    _load_binned_classify_ctp(con)
    _load_head_sim_corr(con)
    _load_ptc_ctp_rows(con)
    _load_truncation(con)

    manifests = _manifests(include_musicnn_ctp)
    effnet_hash = manifests["effnet"].corpus_hash
    _load_head_phase_provenance(con, effnet_hash)

    return con, manifests


def main() -> None:
    require_supported_duckdb()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--include-musicnn-ctp",
        action="store_true",
        help=(
            "OPT-IN: also add MusicNN independent primary rows and archival CTP "
            "analyze_metrics rows to the fixture.  CTP rows are never primary winners. "
            "Default (no flag) writes the narrow effnet-only primary fixture."
        ),
    )
    args = parser.parse_args()

    con, matching_corpora = build_fixture_con(include_musicnn_ctp=args.include_musicnn_ctp)

    report_dir = REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_run(con, report_dir, matching_corpora=matching_corpora)

    print("Fixture report written to:", report_dir)
    print("  report.json ->", report_dir / "report.json")
    print("  report.html ->", report_dir / "report.html")
    con.close()


if __name__ == "__main__":
    main()
