"""Plan D (P1): medoid-baseline resolution and report identity tests.

Proves (with EffNet and MusicNN fixtures) that:
- the flat baseline resolves exactly to ``global_pool:{backbone}:medoid`` (never
  max/median/mean across flat strategies, never a cross-backbone aggregate);
- MusicNN is not averaged into EffNet — separate sections/rows per backbone;
- flat and binned rows that share a display label remain distinguishable;
- all schema-v2 section keys are present.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.embedding_research.report._base import (
    ANALYZE_METRICS_COLUMNS,
    canonical_flat_baseline,
    flat_medoid_value,
)
from scripts.embedding_research.report._retrieval import section_per_backbone, section_unified_table
from scripts.embedding_research.report._summary import section_summary

pytestmark = pytest.mark.unit

_V2_KEYS = {
    "id",
    "title",
    "description",
    "stats",
    "charts",
    "tables",
    "panels",
    "subsections",
    "warnings",
    "headline",
    "empty_message",
}


def _gp_row(backbone: str, strategy: str, *, disc_genre: float, **overrides) -> pd.DataFrame:
    """One global_pool analyze-metrics row (decoded columns included)."""
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        strategy_key=f"global_pool:{backbone}:{strategy}",
        strategy_type="global_pool",
        backbone=backbone,
        strategy=strategy,
        sim_metric="cosine",
        k=10,
        disc_genre=disc_genre,
        disc_general=disc_genre,
        disc_score=disc_genre,
        map_k_general=disc_genre,
        map_k=disc_genre,
        mrr=disc_genre,
        ndcg_k=disc_genre,
        recall_k=disc_genre,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


def _ctp_row(backbone: str, *, disc_genre: float, **overrides) -> pd.DataFrame:
    """One archival-only ctp analyze-metrics row."""
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        strategy_key=f"ctp:{backbone}:genre:1.0:median:max:bidirectional_weighted",
        strategy_type="ctp",
        backbone=backbone,
        std_thresh=1.0,
        rep_a="median",
        rep_b="max",
        agg_method="bidirectional_weighted",
        sim_metric="cosine",
        k=10,
        disc_genre=disc_genre,
        disc_general=disc_genre,
        disc_score=disc_genre,
        map_k_general=disc_genre,
        map_k=disc_genre,
        mrr=disc_genre,
        ndcg_k=disc_genre,
        recall_k=disc_genre,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


def _ptc_row(backbone: str, *, rep_a: str, disc_genre: float, **overrides) -> pd.DataFrame:
    """One ptc analyze-metrics row."""
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        strategy_key=f"ptc:{backbone}:temporal_global:1.0:{rep_a}:median:target_weighted",
        strategy_type="ptc",
        backbone=backbone,
        bin_mode="temporal_global",
        std_thresh=1.0,
        rep_a=rep_a,
        rep_b="median",
        agg_method="target_weighted",
        sim_metric="cosine",
        k=10,
        disc_genre=disc_genre,
        disc_general=disc_genre,
        disc_score=disc_genre,
        map_k_general=disc_genre,
        map_k=disc_genre,
        mrr=disc_genre,
        ndcg_k=disc_genre,
        recall_k=disc_genre,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


# ---------------------------------------------------------------------------
# 1. Medoid baseline selection is exact (only global_pool:{bb}:medoid)
# ---------------------------------------------------------------------------


def test_canonical_flat_baseline_selects_only_medoid_row():
    df = pd.concat(
        [
            _gp_row("EffNet", "mean", disc_genre=0.8),
            _gp_row("EffNet", "max_norm", disc_genre=0.9),
            _gp_row("EffNet", "medoid", disc_genre=0.6),
        ],
        ignore_index=True,
    )

    baseline = canonical_flat_baseline(df, "EffNet")

    assert len(baseline) == 1
    assert baseline.iloc[0]["strategy"] == "medoid"
    assert baseline.iloc[0]["strategy_key"] == "global_pool:EffNet:medoid"
    assert baseline.iloc[0]["disc_genre"] == 0.6


def test_canonical_flat_baseline_never_falls_back_to_aggregate():
    """The mean/max_norm rows (which score higher) must not leak into the baseline."""
    df = pd.concat(
        [
            _gp_row("EffNet", "mean", disc_genre=0.8),
            _gp_row("EffNet", "max_norm", disc_genre=0.9),
            _gp_row("EffNet", "medoid", disc_genre=0.6),
        ],
        ignore_index=True,
    )

    baseline = canonical_flat_baseline(df, "EffNet")

    assert baseline["disc_genre"].tolist() == [0.6]
    assert flat_medoid_value(df, "EffNet", "disc_genre") == 0.6


def test_summary_uses_medoid_not_max_flat():
    """section_summary's flat baseline column reports the medoid value, not the flat max."""
    df = pd.concat(
        [
            _gp_row("EffNet", "mean", disc_genre=0.9),
            _gp_row("EffNet", "medoid", disc_genre=0.6),
            _ptc_row("EffNet", rep_a="median", disc_genre=0.65),
        ],
        ignore_index=True,
    )

    result = section_summary(df)

    table = result["tables"][0]
    col_idx = table["columns"].index("flat_medoid_disc_genre")
    assert table["rows"][0][col_idx] == "0.6000"


