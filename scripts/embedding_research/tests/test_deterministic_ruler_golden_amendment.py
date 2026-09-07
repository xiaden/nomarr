"""Amended P3-S4 Part 1 — deterministic GOLDEN (harness/fixture-path) tests for the ruler / identity layer.

Phases 1-2 and P3-S1/S2/S3 landed the compute/unit layer (``test_observation_rulers`` 12 tests,
suffixed-vocab assertions, threshold/dispatch/identity tests) and the persistence writers.  This
file adds the END-TO-END deterministic evidence layer the amended P3-S4 Part 1 specifies, driving
the REAL producers over ``conftest.build_compact_catalog`` harnesses (never a real corpus / model /
audio / ONNX, CPU-only):

Arm (a) — three-ruler head evidence golden: head-suite pooling = class-1 ``act[1]`` over committed
  whole-song ``uint8 mask == 1`` rows (canonical sorted tuple order, exact labels/pooled values),
  full-tuple relevance/agreement reflected in the persisted ``n_queries_head``, the ``>= 2``-distinct
  tuple-group discrimination guard yielding a guarded finite ``0.0`` when a single group remains, and
  the EffNet-only committed-artifact resolver over a real fixture store.

Arm (b) — vocabulary golden: the exact suffixed 18-key set on the persisted class + medoid rows of a
  real ``run.py::_run_analyze``; generic/unsuffixed keys absent; ``n_queries_artist/genre/head``
  present (0 only when a ruler has no evaluable query); a missing artist/genre label is a per-ruler
  exclusion (never 'unknown', never a whole-run refusal); the flat per-song surface is artist-only
  (bare ``ap_k``/``mrr``/``recall_k`` + ``disc_artist_contrib`` populated, ``disc_genre_contrib`` /
  ``disc_head_contrib`` historical-empty).

Arm (c) — medoid golden: the observed global-medoid rows carry the SAME three suffixed ruler families
  + ``n_queries`` as the class pass (parity) and are persisted as a NON-``catalog`` ``global_pool``
  row (never a class/winner candidate).

Arm (d) — experiment-identity golden: ``bin_mode`` -> executed-distance dispatch matches the
  advertised metric (``temporal_global`` -> ``l2`` via ``global_dist``, ``temporal_perdim`` ->
  ``chebyshev`` via ``perdim_dist``); two equal-numeric-threshold configs under the two bin modes are
  distinct experiments with separate persisted grids (never deduped across config / canonical hash /
  search/exact leaf); the canonical semantic-head phase is L2-primary only (``TEMPORAL_BIN_MODES``).

Compute-level branches that are already pinned in ``test_observation_rulers`` (exact ``0.5`` side
boundary, present-non-finite -> ``NonFiniteResultError``, missing-suite-per-ruler exclusion, exact
full-tuple relevance unit semantics) are referenced, not duplicated, here.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.embedding_research import catalog as catalog_mod
from scripts.embedding_research import run as run_mod
from scripts.embedding_research.baseline import MEDOID_STRATEGY_TYPE, medoid_strategy_key_for
from scripts.embedding_research.catalog_identity import exact_segmentation_hash, search_representation_hash
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.helpers.binning import (
    DIST_FNS,
    distance_metric_label,
    global_dist,
    perdim_dist,
)
from scripts.embedding_research.streams.store import HeadStreamStore

pytestmark = pytest.mark.unit

BACKBONE = "effnet"
SONGS4 = ("s1", "s2", "s3", "s4")
SONGS3 = ("s1", "s2", "s3")
P = 6  # every fixture stream is six patches wide (all searchable by default).

#: The exact finite suffixed 18-key vocabulary a class / medoid pass emits (amended P3-S2).
SUFFIXED18 = frozenset(
    {
        "map_k_artist",
        "mrr_artist",
        "ndcg_k_artist",
        "recall_k_artist",
        "disc_artist",
        "map_k_genre",
        "mrr_genre",
        "ndcg_k_genre",
        "recall_k_genre",
        "disc_genre",
        "map_k_head",
        "mrr_head",
        "ndcg_k_head",
        "recall_k_head",
        "disc_head",
        "n_queries_artist",
        "n_queries_genre",
        "n_queries_head",
    }
)

#: Two full-tuple groups whose membership is IDENTICAL across the artist / genre / head rulers here
#: (A,A|B,B artist, g1,g1|g2,g2 genre, and the head groups (gender0,timbre1) | (gender1,timbre0)).
ART_AB = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}
GEN_AB = {"s1": "g1", "s2": "g1", "s3": "g2", "s4": "g2"}
#: head tuple (side) constants — col1 mean >= 0.5 => side 1, else side 0.
_HEAD_TUPLE_X = {"timbre": 0.9, "gender": 0.2}  # side gender=0 female, timbre=1 dark
_HEAD_TUPLE_Y = {"timbre": 0.2, "gender": 0.9}  # side gender=1 male, timbre=0 bright
_HEAD_TWO_GROUP = {
    "s1": dict(_HEAD_TUPLE_X),
    "s2": dict(_HEAD_TUPLE_X),
    "s3": dict(_HEAD_TUPLE_Y),
    "s4": dict(_HEAD_TUPLE_Y),
}

#: Single-head-tuple scenario (artist/genre all "A"/"g") with s4 carrying NO artist/genre and NO head
#: suite — every ruler evaluates only s1..s3, and the run must still succeed (never whole-run refusal).
ART_SINGLE = {"s1": "A", "s2": "A", "s3": "A", "s4": None}
GEN_SINGLE = {"s1": "g", "s2": "g", "s3": "g", "s4": None}
_HEAD_ONE_GROUP = {"s1": dict(_HEAD_TUPLE_X), "s2": dict(_HEAD_TUPLE_X), "s3": dict(_HEAD_TUPLE_X)}


# --------------------------------------------------------------------------- #
# Synthetic committed-corpus geometry (deterministic, no real audio/model)     #
# --------------------------------------------------------------------------- #


def _axis(i: int) -> np.ndarray:
    v = np.zeros(4, dtype=np.float32)
    v[i] = 1.0
    return v


def _stream(axis: int) -> np.ndarray:
    """Six unit rows: three on a basis axis, three at L2 distance 0.5 on the adjacent axis."""
    u = _axis(axis)
    theta = math.acos(1.0 - 0.5 * 0.5 / 2.0)
    o = _axis((axis + 1) % 4)
    p = (u * math.cos(theta) + o * math.sin(theta)).astype(np.float32)
    return np.stack([u, u, u, p, p, p])


def _binary(col1: float) -> np.ndarray:
    """A deterministic binary head activation ``[P, 2]`` whose class-1 column is ``col1`` everywhere."""
    arr = np.zeros((P, 2), dtype=np.float32)
    arr[:, 0] = 0.5
    arr[:, 1] = np.float32(col1)
    return arr


def _register_songs(con, art: dict, gen: dict) -> None:
    for song in sorted({*art, *gen}):
        con.execute(
            "INSERT INTO songs (song_id, path, artist, album, title, genre) VALUES (?, ?, ?, ?, ?, ?)",
            (song, f"/audio/{song}.mp3", art.get(song), f"album-{song}", f"title-{song}", gen.get(song)),
        )


def _build(compact_catalog_factory, con, out, *, art, gen, songs=SONGS4, bin_mode="temporal_global"):
    """A durable single-config compact catalog over the corpus, with songs registered on ``con``."""
    streams = {(s, BACKBONE): _stream(int(s[1]) - 1) for s in songs}
    configs = [
        catalog_mod.SegConfigInput(
            backbone=BACKBONE,
            bin_mode=bin_mode,
            threshold_configured=0.9,
            threshold_effective=0.9,
        )
    ]
    harness = compact_catalog_factory(con, out, streams=streams, configs=configs, song_ids=list(songs), run_id="golden")
    _register_songs(con, art, gen)
    return harness


def _publish_head_suites(harness, con, out, spec) -> None:
    """Publish committed aligned binary head suites per song in *spec* (song -> {head: col1}).

    Head suites are registered in the RESEARCH connection *con* (the full-stream-schema DB that
    owns the committed stream/mask registries), aligned to the committed group ``harness.stream_store``
    resolves, so ``resolve_head_ruler_labels`` finds them through the filesystem CURRENT markers.
    """
    store = harness.stream_store
    for song, heads in sorted(spec.items()):
        obs = store.load_committed_observation(song, BACKBONE)
        stream_ref = obs.identity.stream_ref
        payload = {head: _binary(col1) for head, col1 in heads.items()}
        HeadStreamStore(con, output_root=str(out)).publish(
            song,
            BACKBONE,
            payload,
            run_id="golden-heads",
            patch_count=P,
            alignment_version="1",
            expected_head_ids=sorted(payload),
            stream_ref=stream_ref,
        )


def _analyze(con, out, run_id):
    """Drive the REAL run.py::_run_analyze over the fixture catalog (single-writer: handle closed)."""
    return run_mod._run_analyze(con, {"output_root": str(out), "backbones": [BACKBONE], "k": 10}, run_id=run_id)


def _decode_rows(con, run_id):
    """Raw decode of analyze_metrics under run_id into {strategy_type: {strategy_key: {metric: value}}}."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for sk, st, sim, k, metric, value in con.execute(
        "SELECT strategy_key, strategy_type, sim_metric, k, metric, value "
        "FROM analyze_metrics WHERE run_id = ? ORDER BY strategy_type, strategy_key, metric",
        (run_id,),
    ).fetchall():
        assert sim == "cosine" and k == 10
        out.setdefault(st, {}).setdefault(sk, {})[str(metric)] = float(value)
    return out


