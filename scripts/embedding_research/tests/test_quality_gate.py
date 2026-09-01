"""Part C quality-gate tests: matching-corpus integrity, cache identity, and the
no-reportable-row-from-unequal-corpora binding.

Phase 3 adds the numerical + integration coverage that pins the P2 guarantees:

* every compared loader (flat / PTC / CTP) emits the SAME deterministic song set
  for a backbone (matching IDs — all compare);
* reordered song IDs fail loud and never silently reorder (no row is written);
* a song missing a required bin is excluded from the corpus, and a config left
  with < 2 songs is skipped with a recorded reason;
* a stale corpus hash is rejected at the cache-identity boundary;
* a scoring-semantics version bump orphans (but preserves) old cache roots while
  making them unread;
* the same representation-pair names over different underlying arrays do not
  collide (cache identity keys on the corpus data, not just the names);
* EffNet and MusicNN get independent matching corpora;
* no reportable flat OR binned row is emitted from unequal corpora.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.cache_identity import (
    matrix_cache_identity,
    validate_matrix_cache_identity,
    versioned_cache_root,
)
from scripts.embedding_research.corpus import (
    MatchingCorpusManifest,
    build_matching_corpus,
    corpus_identity_hash,
)
from scripts.embedding_research.helpers.binning import BIN_MODES
from scripts.embedding_research.vector_types import UnitTensor

if TYPE_CHECKING:
    from pathlib import Path


def _manifest(sids: list[str], backbone: str = "effnet") -> MatchingCorpusManifest:
    return MatchingCorpusManifest(
        tuple(sids),
        corpus_identity_hash(backbone, sids),
        backbone,
    )


def _flat_cfg(load_vecs_fn, *, extra_cfg: dict | None = None) -> dict:
    """A minimal global_pool AnalyzeCfg for analyze() orchestration tests."""
    from scripts.embedding_research import db as db_mod

    return {
        "strategy_names": ["mean"],
        "load_vecs_fn": load_vecs_fn,
        "db_write_fn": db_mod.write_analyze_metrics,
        "strategy_key_fn": lambda _bb, _s, _e: "global_pool:effnet:mean",
        "strategy_type": "global_pool",
        "extra_cfg": dict(extra_cfg or {}),
    }


# ---------------------------------------------------------------------------
# Matching IDs — all compared configurations run on the exact same corpus
# ---------------------------------------------------------------------------


def test_all_loaders_emit_matching_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flat, PTC, and CTP loaders all converge on the manifest's song set."""
    manifest = _manifest(["a", "b", "c"])

    # Flat loader: cache exposes a superset, loader restricts to the manifest.
    monkeypatch.setattr(
        run_mod.flat_vecs,
        "load_matrix",
        lambda _bb, _strat, _con: (
            np.zeros((5, 2), dtype=np.float32),
            ["e", "a", "c", "b", "d"],
            ["u"] * 5,
            ["u"] * 5,
            ["u"] * 5,
        ),
    )
    gp_sids = run_mod._load_global_pool_analyze_vecs("effnet", "mean", None, {"matching_corpus": {"effnet": manifest}})[
        1
    ]

    # PTC loader: discovers in manifest order and drops songs with no bins.
    monkeypatch.setattr(
        run_mod.binned_ptc,
        "load_bin_stats",
        lambda _bb, _bm, _t, sid: [{"weight": 1}] if sid in manifest.song_ids else [],
    )
    monkeypatch.setattr(
        run_mod.binned_ptc,
        "load_norm_pair",
        lambda _bb, _bm, _t, _sid, _a, _b: (
            UnitTensor(np.zeros((1, 2), dtype=np.float32)),
            UnitTensor(np.zeros((1, 2), dtype=np.float32)),
        ),
    )
    name = f"ptc_{BIN_MODES[0]}_0.50"
    ptc_sids = run_mod._load_ptc_analyze_vecs(
        "effnet", name, None, {"rep_types": ["mean"], "matching_corpus": {"effnet": manifest}}
    )[1]

    # CTP loader: restricted to the manifest song IDs.
    bin_row = {"weight": 1, "outlier_count": 0, "vec_mean_norm": np.array([1.0, 0.0], dtype=np.float32)}
    monkeypatch.setattr(
        run_mod.binned_ctp,
        "load_all_reps",
        lambda _con, _bb, _h, _t, _song_ids=None: (
            list(manifest.song_ids),
            ["u"] * 3,
            [[dict(bin_row)] for _ in range(3)],
        ),
    )
    ctp_sids = run_mod._load_ctp_analyze_vecs(
        "effnet", "ctp_emb512_0.50", None, {"rep_types": ["mean"], "matching_corpus": {"effnet": manifest}}
    )[1]

    assert gp_sids == ptc_sids == ctp_sids == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Reordered IDs — fail loud, never silently reorder, emit no row