def test_ctp_never_drives_summary_headline_or_best_binned():
    """A CTP row can never drive the summary best_binned_config/headline.

    CTP is archival-only (requirement 2): even a CTP row scoring higher than the
    medoid baseline must not appear as the best binned config nor flip the summary
    headline — only EffNet PTC binned rows are candidates.
    """
    # Only a medoid flat baseline + a high-scoring CTP row (no PTC row at all).
    df = pd.concat(
        [
            _gp_row("EffNet", "medoid", disc_genre=0.6),
            _ctp_row("EffNet", disc_genre=0.99),
        ],
        ignore_index=True,
    )

    result = section_summary(df)

    table = result["tables"][0]
    col_idx = table["columns"].index("best_binned_config")
    assert table["rows"][0][col_idx] == "—"  # no PTC row -> no best binned config
    assert result["headline"]["text"] == (
        "No backbone's best binned configuration beats the explicit medoid flat baseline on disc_genre."
    )


# ---------------------------------------------------------------------------
# 2. MusicNN is never averaged into EffNet
# ---------------------------------------------------------------------------


def test_musicnn_not_averaged_into_effnet_baselines():
    df = pd.concat(
        [
            _gp_row("EffNet", "medoid", disc_genre=0.6),
            _gp_row("MusicNN", "medoid", disc_genre=0.9),
        ],
        ignore_index=True,
    )

    assert flat_medoid_value(df, "EffNet", "disc_genre") == 0.6
    assert flat_medoid_value(df, "MusicNN", "disc_genre") == 0.9


def test_musicnn_and_effnet_have_separate_per_backbone_subsections():
    df = pd.concat(
        [
            _gp_row("EffNet", "medoid", disc_genre=0.6),
            _gp_row("MusicNN", "medoid", disc_genre=0.9),
            _ptc_row("EffNet", rep_a="median", disc_genre=0.65),
            _ptc_row("MusicNN", rep_a="median", disc_genre=0.95),
        ],
        ignore_index=True,
    )

    result = section_per_backbone(df)

    subsection_ids = {sub["id"] for sub in result["subsections"]}
    assert subsection_ids == {"backbone-EffNet", "backbone-MusicNN"}


def test_musicnn_and_effnet_have_separate_summary_rows():
    df = pd.concat(
        [
            _gp_row("EffNet", "medoid", disc_genre=0.6),
            _gp_row("MusicNN", "medoid", disc_genre=0.9),
            _ptc_row("EffNet", rep_a="median", disc_genre=0.65),
            _ptc_row("MusicNN", rep_a="median", disc_genre=0.95),
        ],
        ignore_index=True,
    )

    result = section_summary(df)

    table = result["tables"][0]
    bb_idx = table["columns"].index("backbone")
    backbone_rows = {table["rows"][i][bb_idx] for i in range(len(table["rows"]))}
    assert backbone_rows == {"EffNet", "MusicNN"}


# ---------------------------------------------------------------------------
# 3. Flat / binned rows sharing a display label stay distinguishable
# ---------------------------------------------------------------------------


def test_flat_and_binned_same_display_label_distinguishable():
    """Flat strategy 'medoid' and binned rep_a 'medoid' both display 'medoid'."""
    df = pd.concat(
        [
            _gp_row("EffNet", "medoid", disc_genre=0.6),
            _ptc_row("EffNet", rep_a="medoid", disc_genre=0.7),
        ],
        ignore_index=True,
    )

    result = section_unified_table(df)

    table = result["tables"][0]
    type_idx = table["columns"].index("type")
    config_idx = table["columns"].index("config")
    type_rows = {row[type_idx] for row in table["rows"]}
    configs = {row[config_idx] for row in table["rows"]}

    assert type_rows == {"flat", "binned"}
    # The flat row's config is the strategy name; the binned config carries 'medoid'
    # as part of its full identity label. Both rows exist and are distinguished by type.
    assert any("medoid" in cfg for cfg in configs)


# ---------------------------------------------------------------------------
# 4. All schema-v2 section keys remain present with EffNet + MusicNN fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder",
    [section_summary, section_per_backbone, section_unified_table],
)
def test_schema_v2_keys_present_with_two_backbones(builder):
    df = pd.concat(
        [
            _gp_row("EffNet", "medoid", disc_genre=0.6),
            _gp_row("MusicNN", "medoid", disc_genre=0.9),
            _ptc_row("EffNet", rep_a="median", disc_genre=0.65),
            _ptc_row("MusicNN", rep_a="median", disc_genre=0.95),
        ],
        ignore_index=True,
    )

    result = builder(df)

    missing = _V2_KEYS - result.keys()
    assert not missing, f"{builder.__name__} missing keys: {missing}"
