"""Phase 2 tests: matching-corpus manifests, cache identity, and skip diagnostics.

Covers corpus.py (MatchingCorpusManifest / build_matching_corpus /
validate_matching_corpus), cache_identity.py (matrix_cache_identity /
validate_matrix_cache_identity / versioned_cache_root), and the run.py
loader + analyze() orchestration wiring that enforces the manifest.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import numpy as np
import pytest

from scripts.embedding_research import run
from scripts.embedding_research.cache_identity import (
    SCORING_SEMANTICS_VERSION,
    matrix_cache_identity,
    validate_matrix_cache_identity,
    versioned_cache_root,
)
from scripts.embedding_research.corpus import (
    MatchingCorpusManifest,
    build_matching_corpus,
    corpus_identity_hash,
    validate_matching_corpus,
)
from scripts.embedding_research.helpers.binning import BIN_MODES
from scripts.embedding_research.vector_types import UnitTensor

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# MatchingCorpusManifest
# ---------------------------------------------------------------------------


def test_manifest_is_immutable_and_canonically_sorted() -> None:
    manifest = MatchingCorpusManifest(
        song_ids=("c", "a", "b"),
        corpus_hash=corpus_identity_hash("effnet", ["a", "b", "c"]),
        backbone="effnet",
    )
    assert manifest.song_ids == ("a", "b", "c")  # canonical sorted order
    assert len(manifest) == 3
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.song_ids = ()  # type: ignore[misc]  # frozen dataclass


def test_manifest_equality_ignores_input_order() -> None:
    m1 = MatchingCorpusManifest(("b", "a"), "h", "effnet")
    m2 = MatchingCorpusManifest(("a", "b"), "h", "effnet")
    assert m1 == m2


def test_corpus_identity_hash_stable_and_sensitive() -> None:
    ids = ["a", "b", "c"]
    h1 = corpus_identity_hash("effnet", ids, {"rep_types": ["mean"], "k": 10})
    h2 = corpus_identity_hash("effnet", list(reversed(ids)), {"rep_types": ["mean"], "k": 10})
    assert h1 == h2  # order-insensitive over the song-ID set
    assert corpus_identity_hash("musicnn", ids) != h1  # backbone sensitive
    assert corpus_identity_hash("effnet", ["a", "b", "d"]) != h1  # song-set sensitive
    assert corpus_identity_hash("effnet", ids, {"rep_types": ["median"]}) != h1  # config sensitive


def test_build_matching_corpus_intersects_requirements() -> None:
    universe = ["a", "b", "c", "d", "e"]
    requirements = {
        "flat:medoid": ["a", "b", "c", "d"],
        "flat:mean": ["a", "b", "c"],
        "ptc:quantile0.1:0.50": ["a", "c"],
        "ctp:emb512:0.50": ["c", "a", "b"],
    }
    manifest = build_matching_corpus("effnet", universe, requirements, eligibility_inputs={"k": 10})
    # "e" never appears in any requirement; "b"/"d" are absent from some
    # requirement; only "a" and "c" are present in every requirement.
    assert manifest.song_ids == ("a", "c")
    assert manifest.backbone == "effnet"
    assert len(manifest.corpus_hash) == 64


def test_build_matching_corpus_deterministic() -> None:
    requirements = {"flat:medoid": ["b", "a"], "ptc:m:0.50": ["a", "b"]}
    m1 = build_matching_corpus("effnet", ["a", "b"], requirements, eligibility_inputs={"k": 5})
    m2 = build_matching_corpus("effnet", ["b", "a"], requirements, eligibility_inputs={"k": 5})
    assert m1 == m2
    assert m1.corpus_hash == m2.corpus_hash


def test_validate_matching_corpus_exact_match_passes() -> None:
    manifest = MatchingCorpusManifest(("a", "b", "c"), "h", "effnet")
    validate_matching_corpus(manifest, ["a", "b", "c"], "ctx")  # no raise


def test_validate_matching_corpus_fails_on_id_set_mismatch() -> None:
    manifest = MatchingCorpusManifest(("a", "b", "c"), "h", "effnet")
    with pytest.raises(ValueError, match="song-ID set mismatch"):
        validate_matching_corpus(manifest, ["a", "b"], "ctx")  # missing c
    with pytest.raises(ValueError, match="song-ID set mismatch"):
        validate_matching_corpus(manifest, ["a", "b", "d"], "ctx")  # extra d


def test_validate_matching_corpus_fails_on_order_mismatch() -> None:
    manifest = MatchingCorpusManifest(("a", "b", "c"), "h", "effnet")
    with pytest.raises(ValueError, match="song-ID order mismatch"):
        validate_matching_corpus(manifest, ["c", "b", "a"], "ctx")


# ---------------------------------------------------------------------------
# Cache identity
# ---------------------------------------------------------------------------


def _identity(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "backbone": "effnet",
        "pathway": "ptc",
        "threshold": 0.5,
        "rep_a": "mean",
        "rep_b": "median",
        "aggregate": "target_weighted",
        "metric": "cosine",
        "song_ids": ["a", "b", "c"],
        "corpus_hash": "abc123",
    }
    kwargs.update(overrides)
    return matrix_cache_identity(**kwargs)  # type: ignore[arg-type]


def test_matrix_cache_identity_changes_with_every_dimension() -> None:
    base = _identity()
    mutations = {
        "corpus_hash": _identity(corpus_hash="def456"),
        "backbone": _identity(backbone="musicnn"),
        "pathway": _identity(pathway="ctp"),
        "threshold": _identity(threshold=0.75),
        "rep_a": _identity(rep_a="median"),
        "rep_b": _identity(rep_b="mean"),
        "aggregate": _identity(aggregate="bidirectional_weighted"),
        "metric": _identity(metric="l2"),
        "song_ids": _identity(song_ids=["a", "b", "d"]),
    }
    for label, mutated in mutations.items():
        assert mutated != base, f"{label} did not change the identity"


def test_matrix_cache_identity_sensitive_to_song_order() -> None:
    ordered = _identity(song_ids=["a", "b", "c"])
    reordered = _identity(song_ids=["c", "b", "a"])
    assert ordered != reordered


def test_matrix_cache_identity_includes_scoring_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """SCORING_SEMANTICS_VERSION is embedded in the identity payload.

    A version bump yields a new identity even when every other dimension is
    unchanged, so old cache roots are orphaned (versioned invalidation).
    """
    from scripts.embedding_research import cache_identity

    payload = {
        "backbone": "effnet",
        "pathway": "ptc",
        "threshold": 0.5,
        "rep_a": "mean",
        "rep_b": "mean",
        "aggregate": "target_weighted",
        "metric": "cosine",
        "song_ids": ["a"],
        "corpus_hash": "abc",
    }
    v1 = matrix_cache_identity(**payload)
    monkeypatch.setattr(cache_identity, "SCORING_SEMANTICS_VERSION", 2)
    v2 = matrix_cache_identity(**payload)
    assert v1 != v2


def test_validate_matrix_cache_identity() -> None:
    expected = _identity()
    validate_matrix_cache_identity(expected, None, "ctx")  # no stored -> ok
    validate_matrix_cache_identity(expected, expected, "ctx")  # match -> ok
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_matrix_cache_identity(expected, _identity(corpus_hash="other"), "ctx")


def test_versioned_cache_root_orphans_old_roots(tmp_path: Path) -> None:
    base = tmp_path / "cache"
    v1 = versioned_cache_root(base, scoring_version=1, corpus_hash="abc")
    assert v1 == base / "v1" / "abc"
    v2 = versioned_cache_root(base, scoring_version=2, corpus_hash="abc")
    v1_other = versioned_cache_root(base, scoring_version=1, corpus_hash="def")
    # Distinct version/corpus roots coexist on disk; old roots are not rewritten.
    assert v1 != v2 and v1 != v1_other
    assert v2 == base / "v2" / "abc"
    assert v1_other == base / "v1" / "def"
    assert SCORING_SEMANTICS_VERSION == 1


# ---------------------------------------------------------------------------
# Loader wiring (run.py restricts to the matching corpus)
# ---------------------------------------------------------------------------


def test_global_pool_loader_restricts_to_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    superset_sids = ["d", "a", "c", "b", "e"]
    vecs = np.zeros((5, 2), dtype=np.float32)
    monkeypatch.setattr(
        run.flat_vecs,
        "load_matrix",
        lambda _bb, _strat, _con: (vecs, list(superset_sids), ["a"] * 5, ["l"] * 5, ["g"] * 5),
    )
    manifest = MatchingCorpusManifest(("c", "b", "a"), corpus_identity_hash("effnet", ["a", "b", "c"]), "effnet")
    vecs_out, sids, artists, albums, genres = run._load_global_pool_analyze_vecs(
        "effnet", "mean", None, {"matching_corpus": {"effnet": manifest}}
    )
    assert sids == ["a", "b", "c"]  # manifest sorted order, non-manifest songs dropped
    assert artists == ["a", "a", "a"]
    assert albums == ["l", "l", "l"]
    assert genres == ["g", "g", "g"]
    assert vecs_out.shape == (3, 2)


def test_ptc_loader_restricts_discovery_to_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = MatchingCorpusManifest(("a", "b", "c"), corpus_identity_hash("effnet", ["a", "b", "c"]), "effnet")
    list_called: list[bool] = []

    def fake_list_sids(_bb, _bin_mode, _thresh):
        list_called.append(True)
        return ["x", "y", "z"]  # would be used only when no manifest is wired

    def fake_load_bin_stats(_bb, _bin_mode, _thresh, sid):
        assert sid in manifest.song_ids, f"loader queried non-manifest sid {sid}"
        return [{"weight": 1}, {"weight": 2}]

    def fake_load_norm_pair(_bb, _bin_mode, _thresh, _sid, _rep_a, _rep_b):
        empty = UnitTensor(np.zeros((2, 2), dtype=np.float32))
        return empty, empty

    monkeypatch.setattr(run.binned_ptc, "list_sids", fake_list_sids)
    monkeypatch.setattr(run.binned_ptc, "load_bin_stats", fake_load_bin_stats)
    monkeypatch.setattr(run.binned_ptc, "load_norm_pair", fake_load_norm_pair)

    name = f"ptc_{BIN_MODES[0]}_0.50"
    _out, sids, _artists, _albums, _genres = run._load_ptc_analyze_vecs(
        "effnet", name, None, {"rep_types": ["mean"], "matching_corpus": {"effnet": manifest}}
    )
    assert list_called == []  # discovery used the manifest, not the cache listing
    assert sids == ["a", "b", "c"]


def test_ctp_loader_passes_manifest_song_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = MatchingCorpusManifest(("a", "b", "c"), corpus_identity_hash("effnet", ["a", "b", "c"]), "effnet")
    captured: dict[str, object] = {}
    bin_row = {"weight": 2, "outlier_count": 0, "vec_mean_norm": np.array([1.0, 0.0], dtype=np.float32)}
    song_data = [[dict(bin_row) for _ in range(2)] for _ in range(3)]

    def fake_load_all_reps(_con, _bb, _head, _thresh, song_ids=None):
        captured["song_ids"] = song_ids
        return ["a", "b", "c"], ["u"] * 3, song_data

    monkeypatch.setattr(run.binned_ctp, "load_all_reps", fake_load_all_reps)

    _out, sids, _artists, _albums, _genres = run._load_ctp_analyze_vecs(
        "effnet", "ctp_emb512_0.50", None, {"rep_types": ["mean"], "matching_corpus": {"effnet": manifest}}
    )
    assert captured["song_ids"] == frozenset(manifest.song_ids)
    assert sids == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# analyze() skip + diagnostics
# ---------------------------------------------------------------------------


def test_analyze_skips_corpus_mismatch_and_records_reason(con) -> None:
    from scripts.embedding_research import common

    manifest = MatchingCorpusManifest(("a", "b", "c"), corpus_identity_hash("effnet", ["a", "b", "c"]), "effnet")

    def load(_bb, _strategy, _con, _extra):
        # Returns a song set that differs from the manifest (missing "c", extra "d").
        return (np.zeros((3, 2), dtype=np.float32), ["a", "b", "d"], ["x"] * 3, ["y"] * 3, ["z"] * 3)

    cfg = {
        "strategy_names": ["mean"],
        "load_vecs_fn": load,
        "db_write_fn": lambda *_a, **_k: None,
        "strategy_key_fn": lambda _bb, _s, _e: "global_pool:effnet:mean",
        "strategy_type": "global_pool",
        "extra_cfg": {"matching_corpus": {"effnet": manifest}},
    }
    common.analyze.analyze(con, cfg, backbones=["effnet"], force=True, k=10)

    reasons = cfg["extra_cfg"]["skip_reasons"]
    assert any("song-ID set mismatch" in r for r in reasons)
    # Nothing written: unequal corpora must not produce reportable rows.
    assert con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 0


def test_analyze_records_load_failure_skip_reason(con, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.embedding_research import common

    def bad_load(_bb, _strategy, _con, _extra):
        raise RuntimeError("boom")

    cfg = {
        "strategy_names": ["mean"],
        "load_vecs_fn": bad_load,
        "db_write_fn": lambda *_a, **_k: None,
        "strategy_key_fn": lambda _bb, _s, _e: "global_pool:effnet:mean",
        "strategy_type": "global_pool",
        "extra_cfg": {},
    }
    monkeypatch.setattr(common.analyze, "_load_head_scores_and_names", lambda _bb, _s: ([], []))
    common.analyze.analyze(con, cfg, backbones=["effnet"], force=True, k=10)
    assert any("vector load failed" in r for r in cfg["extra_cfg"]["skip_reasons"])