# ---------------------------------------------------------------------------


def test_reordered_flat_ids_fail_loud_no_rows(con) -> None:
    """A loader returning IDs in a different order than the manifest is skipped (no row)."""
    from scripts.embedding_research import common

    manifest = _manifest(["a", "b", "c"])

    def load(_bb, _strategy, _con, _extra):
        # Same set, wrong order — must be rejected, never silently re-sorted.
        return (np.zeros((3, 2), dtype=np.float32), ["c", "a", "b"], ["x"] * 3, ["y"] * 3, ["z"] * 3)

    cfg = _flat_cfg(load, extra_cfg={"matching_corpus": {"effnet": manifest}})
    common.analyze.analyze(con, cfg, backbones=["effnet"], force=True, k=10)

    assert any("song-ID order mismatch" in r for r in cfg["extra_cfg"]["skip_reasons"])
    assert con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Missing bins — song excluded from corpus; config with <2 songs skipped
# ---------------------------------------------------------------------------


def test_missing_bin_song_excluded_from_corpus() -> None:
    """A song absent from any required bin sidecar is excluded from the matching corpus."""
    universe = ["a", "b", "c"]
    requirements = {
        "flat:medoid": ["a", "b", "c"],
        "flat:mean": ["a", "b", "c"],
        # "c" has no PTC bin data -> it cannot participate in any comparison.
        f"ptc:{BIN_MODES[0]}:0.50": ["a", "b"],
    }
    manifest = build_matching_corpus("effnet", universe, requirements)
    assert manifest.song_ids == ("a", "b")
    assert "c" not in manifest.song_ids


def test_missing_bin_config_skipped_with_reason(con) -> None:
    """A config whose matching corpus has < 2 songs is skipped with a recorded reason."""
    from scripts.embedding_research import common

    manifest = _manifest(["a"])  # only one song survives the bin intersection

    def load(_bb, _strategy, _con, _extra):
        return (np.zeros((1, 2), dtype=np.float32), ["a"], ["u"], ["u"], ["u"])

    cfg = _flat_cfg(load, extra_cfg={"matching_corpus": {"effnet": manifest}})
    common.analyze.analyze(con, cfg, backbones=["effnet"], force=True, k=10)

    assert any("< 2 matching-corpus songs" in r for r in cfg["extra_cfg"]["skip_reasons"])
    assert con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Stale corpus hashes — identity mismatch rejected
# ---------------------------------------------------------------------------


def _identity(*, corpus_hash: str, song_ids: list[str], rep_a: str = "mean", rep_b: str = "max") -> str:
    return matrix_cache_identity(
        backbone="effnet",
        pathway="ptc",
        threshold=0.5,
        rep_a=rep_a,
        rep_b=rep_b,
        aggregate="target_weighted",
        metric="cosine",
        song_ids=song_ids,
        corpus_hash=corpus_hash,
    )


def test_stale_corpus_hash_identity_rejected() -> None:
    """A cache entry built for a different (older) corpus hash is rejected, never reused."""
    current = _identity(corpus_hash="new_hash", song_ids=["a", "b"])
    stale = _identity(corpus_hash="old_hash", song_ids=["a", "b"])
    assert current != stale
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_matrix_cache_identity(current, stale, "ctx")


# ---------------------------------------------------------------------------
# Changed scoring version — v1 vs v2 roots differ, old root preserved but unread
# ---------------------------------------------------------------------------


def test_scoring_version_bump_orphans_old_root_preserved_unread(tmp_path: Path) -> None:
    """A version bump keeps the old root on disk but no longer reads from it."""
    base = tmp_path / "cache"
    old_root = versioned_cache_root(base, scoring_version=1, corpus_hash="abc")
    old_root.mkdir(parents=True)
    marker = old_root / "matrix.npz"
    marker.write_bytes(b"stale")

    new_root = versioned_cache_root(base, scoring_version=2, corpus_hash="abc")

    assert new_root != old_root
    assert marker.exists()  # old root preserved on disk, not deleted/rewritten
    assert not (new_root / "matrix.npz").exists()  # old data unread under the new root