# --------------------------------------------------------------------------- #
# Arm (a) + (c): head evidence + medoid parity over a real harness             #
# --------------------------------------------------------------------------- #


def test_head_evidence_golden_two_groups(compact_catalog_factory, con, tmp_path):
    """Harness-path head-suite pooling -> exact committed-artifact evidence (two full-tuple groups)."""
    out = tmp_path / "a"
    harness = _build(compact_catalog_factory, con, out, art=ART_AB, gen=GEN_AB)
    try:
        _publish_head_suites(harness, con, out, _HEAD_TWO_GROUP)
        labels = ca.resolve_head_ruler_labels(harness.stream_store, str(out), list(SONGS4), BACKBONE)
        assert set(labels) == set(SONGS4)
        # Canonical sorted head order: gender < timbre (never insertion order). Exact labels/pooled.
        for song in ("s1", "s2"):
            hl = labels[song]
            assert hl.full_tuple == (("gender", 0), ("timbre", 1))
            assert hl.labels == ("female", "dark")
            assert len(hl.pooled) == 2 and abs(hl.pooled[0] - 0.2) < 1e-6 and abs(hl.pooled[1] - 0.9) < 1e-6
            assert hl.searchable_rows == P  # pooled over committed whole-song mask == 1 rows only
        for song in ("s3", "s4"):
            assert labels[song].full_tuple == (("gender", 1), ("timbre", 0))
            assert labels[song].labels == ("male", "bright")
        assert labels["s1"].head_ids == "gender,timbre"
    finally:
        harness.close()


