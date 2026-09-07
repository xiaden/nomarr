"""Mandatory observed global-medoid baseline (execution-reporting Plan A P2) — spec-first.

These fixtures pin the P2 make-mandatory contract:

1. There is NO ``emit_medoid_baseline`` gate/flag: the REAL ``run.py::_run_analyze`` emits
   exactly one observed ``global_pool:{backbone}:medoid`` baseline per successfully analyzed
   backbone, unconditionally.
2. Fail-closed: a requested backbone whose resolved evaluation corpus is sub-2 ``eligible``
   (fewer than two searchable songs) REFUSES the analyze scope with
   ``common.catalog_analysis.AnalyzeRefusalError`` — never a silent baseline-less success and
   never a fabricated vector.
3. Every participating segmented class scope AND the recorded baseline scope carry the ONE
   resolved evaluation-corpus identity (``evaluation_corpus_hash``/``count``/``comparable`` +
    excluded-song ``missing_*`` evidence) on their ``analyze_scope_v2`` provenance line, and
   all such lines agree on that single identity (the corpus threaded everywhere).

Research-only: no audio/model/ONNX/CUDA, no real corpus.  Kept spec-first against the
concrete gate each test names.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.embedding_research.common.catalog_analysis import AnalyzeRefusalError
from scripts.embedding_research.db import analyze_scope as scope

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_RUN = "run-p2-mandatory-medoid"


def _cfg(threshold: float):
    from scripts.embedding_research import catalog as catalog_mod

    return catalog_mod.SegConfigInput(
        backbone=_BACKBONE,
        bin_mode="temporal_global",
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _unit_axis(i: int) -> np.ndarray:
    v = np.zeros(4, dtype=np.float32)
    v[i] = 1.0
    return v


def _stream(axis: int, dist: float) -> np.ndarray:
    """Six unit rows (three on a basis axis, three at Euclidean distance ``dist``)."""
    u = _unit_axis(axis)
    theta = math.acos(1.0 - dist * dist / 2.0)
    other = _unit_axis((axis + 1) % 4)
    p = (u * math.cos(theta) + other * math.sin(theta)).astype(np.float32)
    return np.stack([u, u, u, p, p, p])


def _streams(song_ids):
    return {(song, _BACKBONE): _stream(axis % 4, 0.5) for axis, song in enumerate(sorted(song_ids))}


def _register_songs(con, song_ids):
    for i, song in enumerate(sorted(song_ids)):
        con.execute(
            "INSERT INTO songs (song_id, path, artist) VALUES (?, ?, ?)",
            (song, f"/audio/{song}.mp3", ["Alice", "Bob"][i % 2]),
        )


def _analyze_run(con, out):
    from scripts.embedding_research import run as run_mod

    run_mod._run_analyze(con, {"output_root": str(out), "backbones": [_BACKBONE], "k": 10}, run_id=_RUN)


def _scope_lines(con, run_id):
    """Every parsed analyze-scope line (the single ``analyze_scope_v2`` schema) for *run_id*."""
    parsed = []
    for (blob,) in con.execute(
        "SELECT output_artifact_hashes FROM run_provenance WHERE run_id=? AND phase='analyze'",
        (run_id,),
    ).fetchall():
        if not blob:
            continue
        for line in blob.splitlines():
            p = scope.parse_analyze_scope(line.strip())
            if p is not None:
                parsed.append(p)
    return parsed


def test_sub2_eligible_corpus_refuses_analyze(compact_catalog_factory, con, tmp_path):
    """A sub-2 eligible corpus makes the analyze scope REFUSE (AnalyzeRefusalError), never succeed."""
    from scripts.embedding_research import run as run_mod

    out = tmp_path / "sub2"
    _register_songs(con, ("s1",))
    harness = compact_catalog_factory(
        con, out, streams=_streams(("s1",)), configs=[_cfg(0.9)], song_ids=["s1"], run_id=_RUN
    )
    try:
        harness.handle.close()
        with pytest.raises(AnalyzeRefusalError):
            run_mod._run_analyze(con, {"output_root": str(out), "backbones": [_BACKBONE], "k": 10}, run_id=_RUN)
        # Fail-closed: no analyze rows, no 'complete' analyze provenance, nothing fabricated.
        n_rows = con.execute("SELECT count(*) FROM analyze_metrics WHERE run_id=?", (_RUN,)).fetchone()[0]
        assert n_rows == 0
        n_complete = con.execute(
            "SELECT count(*) FROM run_provenance WHERE run_id=? AND phase='analyze' AND status='complete'",
            (_RUN,),
        ).fetchone()[0]
        assert n_complete == 0
    finally:
        harness.close()


def test_segmented_and_baseline_scope_lines_carry_one_corpus_identity(compact_catalog_factory, con, tmp_path):
    """Every segmented class scope AND the recorded baseline scope carry the SAME resolved corpus identity."""
    from scripts.embedding_research.catalog_identity import resolve_evaluation_corpus

    songs = ("s1", "s2", "s3", "s4")
    out = tmp_path / "scope-id"
    _register_songs(con, songs)
    harness = compact_catalog_factory(
        con, out, streams=_streams(songs), configs=[_cfg(0.9)], song_ids=list(songs), run_id=_RUN
    )
    try:
        # Resolve the ONE identity at the analyze boundary (mirrors run.py) for the expected hash.
        identity = resolve_evaluation_corpus(harness.con, harness.stream_store, list(songs), backbone=_BACKBONE)
        assert identity.eligible and identity.comparable and identity.count == len(songs)
        harness.handle.close()
        _analyze_run(con, out)

        lines = _scope_lines(con, _RUN)
        # A single-class fixture writes one 'catalog' class scope + the mandatory 'global_pool' scope.
        types = {ln["strategy_key"].split(":")[0] for ln in lines}
        assert "catalog" in types and "global_pool" in types
        # Every corpus-bearing scope line names the SAME single identity (threaded everywhere).
        corpus_lines = [ln for ln in lines if "evaluation_corpus_hash" in ln]
        assert corpus_lines, "every participating scope must carry the evaluation-corpus identity"
        hashes = {ln["evaluation_corpus_hash"] for ln in corpus_lines}
        assert hashes == {identity.corpus_hash}
        for ln in corpus_lines:
            assert ln["evaluation_corpus_count"] == len(songs)
            assert ln["evaluation_corpus_comparable"] is True
            assert ln["evaluation_corpus_missing_count"] == 0
    finally:
        harness.close()


def test_mandatory_baseline_emitted_without_any_emit_gate(compact_catalog_factory, con, tmp_path):
    """_run_analyze emits exactly one global_pool baseline per backbone with NO emit key in the cfg."""
    from scripts.embedding_research.baseline import MEDOID_STRATEGY_TYPE, medoid_strategy_key_for

    songs = ("s1", "s2", "s3", "s4")
    out = tmp_path / "no-gate"
    _register_songs(con, songs)
    harness = compact_catalog_factory(
        con, out, streams=_streams(songs), configs=[_cfg(0.9)], song_ids=list(songs), run_id=_RUN
    )
    try:
        harness.handle.close()
        _analyze_run(con, out)
        keys = {
            r[0]
            for r in con.execute(
                "SELECT DISTINCT strategy_key FROM analyze_metrics WHERE run_id=? AND strategy_type=?",
                (_RUN, MEDOID_STRATEGY_TYPE),
            ).fetchall()
        }
        assert keys == {medoid_strategy_key_for(_BACKBONE)}, "exactly ONE global_pool baseline per backbone"
    finally:
        harness.close()


def test_class_scopes_record_real_semantic_hash_separate_from_disposable(compact_catalog_factory, con, tmp_path):
    """Class scope lines carry the REAL semantic search_representation_hash, distinct keyset/content.

    The persisted analyze_scope_v2 class line must source its ``search_representation_hash`` from
    ``catalog_identity`` (the analyzed class's real value) — never the disposable strategy-key
    keyset hash masquerading as semantic identity (execution-reporting Plan B P1-S1/P1-S3).  The
    disposable per-run ``view_keyset_hash`` (== the strategy-key trailing component) and
    ``view_content_hash`` are separate fields, and neither equals the semantic hash.
    """
    from scripts.embedding_research.catalog_identity import collapse_search_representations

    songs = ("s1", "s2", "s3", "s4")
    out = tmp_path / "v2-id"
    _register_songs(con, songs)
    harness = compact_catalog_factory(
        con, out, streams=_streams(songs), configs=[_cfg(0.9)], song_ids=list(songs), run_id=_RUN
    )
    try:
        # Expected real semantic identity of the analyzed class (computed BEFORE the handle closes —
        # _analyze_run opens its own snapshot handle).
        class_hashes = {c.search_representation_hash for c in collapse_search_representations(harness.con)}
        assert class_hashes, "single-config fixture must collapse to >= 1 search-representation class"
        harness.handle.close()
        _analyze_run(con, out)

        class_scopes = [ln for ln in _scope_lines(con, _RUN) if ln["strategy_key"].startswith("catalog:")]
        assert class_scopes, "real _run_analyze must record >= 1 catalog class scope line"
        for ln in class_scopes:
            semantic = ln.get("search_representation_hash")
            assert semantic, "class scope must carry a non-empty semantic search representation hash"
            assert semantic in class_hashes, "semantic hash must be the REAL catalog_identity value"
            # Durable catalog anchor retained on the class line.
            assert ln.get("catalog_id"), "class scope must retain the catalog_id"
            assert ln.get("catalog_fingerprint"), "class scope must retain the catalog_fingerprint"
            # Semantic vs disposable separation (never a keyset hash masquerading as semantic identity).
            keyset = ln["strategy_key"].split(":")[-1]
            assert ln.get("view_keyset_hash") == keyset, "view_keyset_hash == strategy-key keyset component"
            assert semantic != ln["view_keyset_hash"]
            assert ln["view_keyset_hash"] != ln.get("view_content_hash")
            # Ordered class identity: canonical is the lowest member; per-member detail present.
            assert ln.get("canonical_config_id") is not None
            members = ln.get("members") or []
            assert members, "class scope must carry ordered per-member records"
            assert [m["config_id"] for m in members] == sorted(m["config_id"] for m in members)
            for m in members:
                assert m["exact_segmentation_hash"], "each member must carry its exact segmentation hash"
                assert m["threshold_configured"] is not None and m["threshold_effective"] is not None
    finally:
        harness.close()


def test_baseline_scope_carries_catalog_anchor(compact_catalog_factory, con, tmp_path):
    """The recorded baseline analyze_scope_v2 line retains the durable catalog id + fingerprint.

    The mandatory global-pool baseline scope is NON-class (empty config_ids / view identity) but
    still carries the run's compact catalog anchor so every output row — class or baseline — is
    durably tied to the same catalog it was computed over.
    """
    songs = ("s1", "s2", "s3", "s4")
    out = tmp_path / "v2-baseline"
    _register_songs(con, songs)
    harness = compact_catalog_factory(
        con, out, streams=_streams(songs), configs=[_cfg(0.9)], song_ids=list(songs), run_id=_RUN
    )
    try:
        harness.handle.close()
        _analyze_run(con, out)
        base_scopes = [ln for ln in _scope_lines(con, _RUN) if ln["strategy_key"].startswith("global_pool:")]
        assert base_scopes, "real _run_analyze must record the mandatory baseline scope line"
        for ln in base_scopes:
            assert ln.get("catalog_id"), "baseline scope must retain the catalog_id"
            assert ln.get("catalog_fingerprint"), "baseline scope must retain the catalog_fingerprint"
            # Non-class: no config/canonical/alias/member identity, no view content.
            assert ln.get("config_ids") in ([], None)
            assert ln.get("view_content_hash") in ("", None)
    finally:
        harness.close()