# ---------------------------------------------------------------------------
# Representation-pair cache collisions — same names, different arrays do not collide
# ---------------------------------------------------------------------------


def test_rep_pair_same_names_different_arrays_no_collision() -> None:
    """Two corpora with identical rep names but different underlying arrays never share a cache key.

    The cache identity is keyed on the corpus data (via corpus_hash), not merely the
    representation names, so a stale matrix built from different arrays is unreachable.
    """
    reqs_2 = {"flat:medoid": ["a", "b"], "flat:mean": ["a", "b"]}
    reqs_3 = {"flat:medoid": ["a", "b", "c"], "flat:mean": ["a", "b", "c"]}
    corpus_2 = build_matching_corpus("effnet", ["a", "b", "c"], reqs_2)
    corpus_3 = build_matching_corpus("effnet", ["a", "b", "c"], reqs_3)
    assert corpus_2.song_ids != corpus_3.song_ids
    assert corpus_2.corpus_hash != corpus_3.corpus_hash

    # Identical rep_a/rep_b names in both calls — only the underlying corpus differs.
    id_2 = _identity(corpus_hash=corpus_2.corpus_hash, song_ids=list(corpus_2.song_ids))
    id_3 = _identity(corpus_hash=corpus_3.corpus_hash, song_ids=list(corpus_3.song_ids))
    assert id_2 != id_3


# ---------------------------------------------------------------------------
# Separate EffNet / MusicNN manifests
# ---------------------------------------------------------------------------


def test_separate_effnet_musicnn_manifests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each backbone gets its own independent matching corpus (never cross-averaged)."""

    def fake_corpus_requirements(backbone: str, _flat_strategies: list[str]):
        if backbone == "effnet":
            return {"flat:medoid": ["a", "b", "c"], f"ptc:{BIN_MODES[0]}:0.50": ["a", "b", "c"]}
        return {"flat:medoid": ["x", "y", "z"], f"ptc:{BIN_MODES[0]}:0.50": ["x", "y", "z"]}

    monkeypatch.setattr(run_mod, "_corpus_requirements", fake_corpus_requirements)
    cfg = {
        "backbones": ["effnet", "musicnn"],
        "flat_strategies": ["medoid", "mean"],
        "song_ids": ["a", "b", "c", "x", "y", "z"],
        "k": 10,
    }
    manifests = run_mod._build_backbone_manifests(cfg)

    assert set(manifests) == {"effnet", "musicnn"}
    assert manifests["effnet"].song_ids == ("a", "b", "c")
    assert manifests["musicnn"].song_ids == ("x", "y", "z")
    assert manifests["effnet"].corpus_hash != manifests["musicnn"].corpus_hash


# ---------------------------------------------------------------------------
# Binding: no reportable BINNED row is emitted from unequal corpora
# ---------------------------------------------------------------------------


def test_binned_unequal_corpora_no_reportable_row(con) -> None:
    """A binned (CTP) config whose loader returns a different corpus than the manifest writes nothing."""
    from scripts.embedding_research import common

    manifest = _manifest(["a", "b", "c"])

    def load(_bb, _strategy, _con, _extra):
        # ctp loader returns a song set that differs from the manifest ("d" instead of "c").
        payload = {
            "pairs": [
                {
                    "rep_a": "mean",
                    "rep_b": "mean",
                    "norm_a_all": [],
                    "norm_b_all": [],
                    "bin_counts": [],
                }
            ]
        }
        return payload, ["a", "b", "d"], ["x"] * 3, ["y"] * 3, ["z"] * 3

    cfg = {
        "strategy_names": ["ctp_emb512_0.50"],
        "load_vecs_fn": load,
        "db_write_fn": common.analyze.db.write_analyze_metrics,
        "strategy_key_fn": lambda _bb, _s, _e: "ctp:effnet:emb512:0.50:mean:mean:target_weighted",
        "strategy_type": "ctp",
        "extra_cfg": {"rep_types": ["mean"], "matching_corpus": {"effnet": manifest}},
    }
    common.analyze.analyze(con, cfg, backbones=["effnet"], force=True, k=10)

    assert any("song-ID set mismatch" in r for r in cfg["extra_cfg"]["skip_reasons"])
    assert con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 0