def test_ruler_guards_and_relevance_over_two_groups(compact_catalog_factory, con, tmp_path):
    """Two distinct tuple groups => head guard OFF (computed); every song has a same-tuple partner."""
    out = tmp_path / "a2"
    harness = _build(compact_catalog_factory, con, out, art=ART_AB, gen=GEN_AB)
    try:
        _publish_head_suites(harness, con, out, _HEAD_TWO_GROUP)
        cfg = ca.CatalogAnalysisConfig(
            run_id="r",
            backbone=BACKBONE,
            song_ids=list(SONGS4),
            artists=dict(ART_AB),
            genres=dict(GEN_AB),
            head_labels=ca.resolve_head_ruler_labels(harness.stream_store, str(out), list(SONGS4), BACKBONE),
            k=10,
        )
        result = ca.analyze_catalog_corpus(harness.stream_store, harness.con, cfg, research_con=con)
        assert result.comparable and result.finite
        assert set(result.metrics) == SUFFIXED18
        # All three rulers are active over all four queries; head has a same-tuple partner for each.
        for ruler in ("artist", "genre", "head"):
            rr = result.rulers[ruler]
            assert rr.active and rr.n_queries == 4
            assert np.isfinite(rr.map_k) and rr.map_k == pytest.approx(2.0 / 3.0)
            assert np.isfinite(rr.disc)
        # Two distinct tuple groups -> the head discrimination guard is OFF (computed, not guarded).
        assert result.rulers["head"].disc_guard == ""
        assert result.ruler_sources["artist"].source == "songs.artist"
        assert result.ruler_sources["genre"].source == "songs.genre"
        assert result.ruler_sources["head"].source.startswith("head:effnet")
        # No generic unsuffixed or composite aggregate survives on the result surface.
        assert not {"map_k", "mrr", "ndcg_k", "recall_k", "disc"} & set(result.metrics)
    finally:
        harness.close()


