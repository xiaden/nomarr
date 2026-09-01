"""Plan D (P3): rendered report surfaces for exact winners/deltas and the summary.

Proves that the new ``section_winners`` schema-v2 section:
- carries every schema-v2 key and separates backbones into their own subsections;
- renders the full 22-column winner-delta table and the 10-column factor-summary
  table (every new column present);
- computes winner/delta arithmetic exactly and orders rows deterministically;
- degrades to a clear empty_message when there is no data or no explicit
  ``global_pool:{backbone}:medoid`` baseline;
- serializes cleanly through the report's JSON payload path with schema_version 2
  and never emits a ``disc_album`` key;

and that the Phase 3 summary rewrite keeps the medoid baseline, an exact
best-binned winner identity, and a headline (the dead n_songs corpus-mismatch
warning branch is removed).
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.embedding_research.corpus import MatchingCorpusManifest
from scripts.embedding_research.report import _payload
from scripts.embedding_research.report._base import ANALYZE_METRICS_COLUMNS
from scripts.embedding_research.report._summary import section_summary
from scripts.embedding_research.report._winners import (
    FACTOR_SUMMARY_COLUMNS,
    GROUPS,
    METRIC_FAMILIES,
    WINNER_DELTA_COLUMNS,
)
from scripts.embedding_research.report._winners_report import section_winners

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

_SUBSECTION_V2_KEYS = _V2_KEYS


def _base_row() -> dict:
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        sim_metric="cosine",
        k=10,
        map_k_artist=0.5,
        map_k_genre=0.5,
        map_k_head=0.5,
        map_k_general=0.5,
        mrr=0.5,
        mrr_genre=0.5,
        mrr_head=0.5,
        ndcg_k_artist=0.5,
        ndcg_k_genre=0.5,
        ndcg_k_head=0.5,
        recall_k_artist=0.5,
        recall_k_genre=0.5,
        recall_k_head=0.5,
        disc_artist=0.4,
        disc_genre=0.4,
        disc_head=0.4,
        disc_general=0.4,
        disc_score=0.4,
    )
    return row


def _medoid_row(backbone: str, *, k: int = 10, **overrides) -> dict:
    row = _base_row()
    row.update(
        strategy_key=f"global_pool:{backbone}:medoid",
        strategy_type="global_pool",
        backbone=backbone,
        strategy="medoid",
        k=k,
    )
    row.update(overrides)
    return row


def _ptc_row(backbone: str, *, k: int = 10, **overrides) -> dict:
    row = _base_row()
    row.update(
        strategy_key=f"ptc:{backbone}:temporal_global:1.0:median:max:target_weighted",
        strategy_type="ptc",
        backbone=backbone,
        bin_mode="temporal_global",
        std_thresh=1.0,
        rep_a="median",
        rep_b="max",
        agg_method="target_weighted",
        k=k,
    )
    row.update(overrides)
    return row


def _df(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def _table_rows(table: dict) -> list[dict]:
    """make_table stores rows as lists indexed by ``table["columns"]``; zip back to dicts."""
    return [dict(zip(table["columns"], r, strict=False)) for r in table["rows"]]


def _effnet_musicnn_df() -> pd.DataFrame:
    """Two backbones, each with a medoid baseline and a winning PTC config."""
    return _df(
        _medoid_row("EffNet", map_k_artist=0.6, map_k_genre=0.55, disc_genre=0.6),
        _ptc_row("EffNet", map_k_artist=0.8, map_k_genre=0.6, disc_genre=0.65),
        _medoid_row("MusicNN", map_k_artist=0.5, map_k_genre=0.45, disc_genre=0.5),
        _ptc_row("MusicNN", map_k_artist=0.9, map_k_genre=0.55, disc_genre=0.95),
    )


def _winner_delta_table(section: dict, backbone: str) -> dict:
    sub = next(s for s in section["subsections"] if s["id"] == f"winners-{backbone}")
    return next(t for t in sub["tables"] if t["id"] == f"winner_delta_{backbone}")


def _factor_table(section: dict, backbone: str) -> dict:
    sub = next(s for s in section["subsections"] if s["id"] == f"winners-{backbone}")
    return next(t for t in sub["tables"] if t["id"] == f"factor_summary_{backbone}")


# ---------------------------------------------------------------------------
# schema-v2 + per-backbone structure
# ---------------------------------------------------------------------------


def test_section_winners_schema_v2_keys():
    section = section_winners(_effnet_musicnn_df())
    assert set(section) == _V2_KEYS
    assert section["id"] == "winners"


def test_section_winners_separate_backbone_subsections():
    section = section_winners(_effnet_musicnn_df())
    ids = {sub["id"] for sub in section["subsections"]}
    assert ids == {"winners-EffNet", "winners-MusicNN"}
    for sub in section["subsections"]:
        assert set(sub) == _SUBSECTION_V2_KEYS


# ---------------------------------------------------------------------------
# column coverage
# ---------------------------------------------------------------------------


def test_winner_delta_table_includes_all_columns():
    table = _winner_delta_table(section_winners(_effnet_musicnn_df()), "EffNet")
    assert table["columns"] == list(WINNER_DELTA_COLUMNS)


def test_factor_summary_table_includes_all_columns():
    table = _factor_table(section_winners(_effnet_musicnn_df()), "EffNet")
    assert table["columns"] == list(FACTOR_SUMMARY_COLUMNS)


# ---------------------------------------------------------------------------
# arithmetic + deterministic ordering
# ---------------------------------------------------------------------------


def test_winner_delta_arithmetic_exact():
    section = section_winners(_effnet_musicnn_df())
    eff = _table_rows(_winner_delta_table(section, "EffNet"))
    artist_map = next(r for r in eff if r["group"] == "artist" and r["metric"] == "MAP")
    assert float(artist_map["winner_value"]) == pytest.approx(0.8)
    assert float(artist_map["baseline_value"]) == pytest.approx(0.6)
    assert float(artist_map["delta"]) == pytest.approx(0.2)  # 0.8 - 0.6
    assert artist_map["baseline_strategy_key"] == "global_pool:EffNet:medoid"

    mus = _table_rows(_winner_delta_table(section, "MusicNN"))
    # EffNet's winner must never be compared to MusicNN's baseline.
    for r in mus:
        assert r["baseline_strategy_key"] == "global_pool:MusicNN:medoid"


def test_winner_delta_emits_corpus_hash_and_size_per_backbone():
    corpora = {
        "EffNet": MatchingCorpusManifest(
            song_ids=("s1", "s2", "s3"),
            corpus_hash="abc123",
            backbone="EffNet",
        ),
        "MusicNN": MatchingCorpusManifest(
            song_ids=("s4", "s5", "s6", "s7"),
            corpus_hash="def456",
            backbone="MusicNN",
        ),
    }
    section = section_winners(_effnet_musicnn_df(), corpus_by_backbone=corpora)
    eff = _table_rows(_winner_delta_table(section, "EffNet"))
    assert all(r["corpus_hash"] == "abc123" and r["corpus_size"] == "3" for r in eff)
    mus = _table_rows(_winner_delta_table(section, "MusicNN"))
    assert all(r["corpus_hash"] == "def456" and r["corpus_size"] == "4" for r in mus)


def test_winner_delta_corpus_columns_none_without_manifest():
    section = section_winners(_effnet_musicnn_df())
    eff = _table_rows(_winner_delta_table(section, "EffNet"))
    # make_table renders None as "—"; no manifest supplied => empty corpus columns.
    assert all(r["corpus_hash"] == "—" and r["corpus_size"] == "—" for r in eff)


def test_delta_can_be_negative():
    df = _df(
        _medoid_row("EffNet", map_k_artist=0.7),
        _ptc_row("EffNet", map_k_artist=0.4),
    )
    rows = _table_rows(_winner_delta_table(section_winners(df), "EffNet"))
    artist_map = next(r for r in rows if r["group"] == "artist" and r["metric"] == "MAP")
    assert float(artist_map["delta"]) == pytest.approx(-0.3)


def test_section_winners_deterministic_ordering():
    df = _effnet_musicnn_df()
    first = section_winners(df)
    second = section_winners(df)
    assert first == second

    group_rank = {g: i for i, g in enumerate(GROUPS)}
    metric_rank = {m: i for i, m in enumerate(METRIC_FAMILIES)}
    for backbone in ("EffNet", "MusicNN"):
        rows = _table_rows(_winner_delta_table(first, backbone))
        keys = [(r["backbone"], r["group"], r["metric"], r["k"]) for r in rows]
        # Deterministic: sorted by backbone, then the grid's group order, then metric-family order, then k.
        assert keys == sorted(keys, key=lambda t: (t[0], group_rank.get(t[1], 99), metric_rank.get(t[2], 99), t[3]))
        # factor summary rows ordered by backbone, factor, factor_value, group, metric, k
        factor = _table_rows(_factor_table(first, backbone))
        fkeys = [(r["backbone"], r["factor"], r["factor_value"], r["group"], r["metric"], r["k"]) for r in factor]
        assert fkeys == sorted(fkeys)


# ---------------------------------------------------------------------------
# empty / no-baseline degradation
# ---------------------------------------------------------------------------


def test_section_winners_empty_df():
    section = section_winners(pd.DataFrame())
    assert section["empty_message"]
    assert not section["subsections"]


def test_section_winners_no_medoid_baseline():
    df = _df(_ptc_row("EffNet", map_k_artist=0.8))  # no global_pool medoid row
    section = section_winners(df)
    assert section["empty_message"]
    assert "medoid" in section["empty_message"].lower()
    assert not section["subsections"]


# ---------------------------------------------------------------------------
# Phase 3 summary rewrite
# ---------------------------------------------------------------------------


def test_summary_uses_medoid_policy_and_exact_winner():
    df = _df(
        _medoid_row("EffNet", disc_genre=0.6),
        _ptc_row("EffNet", disc_genre=0.65),
    )
    section = section_summary(df)
    assert section["headline"] is not None
    row = _table_rows(section["tables"][0])[0]
    assert row["flat_medoid_disc_genre"] == "0.6000"  # medoid, never max
    assert row["best_binned_disc_genre"] == "0.6500"
    assert float(row["delta_vs_medoid"]) == pytest.approx(0.05)
    # full exact identity, not a collapsed aggregate name
    assert row["best_binned_config"] != "—"


def test_summary_no_n_songs_mismatch_warning():
    # The n_songs corpus-mismatch warning was removed because ANALYZE_METRICS_COLUMNS
    # has no n_songs column, so the branch could never fire in the real report path.
    # Even if a hand-built fixture carries n_songs, section_summary must not emit it.
    df = _df(
        _medoid_row("EffNet", n_songs=100, disc_genre=0.6),
        _ptc_row("EffNet", n_songs=90, disc_genre=0.65),
    )
    section = section_summary(df)
    assert section["warnings"] == []


# ---------------------------------------------------------------------------
# generated payload JSON schema + no disc_album
# ---------------------------------------------------------------------------


def test_winners_payload_json_schema():
    df = _effnet_musicnn_df()
    sections = [section_winners(df), section_summary(df)]
    payload = _payload(sections, warnings=[])
    assert payload["schema_version"] == 2
    assert set(payload) >= {"schema_version", "title", "run_ts", "warnings", "sections"}
    # The generated payload must round-trip through the exact JSON writer used by run().
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    decoded = json.loads(encoded)
    assert decoded["schema_version"] == 2
    assert {s["id"] for s in decoded["sections"]} >= {"winners", "summary"}


def test_no_disc_album_in_winners_section_or_payload():
    df = _effnet_musicnn_df()
    section = section_winners(df)
    assert "disc_album" not in json.dumps(section)
    payload = _payload([section, section_summary(df)], warnings=[])
    assert "disc_album" not in json.dumps(payload)
