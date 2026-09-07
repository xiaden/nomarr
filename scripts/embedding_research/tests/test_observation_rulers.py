"""Amended P3-S1 — deterministic tests for the three independent retrieval rulers.

Covers the COMPUTE layer delivered by Pass A1 (P3-S1): the per-ruler lens generalization
(artist / genre / head over every segmented class AND the observed global-medoid control),
the frozen semantic-head committed-artifact resolver (``resolve_head_ruler_labels``), the
full-tuple relevance + ``>= 2``-group discrimination guard, per-ruler missing-label (null /
blank) exclusion, and RESULT-level ruler + label-source delivery (``CatalogAnalysisConfig`` /
``CatalogAnalysisResult`` gain ``rulers``/``ruler_sources``).  Persistence-key relabeling is
A2's (P3-S2) surface and is NOT touched here.

All head artifacts are synthetic committed suites (deterministic, no real corpus/model/audio/
ONNX), CPU-only.  The artist ruler's suffixed emission (``map_k_artist/mrr_artist/
ndcg_k_artist/recall_k_artist/disc_artist``) equals the artist :class:`RulerResult` values.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import config as config_mod
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.common.catalog_analysis import (
    CatalogAnalysisConfig,
    HeadSongLabel,
    NonFiniteResultError,
    PerQueryResult,
)
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.masks import MaskPayload
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

_ARTISTS = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}


# --------------------------------------------------------------------------- #
# Synthetic committed-artifact helpers (stream + mask + head suite)            #
# --------------------------------------------------------------------------- #


@pytest.fixture
def head_con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _unit(rng, n: int, d: int) -> np.ndarray:
    """Deterministic float32 L2-unit rows (a normalized frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _commit_effnet(out, con, song_id, patch_count: int, mask, *, dim: int = 6, seed: int = 0):
    """Publish a committed observation group (stream + mask + commit marker) for ONE effnet song.

    Returns ``(store, stream_ref, embeddings)``.  ``store`` is the bound ``StreamStore`` used
    both for the commit and later by :func:`ca.resolve_head_ruler_labels`.
    """
    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(seed)
    arr = _unit(rng, patch_count, dim) if dim else rng.random((patch_count, dim)).astype(np.float32)
    m = np.asarray(mask, dtype=np.uint8)
    rec = store.publish(song_id, "effnet", arr, run_id="run-stream")
    store.publish_observation_group(
        rec,
        MaskPayload(
            song_id=song_id,
            backbone="effnet",
            patch_count=patch_count,
            mask=m,
            params_id="0" * 64,
            audio_content_sha256=hashlib.sha256(b"fx-audio").hexdigest(),
            run_id="run-stream",
            created_at=1,
        ),
    )
    store.reconcile()
    return store, rec.artifact_ref, arr


def _publish_head_suite(out, con, song_id, stream_ref, head_arrays: dict, patch_count: int) -> None:
    hs = HeadStreamStore(con, output_root=str(out))
    hs.publish(
        song_id,
        "effnet",
        head_arrays,
        run_id="run-heads",
        patch_count=patch_count,
        alignment_version="1",
        expected_head_ids=sorted(head_arrays),
        stream_ref=stream_ref,
    )


def _binary_head(patch_count: int, col1, *, head: str = "timbre") -> dict[str, np.ndarray]:
    """A deterministic binary head activation matrix ``[patch_count, 2]`` with col1 = *col1*."""
    col1 = np.asarray(col1, dtype=np.float32)
    arr = np.zeros((patch_count, 2), dtype=np.float32)
    arr[:, 0] = 0.5
    arr[:, 1] = col1
    return {head: arr}


def _hl(sid, *heads, pooled=None):
    """A hand-built HeadSongLabel (used for the pure lens-level tests — no artifact I/O)."""
    return HeadSongLabel(
        song_id=sid,
        backbone="effnet",
        full_tuple=tuple(heads),
        labels=tuple(config_mod.HEAD_LABELS[h][i] for h, i in heads),
        pooled=tuple(pooled) if pooled is not None else tuple(1.0 if i == 1 else 0.0 for _h, i in heads),
        searchable_rows=5,
        head_set_fingerprint="fp",
        head_ids=",".join(sorted(h for h, _i in heads)),
        dim_by_head=",".join(f"{h}=2" for h, _i in heads),
        alignment_version="1",
        stream_ref="streams/s.npy",
        stream_digest="s",
        mask_ref="m",
        mask_digest="md",
        commit_sha256="c",
    )


def _pq(query, scores):
    return PerQueryResult(
        query_song_id=query,
        score=max(scores.values()),
        winner_counts={},
        candidate_scores=dict(scores),
        candidate_keys=tuple(sorted(scores)),
        retained_count=0,
        dropped_count=0,
        variant="x",
    )


# --------------------------------------------------------------------------- #
# Frozen-head committed-artifact resolver                                      #
# --------------------------------------------------------------------------- #


def test_pooling_uses_only_committed_mask_equal_1_rows(head_con, tmp_path):
    out = tmp_path / "out"
    # P=5, only patch 0 searchable (mask==1); its class-1 act is 1.0, every masked row is 0.0.
    # All-rows mean would be 0.2 (<0.5 => index 0); the mask==1-only mean is 1.0 => index 1.
    store, stream_ref, _ = _commit_effnet(out, head_con, "s1", 5, [1, 0, 0, 0, 0], seed=1)
    _publish_head_suite(out, head_con, "s1", stream_ref, _binary_head(5, [1.0, 0.0, 0.0, 0.0, 0.0]), 5)

    labels = ca.resolve_head_ruler_labels(store, out, ("s1",), "effnet")
    assert set(labels) == {"s1"}
    hl = labels["s1"]
    assert hl.full_tuple == (("timbre", 1),)  # mask==1-only pooled 1.0 >= 0.5 => side 1
    assert hl.labels == ("dark",)
    assert hl.searchable_rows == 1
    assert abs(hl.pooled[0] - 1.0) < 1e-6
    assert hl.stream_ref == stream_ref
    assert hl.backbone == "effnet"


def test_pooling_boundary_0_5_side_index_1(head_con, tmp_path):
    out = tmp_path / "out"
    store_a, ref_a, _ = _commit_effnet(out, head_con, "a", 1, [1], seed=2)
    _publish_head_suite(out, head_con, "a", ref_a, _binary_head(1, [0.5]), 1)  # exactly 0.5 => index 1
    _store_b, ref_b, _ = _commit_effnet(out, head_con, "b", 1, [1], seed=3)
    _publish_head_suite(out, head_con, "b", ref_b, _binary_head(1, [0.25]), 1)  # < 0.5 => index 0

    labels = ca.resolve_head_ruler_labels(store_a, out, ("a", "b"), "effnet")
    assert labels["a"].full_tuple == (("timbre", 1),)
    assert labels["a"].labels == ("dark",)
    assert labels["b"].full_tuple == (("timbre", 0),)
    assert labels["b"].labels == ("bright",)
    assert abs(labels["a"].pooled[0] - 0.5) < 1e-6


def test_canonical_sorted_full_tuple_order(head_con, tmp_path):
    out = tmp_path / "out"
    store, stream_ref, _ = _commit_effnet(out, head_con, "s1", 2, [1, 1], seed=4)
    rng = np.random.default_rng(0)
    heads = {
        "timbre": rng.random((2, 2)).astype(np.float32),
        "gender": rng.random((2, 2)).astype(np.float32),
    }
    # Force deterministic class-1 means so gender -> 1, timbre -> 0.
    heads["gender"][:, 1] = 0.8
    heads["timbre"][:, 1] = 0.3
    _publish_head_suite(out, head_con, "s1", stream_ref, heads, 2)

    labels = ca.resolve_head_ruler_labels(store, out, ("s1",), "effnet")
    # Canonical sorted head order: gender < timbre (NOT the insertion order).
    assert labels["s1"].full_tuple == (("gender", 1), ("timbre", 0))
    assert labels["s1"].labels == ("male", "bright")
    assert labels["s1"].head_ids == "gender,timbre"


def test_missing_head_suite_is_per_ruler_exclusion_and_non_effnet_is_empty(head_con, tmp_path):
    out = tmp_path / "out"
    store, ref, _ = _commit_effnet(out, head_con, "hashead", 2, [1, 1], seed=5)
    _publish_head_suite(out, head_con, "hashead", ref, _binary_head(2, [0.9, 0.9]), 2)
    # "noheads" has a committed stream/mask group but NO head suite marker -> MISSING label.
    _commit_effnet(out, head_con, "noheads", 2, [1, 1], seed=6)

    labels = ca.resolve_head_ruler_labels(store, out, ("hashead", "noheads"), "effnet")
    assert set(labels) == {"hashead"}  # noheads excluded (never an error / never a default label)
    # Non-effnet backbones resolve NO head labels (head ruler is EffNet-only).
    assert ca.resolve_head_ruler_labels(store, out, ("hashead",), "musicnn") == {}


def test_present_non_finite_pooled_value_raises_non_finite(head_con, tmp_path, monkeypatch):
    out = tmp_path / "out"
    store, stream_ref, _ = _commit_effnet(out, head_con, "s1", 3, [1, 1, 1], seed=7)
    # Fabricate a committed-suite selection whose payload contains a present NaN at a searchable
    # row (bypassing the publish-time finiteness gate) to prove the resolver refuses, never coerces.
    bad = out / "heads" / "s1.effnet.bad.npz"
    bad.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((3, 2), dtype=np.float32)
    arr[:, 0] = 0.5
    arr[:, 1] = np.array([0.9, np.nan, 0.9], dtype=np.float32)
    np.savez(bad, timbre=arr)

    record = SimpleNamespace(
        artifact_ref=f"heads/{bad.name}",
        head_ids="timbre",
        dim_by_head="timbre=2",
        alignment_version="1",
        head_set_fingerprint="fp",
    )
    selection = SimpleNamespace(record=record, stream_ref=stream_ref, stream_digest="s")

    def _fake_resolve(*_args, **_kwargs):
        return selection

    monkeypatch.setattr("scripts.embedding_research.streams.heads_current.resolve_current_head_suite", _fake_resolve)
    with pytest.raises(NonFiniteResultError):
        ca.resolve_head_ruler_labels(store, out, ("s1",), "effnet")


# --------------------------------------------------------------------------- #
# Pure lens-level ruler semantics (no artifact I/O)                            #
# --------------------------------------------------------------------------- #


def test_artist_bare_emission_equals_artist_ruler():
    songs = ("s1", "s2", "s3", "s4")
    cfg = CatalogAnalysisConfig(run_id="r", backbone="effnet", song_ids=songs, artists=_ARTISTS, k=10)
    per_query = [
        _pq(q, {c: (1.0 if _ARTISTS[c] == _ARTISTS[q] else 0.0) + 0.01 * (0 if c < q else 1) for c in songs if c != q})
        for q in songs
    ]
    lenses = ca._Lenses(cfg)
    metrics, per_song = lenses.evaluate(per_query)
    rulers, _sources = lenses.evaluate_rulers(per_query)
    ar = rulers["artist"]
    assert ar.active and ar.n_queries == 4
    assert metrics["map_k_artist"] == pytest.approx(ar.map_k)
    assert metrics["mrr_artist"] == pytest.approx(ar.mrr)
    assert metrics["ndcg_k_artist"] == pytest.approx(ar.ndcg_k)
    assert metrics["recall_k_artist"] == pytest.approx(ar.recall_k)
    assert metrics["disc_artist"] == pytest.approx(ar.disc)
    assert set(per_song) == {"s1", "s2", "s3", "s4"}


def test_exact_full_tuple_relevance_and_no_same_tuple_query_exclusion():
    # s1/s2 share the SAME complete tuple -> relevant to each other.
    # s3 shares only ONE head with s1 (timbre side 1) but differs on gender -> NOT relevant (exact tuple).
    # s4 has a unique tuple -> no same-tuple candidate -> excluded from the head ruler.
    head_labels = {
        "s1": _hl("s1", ("timbre", 1), ("gender", 0)),
        "s2": _hl("s2", ("timbre", 1), ("gender", 0)),
        "s3": _hl("s3", ("timbre", 1), ("gender", 1)),
        "s4": _hl("s4", ("danceability", 0)),
    }
    songs = ("s1", "s2", "s3", "s4")
    cfg = CatalogAnalysisConfig(
        run_id="r",
        backbone="effnet",
        song_ids=songs,
        artists=_ARTISTS,
        genres={"s1": "g1", "s2": "g1", "s3": "g1", "s4": "g2"},
        head_labels=head_labels,
        k=10,
    )
    per_query = [_pq(q, {c: (2.0 if c < q else 1.0) for c in songs if c != q}) for q in songs]
    rulers, _s = ca._Lenses(cfg).evaluate_rulers(per_query)
    head = rulers["head"]
    # Only s1 and s2 have a same-full-tuple candidate (each other); s3/s4 have none.
    assert head.active and head.n_queries == 2
    # Exact-tuple relevance: a query's only relevant song ranks first for these pairings.
    assert head.map_k == pytest.approx(1.0)


def test_head_discrimination_guard_single_group_and_two_group():
    # Single distinct full-tuple group => disc is FINITE guarded 0.0 (guard visible in evidence).
    hl1 = {"s1": _hl("s1", ("timbre", 1)), "s2": _hl("s2", ("timbre", 1)), "s3": _hl("s3", ("timbre", 1))}
    songs = ("s1", "s2", "s3")
    cfg1 = CatalogAnalysisConfig(run_id="r", backbone="effnet", song_ids=songs, artists=_ARTISTS, head_labels=hl1, k=10)
    per_query = [_pq(q, {c: 1.0 for c in songs if c != q}) for q in songs]
    head1 = ca._Lenses(cfg1).evaluate_rulers(per_query)[0]["head"]
    assert head1.active
    assert head1.disc == 0.0
    assert "distinct tuple groups" in head1.disc_guard

    # Two distinct groups + both pair sets present => disc is computed (guard empty).
    hl2 = {"s1": _hl("s1", ("timbre", 1)), "s2": _hl("s2", ("timbre", 1)), "s3": _hl("s3", ("timbre", 0))}
    cfg2 = CatalogAnalysisConfig(run_id="r", backbone="effnet", song_ids=songs, artists=_ARTISTS, head_labels=hl2, k=10)
    # Same-tuple (within) scores higher than cross-tuple scores => positive discrimination.
    per_query2 = [
        _pq("s1", {"s2": 0.9, "s3": 0.2}),
        _pq("s2", {"s1": 0.9, "s3": 0.2}),
        _pq("s3", {"s1": 0.1, "s2": 0.1}),
    ]
    head2 = ca._Lenses(cfg2).evaluate_rulers(per_query2)[0]["head"]
    # Two distinct tuple groups but group-0 has a single song => only the two group-1 queries
    # carry a same-tuple candidate (n_queries == 2); cross-tuple pairs are present (guard off).
    assert head2.active and head2.n_queries == 2
    assert head2.disc_guard == ""
    assert np.isfinite(head2.disc) and head2.disc > 0.0


def test_null_and_blank_artist_genre_labels_excluded_never_unknown():
    # s1/s2 have a real artist; s3/s4 have null/blank artist AND genre.  Missing labels are per-ruler
    # exclusions, never substituted with 'unknown' (which would fabricate a relevance group).
    songs = ("s1", "s2", "s3", "s4")
    cfg = CatalogAnalysisConfig(
        run_id="r",
        backbone="effnet",
        song_ids=songs,
        artists={"s1": "A", "s2": "A", "s3": None, "s4": "  "},
        genres={"s1": "g1", "s2": "g1", "s3": None, "s4": ""},
        k=10,
    )
    per_query = [_pq(q, {c: 1.0 for c in songs if c != q}) for q in songs]
    rulers, sources = ca._Lenses(cfg).evaluate_rulers(per_query)
    # Only s1/s2 carry an artist AND genre label => both rulers evaluate exactly those 2 queries.
    assert rulers["artist"].active and rulers["artist"].n_queries == 2
    assert rulers["genre"].active and rulers["genre"].n_queries == 2
    assert sources["artist"].song_count == 2 and sources["artist"].missing_count == 2
    assert sources["genre"].song_count == 2 and sources["genre"].missing_count == 2
    # The label maps contain no fabricated 'unknown' text at all.
    assert "unknown" not in json.dumps({s: a for s, a in cfg.artists.items() if isinstance(a, str)}).lower()


def test_per_ruler_independence():
    # artist groups follow artist; genre groups follow genre (independent membership/aggregation).
    songs = ("s1", "s2", "s3")
    cfg = CatalogAnalysisConfig(
        run_id="r",
        backbone="effnet",
        song_ids=songs,
        artists={"s1": "A", "s2": "A", "s3": "A"},  # all one artist
        genres={"s1": "g1", "s2": "g1", "s3": "g2"},  # g2 unique -> s3 has no same-genre candidate
        k=10,
    )
    per_query = [_pq(q, {c: 1.0 for c in songs if c != q}) for q in songs]
    rulers, _s = ca._Lenses(cfg).evaluate_rulers(per_query)
    # Genre ruler excludes s3 (no same-genre candidate); artist ruler includes all three.
    assert rulers["artist"].n_queries == 3
    assert rulers["genre"].n_queries == 2


# --------------------------------------------------------------------------- #
# Observed global-medoid control carries the same rulers                       #
# --------------------------------------------------------------------------- #


def test_medoid_control_carries_same_rulers(head_con, tmp_path):
    out = tmp_path / "out"
    refs = {}
    for i, song in enumerate(("s1", "s2", "s3")):
        store, ref, _ = _commit_effnet(out, head_con, song, 4, [1, 1, 1, 1], dim=6, seed=10 + i)
        refs[song] = (store, ref)
    store = refs["s1"][0]
    artists = {"s1": "A", "s2": "A", "s3": "B"}
    genres = {"s1": "g1", "s2": "g1", "s3": "g1"}
    head_labels = {
        "s1": _hl("s1", ("timbre", 1)),
        "s2": _hl("s2", ("timbre", 1)),
        "s3": _hl("s3", ("timbre", 0)),
    }
    bare = ca.analyze_medoid_baseline(
        store,
        backbone="effnet",
        song_ids=("s1", "s2", "s3"),
        artists=artists,
        genres=genres,
        head_labels=head_labels,
        k=10,
    )
    assert bare is not None
    rulers, sources = ca.analyze_medoid_baseline_rulers(
        store,
        backbone="effnet",
        song_ids=("s1", "s2", "s3"),
        artists=artists,
        genres=genres,
        head_labels=head_labels,
        k=10,
    )
    assert set(rulers) == {"artist", "genre", "head"}
    assert set(sources) == {"artist", "genre", "head"}
    assert bare["map_k_artist"] == pytest.approx(rulers["artist"].map_k)
    assert rulers["head"].active and rulers["head"].disc_guard == ""
    assert sources["head"].source.startswith("head:")


# --------------------------------------------------------------------------- #
# RESULT-level delivery through analyze_catalog_corpus                          #
# --------------------------------------------------------------------------- #


def test_result_level_rulers_and_label_sources(con, tmp_path, compact_catalog_factory):
    from scripts.embedding_research import catalog

    out = tmp_path / "out"
    rng = np.random.default_rng(3)
    songs = ("s1", "s2", "s3", "s4")
    streams = {(s, "effnet"): _unit(rng, 10, 6) for s in songs}
    harness = compact_catalog_factory(
        con,
        out,
        streams=streams,
        configs=[
            catalog.SegConfigInput(
                backbone="effnet", bin_mode="temporal_global", threshold_configured=0.7, threshold_effective=0.7
            )
        ],
        song_ids=list(songs),
        run_id="run-cat-rulers",
    )
    try:
        cfg = CatalogAnalysisConfig(
            run_id="run-rulers",
            backbone="effnet",
            song_ids=list(songs),
            artists=dict(_ARTISTS),
            genres={"s1": "g1", "s2": "g1", "s3": "g1", "s4": "g2"},
            head_labels={s: _hl(s, ("timbre", 1)) for s in songs},
            k=10,
        )
        result = ca.analyze_catalog_corpus(harness.stream_store, harness.con, cfg, research_con=con)
        assert result.comparable
        assert set(result.rulers) == {"artist", "genre", "head"}
        assert set(result.ruler_sources) == {"artist", "genre", "head"}
        # artist suffixed emission keys still present and equal the artist ruler.
        assert result.rulers["artist"].active
        assert result.metrics["map_k_artist"] == pytest.approx(result.rulers["artist"].map_k)
        assert result.metrics["disc_artist"] == pytest.approx(result.rulers["artist"].disc)
        assert "map_k_genre" in result.metrics and "map_k_head" in result.metrics
        assert "map_k" not in result.metrics  # no generic unsuffixed aggregate key survives
        # All four songs carry the same single-head tuple => exactly one distinct head group.
        assert result.rulers["head"].active
        assert result.rulers["head"].disc_guard != ""  # single-group guarded 0.0
        assert result.rulers["head"].disc == 0.0
        assert result.ruler_sources["artist"].source == "songs.artist"
        assert result.ruler_sources["genre"].source == "songs.genre"
        assert result.ruler_sources["head"].source.startswith("head:effnet")
        assert result.ruler_sources["head"].song_count == 4
        # Per-ruler n_queries is carried on each RulerResult.
        assert result.rulers["genre"].n_queries == 3  # s4's g2 is unique -> no same-genre candidate
    finally:
        harness.close()