def test_single_tuple_group_guarded_finite_zero(compact_catalog_factory, con, tmp_path):
    """<2 distinct tuple groups => head disc is the guarded finite 0.0 (guard visible in evidence)."""
    out = tmp_path / "a3"
    harness = _build(compact_catalog_factory, con, out, art=ART_SINGLE, gen=GEN_SINGLE, songs=SONGS3)
    try:
        _publish_head_suites(harness, con, out, _HEAD_ONE_GROUP)
        cfg = ca.CatalogAnalysisConfig(
            run_id="r",
            backbone=BACKBONE,
            song_ids=list(SONGS3),
            artists={"s1": "A", "s2": "A", "s3": "A"},
            genres={"s1": "g", "s2": "g", "s3": "g"},
            head_labels=ca.resolve_head_ruler_labels(harness.stream_store, str(out), list(SONGS3), BACKBONE),
            k=10,
        )
        result = ca.analyze_catalog_corpus(harness.stream_store, harness.con, cfg, research_con=con)
        assert result.comparable
        head = result.rulers["head"]
        assert head.active and head.n_queries == 3
        assert head.disc == 0.0
        assert "distinct tuple groups" in head.disc_guard and "1" in head.disc_guard
    finally:
        harness.close()


def test_persist_three_ruler_families_class_and_medoid(compact_catalog_factory, con, tmp_path):
    """A real _run_analyze persists the suffixed 18-key vocab on class AND observed-medoid rows."""
    out = tmp_path / "persist"
    harness = _build(compact_catalog_factory, con, out, art=ART_AB, gen=GEN_AB)
    try:
        _publish_head_suites(harness, con, out, _HEAD_TWO_GROUP)
        harness.handle.close()  # let run.py reopen the durable snapshot read-only (single-writer)
        ret = _analyze(con, out, "RUN-P3S4")
        assert ret["song_count"] == 4 and ret["self_recorded"] is True
        decoded = _decode_rows(con, "RUN-P3S4")
        # Exactly one segmented class pass + exactly one observed global-medoid baseline.
        class_rows = decoded["catalog"]
        medoid_rows = decoded[MEDOID_STRATEGY_TYPE]
        assert len(class_rows) == 1
        assert len(medoid_rows) == 1
        medoid_key = medoid_strategy_key_for(BACKBONE)
        assert medoid_key in medoid_rows
        # Arm (b): the exact suffixed 18-key vocab on BOTH surfaces — no generic key survives.
        class_metrics = next(iter(class_rows.values()))
        medoid_metrics = medoid_rows[medoid_key]
        assert set(class_metrics) == SUFFIXED18
        assert set(medoid_metrics) == SUFFIXED18
        # n_queries_* present and ruler-evaluable-only (every song has a same-tuple partner here).
        assert class_metrics["n_queries_artist"] == 4
        assert class_metrics["n_queries_genre"] == 4
        assert class_metrics["n_queries_head"] == 4
        assert class_metrics["map_k_head"] == pytest.approx(2.0 / 3.0)
        assert np.isfinite(class_metrics["disc_head"]) and np.isfinite(medoid_metrics["disc_head"])
        # Arm (c) parity: the medoid rows carry the SAME three suffixed ruler families + n_queries.
        for suffix in ("map_k", "mrr", "ndcg_k", "recall_k", "disc", "n_queries"):
            for ruler in ("artist", "genre", "head"):
                assert f"{suffix}_{ruler}" in medoid_metrics
        # The medoid baseline is a NON-catalog 'global_pool' row and never a class/winner candidate.
        assert medoid_key not in class_rows
        assert next(iter(class_rows)) != medoid_key
        assert medoid_metrics == pytest.approx(class_metrics)  # same corpus/k/cosine scope geometry
    finally:
        harness.close()


def test_flat_per_song_artist_only_surface(compact_catalog_factory, con, tmp_path):
    """Per-song rows are artist-only: ap_k/mrr/recall_k + disc_artist_contrib populated; genre/head empty."""
    out = tmp_path / "per-song"
    harness = _build(compact_catalog_factory, con, out, art=ART_AB, gen=GEN_AB)
    try:
        _publish_head_suites(harness, con, out, _HEAD_TWO_GROUP)
        harness.handle.close()
        _analyze(con, out, "RUN-P3S4-PS")
        decoded = _decode_rows(con, "RUN-P3S4-PS")
        class_key = next(iter(decoded["catalog"]))
        rows = con.execute(
            "SELECT song_id, ap_k, mrr, recall_k, disc_artist_contrib, disc_genre_contrib, "
            "disc_head_contrib FROM song_retrieval_metrics WHERE strategy_key = ? ORDER BY song_id",
            (class_key,),
        ).fetchall()
        by_song = {r[0]: r for r in rows}
        assert set(by_song) == set(SONGS4)
        # s1/s2 (artist A) — the other A is the only same-artist candidate, ranking first -> ap/mrr 1.0.
        for song in ("s1", "s2"):
            _, ap, mrr, recall, disc_a, disc_g, disc_h = by_song[song]
            assert ap == pytest.approx(1.0) and mrr == pytest.approx(1.0) and recall == pytest.approx(1.0)
            assert disc_a == pytest.approx(0.0)  # finite artist per-song contribution
            assert disc_g is None and disc_h is None  # genre/head per-song is historical-empty (no DDL)
        # s3/s4 (artist B) — one of two same-artist candidates at rank 3 -> ap/mrr = 1/3.
        for song in ("s3", "s4"):
            _, ap, mrr, recall, disc_a, disc_g, disc_h = by_song[song]
            assert ap == pytest.approx(1.0 / 3.0) and mrr == pytest.approx(1.0 / 3.0)
            assert recall == pytest.approx(1.0)
            assert disc_a == pytest.approx(0.0) and disc_g is None and disc_h is None
    finally:
        harness.close()


def test_missing_artist_genre_label_is_per_ruler_exclusion_not_unknown(compact_catalog_factory, con, tmp_path):
    """A song with no artist/genre/head evidence is excluded per-ruler — never 'unknown', no refusal."""
    out = tmp_path / "missing"
    harness = _build(compact_catalog_factory, con, out, art=ART_SINGLE, gen=GEN_SINGLE, songs=SONGS4)
    try:
        _publish_head_suites(harness, con, out, _HEAD_ONE_GROUP)  # s4 has NO head suite
        # In-process rulers: s4 is a searchable candidate/query but labels are missing -> excluded.
        cfg = ca.CatalogAnalysisConfig(
            run_id="r",
            backbone=BACKBONE,
            song_ids=list(SONGS4),
            artists=dict(ART_SINGLE),
            genres=dict(GEN_SINGLE),
            head_labels=ca.resolve_head_ruler_labels(harness.stream_store, str(out), list(SONGS4), BACKBONE),
            k=10,
        )
        result = ca.analyze_catalog_corpus(harness.stream_store, harness.con, cfg, research_con=con)
        assert result.comparable  # never a whole-run refusal because ONE song lacks labels
        for ruler in ("artist", "genre", "head"):
            rr = result.rulers[ruler]
            src = result.ruler_sources[ruler]
            assert rr.active and rr.n_queries == 3
            assert src.song_count == 3 and src.missing_count == 1
        # No fabricated 'unknown' substitute label anywhere on the result's label maps/sources.
        for source in result.ruler_sources.values():
            assert "unknown" not in source.source.lower()
        assert "unknown" not in str(dict(ART_SINGLE)).lower()  # raw songs.artist is genuinely NULL/absent
        harness.handle.close()
        # Persistence: the CLI analyze still succeeds and records n_queries = 3 for every ruler.
        _analyze(con, out, "RUN-MISSING")
        decoded = _decode_rows(con, "RUN-MISSING")
        class_key = next(iter(decoded["catalog"]))
        class_metrics = decoded["catalog"][class_key]
        assert class_metrics["n_queries_artist"] == 3
        assert class_metrics["n_queries_genre"] == 3
        assert class_metrics["n_queries_head"] == 3
        assert class_metrics["map_k_head"] == pytest.approx(1.0)  # single relevance group, all retrieved
        # Only the three labelled songs produce artist per-song rows (s4 excluded from the ruler).
        song_ids = {
            r[0]
            for r in con.execute(
                "SELECT song_id FROM song_retrieval_metrics WHERE strategy_key = ?", (class_key,)
            ).fetchall()
        }
        assert song_ids == set(SONGS3)
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# Arm (d): experiment-identity golden (bin_mode -> executed distance dispatch) #
# --------------------------------------------------------------------------- #


def test_bin_mode_distance_dispatch_matches_advertised_metric():
    """temporal_global executes global_dist (l2); temporal_perdim executes perdim_dist (chebyshev)."""
    assert DIST_FNS["temporal_global"] is global_dist
    assert DIST_FNS["temporal_perdim"] is perdim_dist
    # The advertised label is derived from the EXECUTED function identity (never stored).
    assert distance_metric_label("temporal_global") == "l2"
    assert distance_metric_label("temporal_perdim") == "chebyshev"
    # The two executed metrics are genuinely different distance functions.
    a = global_dist(np.array([0.0, 0.0]), np.array([0.6, 0.8]))
    b = perdim_dist(np.array([0.0, 0.0]), np.array([0.6, 0.8]))
    assert math.isclose(a, 1.0) and math.isclose(b, 0.8)  # l2 magnitude vs chebyshev per-dim max


def test_equal_numeric_thresholds_distinct_identities_across_bin_modes(compact_catalog_factory, con, tmp_path):
    """Equal numeric thresholds under temporal_global vs temporal_perdim are separate experiments."""
    out = tmp_path / "ident"
    streams = {(s, BACKBONE): _stream(int(s[1]) - 1) for s in SONGS4}
    configs = [
        catalog_mod.SegConfigInput(
            backbone=BACKBONE, bin_mode="temporal_global", threshold_configured=0.9, threshold_effective=0.9
        ),
        catalog_mod.SegConfigInput(
            backbone=BACKBONE, bin_mode="temporal_perdim", threshold_configured=0.9, threshold_effective=0.9
        ),
    ]
    harness = compact_catalog_factory(
        con, out, streams=streams, configs=configs, song_ids=list(SONGS4), run_id="golden-ident"
    )
    try:
        cfg_rows = harness.con.execute(
            "SELECT config_id, bin_mode, threshold_effective, threshold_semantics, canonical_config_hash "
            "FROM seg_config ORDER BY config_id"
        ).fetchall()
        by_mode = {r[1]: r for r in cfg_rows}
        g, pd = by_mode["temporal_global"], by_mode["temporal_perdim"]
        # Same numeric threshold + same direct-L2 semantics, yet DIFFERENT experiment identities.
        assert g[2] == pd[2] == 0.9
        assert g[3] == pd[3] == "direct_distance"
        assert g[4] != pd[4]  # distinct canonical config hashes
        # Search/exact leaves fold the bin_mode + derived distance metric: never collapsed/deduped.
        assert search_representation_hash(harness.con, g[0]) != search_representation_hash(harness.con, pd[0])
        assert exact_segmentation_hash(harness.con, g[0]) != exact_segmentation_hash(harness.con, pd[0])
    finally:
        harness.close()


def test_canonical_semantic_head_phase_is_l2_primary_only():
    """The canonical head phase selects temporal_global (L2) only — temporal_perdim is not eligible."""
    from scripts.embedding_research.common.head_analysis import PTC_SEMANTICS, TEMPORAL_BIN_MODES
    from scripts.embedding_research.helpers.thresholds import DIRECT_DISTANCE

    assert frozenset({"temporal_global"}) == TEMPORAL_BIN_MODES
    assert "temporal_perdim" not in TEMPORAL_BIN_MODES
    assert frozenset({"direct_distance"}) == PTC_SEMANTICS
    assert DIRECT_DISTANCE == "direct_distance"  # the advertised == executed direct-threshold semantics


def test_suffixed_and_generic_key_boundaries():
    """The canonical ruler vocabulary is exactly the suffixed 18-key set — bare generic keys absent."""
    from scripts.embedding_research.common.catalog_analysis import _RULER_NAMES

    assert tuple(_RULER_NAMES) == ("artist", "genre", "head")
    # Every vocabulary key is suffixed with a ruler; none is bare or composite/optimization-scored.
    for key in SUFFIXED18:
        assert any(key.endswith(f"_{r}") for r in ("artist", "genre", "head"))
    assert "map_k" not in SUFFIXED18 and "mrr" not in SUFFIXED18 and "ndcg_k" not in SUFFIXED18
    assert "recall_k" not in SUFFIXED18 and "disc" not in SUFFIXED18
    assert not {k for k in SUFFIXED18 if "_" not in k}
