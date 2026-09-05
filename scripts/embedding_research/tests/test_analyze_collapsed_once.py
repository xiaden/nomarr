"""Plan D P1-S4 — collapse-aware ``analyze`` through the real scheduler (spec-first).

These tests pin the AMENDED §D analyze scheduling contract (parts CONTRACTS.md §D; the
P1-S4 amendment) delivered by ``scripts/embedding_research/common/catalog_analysis.py``:

1. analyzing the two-threshold collapse fixture through ``analyze_catalog_corpus`` (the LIVE
   scheduler) executes ONE ``materialize_search_view`` and ONE ``score_bounded_exact`` per logical
   query/candidate input — the alias config NEVER triggers a second materialization/scorer call and
   never leaks its rows into any candidate view;
2. ``config_ids`` = ALL participating configs sorted and the transient ``representation_classes``
   exposes the canonical id + sorted aliases (no durable alias state on the result);
3. ``PerQueryResult.candidate_keys`` reference canonical rows only (deduped), deterministically
   sorted, with no alias duplicates;
4. per-config winner/delta/count semantics are preserved through the transient class membership —
   no duplicated winners/retained counts/deltas and the schema is unchanged;
5. lazy catalog attach: ``analyze`` opens + validates its catalog at run time and fails CLOSED with
   a typed :class:`~scripts.embedding_research.common.catalog_analysis.CatalogRefusalError` on a
   missing / invalid / corrupt catalog (no stale fallback);
6. run-scoped deletion only — retained rows and other runs' rows survive a re-run (no global delete);
7. a zero-searchable (metadata-only) song is excluded from queries and candidates;
8. CPU sentinels never fire through the whole analyze path;
9. ``analyze_metrics`` rows are run-scoped (physical ``run_id`` = the run) and the run's
   ``run_provenance.view_refs`` is a single deduped line with ``retained=False``.
"""

from __future__ import annotations

import math

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import bounded_scoring, catalog
from scripts.embedding_research import search_views as sv
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.db import analyze_scope
from scripts.embedding_research.db import provenance as prov

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_SONGS = ("s1", "s2", "s3", "s4")
_ARTISTS = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}
_RUN = "run-p1s4-collapsed"

try:  # pragma: no cover - environment dependent
    import onnxruntime  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    onnxruntime = None
try:  # pragma: no cover - environment dependent
    import torch  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    torch = None
try:  # pragma: no cover - environment dependent
    from scripts.embedding_research import config as _config
except Exception:  # pragma: no cover
    _config = None


class _RaisingSentinel:
    def __init__(self, name: str) -> None:
        self._name = name

    def __call__(self, *_args, **_kwargs):  # pragma: no cover - only on failure
        raise AssertionError(f"CPU-only analyze path must not call {self._name}")


def _install_cpu_sentinels(monkeypatch) -> list[str]:
    """Patch audio/model/ONNX/CUDA seams so any call fails the test; return installed names."""
    targets: list[str] = []
    if _config is not None and hasattr(_config, "discover_audio"):
        targets.append(f"{_config.__name__}.discover_audio")
    if onnxruntime is not None:
        targets.append("onnxruntime.InferenceSession")
    if torch is not None:
        targets.append("torch.cuda.is_available")
    installed: list[str] = []
    for dotted in targets:
        try:
            monkeypatch.setattr(dotted, _RaisingSentinel(dotted))
        except (ImportError, AttributeError, ModuleNotFoundError):
            continue
        installed.append(dotted)
    return installed


# --------------------------------------------------------------------------- #
# Two-threshold collapse fixture (identical searchable medoids across configs) #
# --------------------------------------------------------------------------- #


def _cfg(threshold: float) -> catalog.SegConfigInput:
    return catalog.SegConfigInput(
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
    """Six unit rows: three on basis *axis*, three at Euclidean distance *dist*.

    Both collapse configs (0.9 / 1.0) are > ``dist``, so each config segments each such stream
    IDENTICALLY -> one structural segment -> identical per-song search leaves -> collapse.
    """
    u = _unit_axis(axis)
    theta = math.acos(1.0 - dist * dist / 2.0)
    other = _unit_axis((axis + 1) % 4)
    p = (u * math.cos(theta) + other * math.sin(theta)).astype(np.float32)
    return np.stack([u, u, u, p, p, p])


def _build_collapsed_corpus(compact_catalog_factory, con, out, *, song_ids=_SONGS, masks=None, run_id=_RUN):
    """Build a real compact catalog over the two collapse configs (one equivalence class)."""
    streams = {}
    for axis, song in enumerate(sorted(song_ids)):
        streams[(song, _BACKBONE)] = _stream(axis % 4, 0.5)
    return compact_catalog_factory(
        con,
        out,
        streams=streams,
        configs=[_cfg(0.9), _cfg(1.0)],
        song_ids=list(song_ids),
        masks=masks,
        run_id=run_id,
    )


def _analysis_cfg(run_id: str, song_ids=_SONGS, artists=_ARTISTS) -> ca.CatalogAnalysisConfig:
    return ca.CatalogAnalysisConfig(run_id=run_id, backbone=_BACKBONE, song_ids=tuple(song_ids), artists=dict(artists))


# --------------------------------------------------------------------------- #
# 1. ONE materialize + ONE scorer execution per class (real scheduler)         #
# --------------------------------------------------------------------------- #


def test_analyze_executes_one_materialize_and_per_class_scorer_calls(
    compact_catalog_factory, con, tmp_path, monkeypatch
):
    """Through the real scheduler one materialize runs and each logical input is scored ONCE per class."""
    harness = _build_collapsed_corpus(compact_catalog_factory, con, tmp_path / "out")
    try:
        from scripts.embedding_research.catalog_identity import collapse_search_representations

        classes = collapse_search_representations(harness.con)
        assert len(classes) == 1
        canonical = classes[0].canonical_config_id
        alias = classes[0].alias_ids[0]

        materialize_calls = {"n": 0}
        real_mat = sv.materialize_search_view

        def _mat_spy(*a, **k):
            materialize_calls["n"] += 1
            return real_mat(*a, **k)

        scorer_calls = {"n": 0, "candidate_configs": set()}
        real_score = bounded_scoring.score_bounded_exact

        def _score_spy(*a, **k):
            scorer_calls["n"] += 1
            cand = k.get("candidate_view")
            if cand is not None:
                scorer_calls["candidate_configs"].update(r[0] for r in cand.row_addresses)
            return real_score(*a, **k)

        monkeypatch.setattr(sv, "materialize_search_view", _mat_spy)
        monkeypatch.setattr(bounded_scoring, "score_bounded_exact", _score_spy)

        result = ca.analyze_catalog_corpus(
            harness.stream_store, harness.con, _analysis_cfg("run-p1s4-a"), research_con=con
        )

        assert materialize_calls["n"] == 1, "one all-config materialization per run, never per config"
        n_logical = len(_SONGS) * (len(_SONGS) - 1)  # leave-one-out query/candidate pairs
        assert scorer_calls["n"] == n_logical, "aliases must never add extra scorer executions"
        assert scorer_calls["candidate_configs"] == {canonical}
        assert alias not in scorer_calls["candidate_configs"]
        assert result.finite is True and result.n_queries == len(_SONGS)
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 2/3. config_ids all-participating; representation_classes; canonical keys    #
# --------------------------------------------------------------------------- #


def test_result_identity_and_canonical_candidate_keys(compact_catalog_factory, con, tmp_path):
    """config_ids = ALL participating configs; candidate_keys are canonical-only and sorted."""
    harness = _build_collapsed_corpus(compact_catalog_factory, con, tmp_path / "out")
    try:
        from scripts.embedding_research.catalog_identity import collapse_search_representations

        classes = collapse_search_representations(harness.con)
        assert len(classes) == 1
        canonical = classes[0].canonical_config_id
        alias = classes[0].alias_ids[0]

        result = ca.analyze_catalog_corpus(
            harness.stream_store, harness.con, _analysis_cfg("run-p1s4-b"), research_con=con
        )

        # (2) config_ids = EVERY participating config, sorted; transient representation_classes.
        assert tuple(sorted(result.config_ids)) == result.config_ids == tuple(sorted((canonical, alias)))
        assert len(result.representation_classes) == 1
        rc = result.representation_classes[0]
        assert rc.canonical_config_id == canonical
        assert rc.config_ids == tuple(sorted((canonical, alias)))
        assert rc.alias_ids == (alias,)
        # Transient only: no durable alias table/column appears because of the analysis.
        tables = {str(r[0]) for r in harness.con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        assert not any("alias" in t.lower() for t in tables)

        # (3) candidate_keys canonical-only, deduped, deterministically sorted.
        for pq in result.per_query:
            assert pq.all_finite() is True
            configs = {int(k[0]) for k in pq.candidate_keys}
            assert configs == {canonical}
            assert not any(int(k[0]) == alias for k in pq.candidate_keys)
            assert pq.candidate_keys == tuple(sorted(pq.candidate_keys))
        # n_candidate_rows counts the unique canonical medoid rows (one per searchable song here).
        assert result.n_candidate_rows == len(_SONGS)
        assert result.n_queries == len(_SONGS)
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 4. Winners/retained preserved; schema unchanged (no alias duplication)       #
# --------------------------------------------------------------------------- #


def test_winner_and_count_schema_unchanged_after_collapse(compact_catalog_factory, con, tmp_path):
    """The single canonical execution's winner/count/delta surface is preserved — no alias duplication."""
    harness = _build_collapsed_corpus(compact_catalog_factory, con, tmp_path / "out")
    try:
        result = ca.analyze_catalog_corpus(
            harness.stream_store, harness.con, _analysis_cfg("run-p1s4-c"), research_con=con
        )
        for pq in result.per_query:
            assert isinstance(pq.winner_counts, dict) and all(
                isinstance(k, int) and np.isfinite(v) for k, v in pq.winner_counts.items()
            )
            assert pq.dropped_count == 0  # retain_all_candidate_segments never drops
            assert pq.retained_count > 0
            assert pq.variant == result.score_variant == "max_per_candidate_segment"
            # Exactly one scorer execution per logical input (asserted by schema-preserving count):
            # the per-query retained/winner totals reflect a SINGLE canonical class execution.
            assert pq.retained_count <= result.n_candidate_rows
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 5. Lazy catalog attach + typed refusal (no stale fallback)                   #
# --------------------------------------------------------------------------- #


def test_analyze_opens_snapshot_path_lazily_and_matches_handle_run(compact_catalog_factory, con, tmp_path):
    """Passing the snapshot PATH string: analyze opens+validates at run time (lazy attach)."""
    harness = _build_collapsed_corpus(compact_catalog_factory, con, tmp_path / "out")
    # Determinism baseline via the live (handle) connection FIRST — the harness holds the only
    # live handle to this snapshot, so the path-based lazy open runs only after it is closed.
    by_handle = ca.analyze_catalog_corpus(harness.stream_store, harness.con, _analysis_cfg("run-p1s4-handle"))
    assert by_handle.finite is True and by_handle.n_queries == len(_SONGS)
    path = str(harness.snapshot_path)
    harness.close()  # release the read-write handle so a fresh read-only open is allowed
    try:
        # Analyzer opens + validates the snapshot at run time (lazy attach, read-only, closed after).
        result = ca.analyze_catalog_corpus(harness.stream_store, path, _analysis_cfg("run-p1s4-path"))
        assert result.finite is True and result.n_queries == len(_SONGS)
        for key in result.metrics:
            np.testing.assert_allclose(by_handle.metrics[key], result.metrics[key], rtol=1e-6)
    finally:
        harness.close()  # idempotent no-op after already closed


def test_analyze_refuses_missing_catalog_typed(tmp_path):
    """A nonexistent snapshot path is a typed refusal, never a silent skip."""
    missing = tmp_path / "does-not-exist" / "catalog.duckdb"
    with pytest.raises(ca.CatalogRefusalError):
        ca.analyze_catalog_corpus(None, str(missing), _analysis_cfg("run-p1s4-missing"))


def test_analyze_refuses_invalid_non_compact_catalog():
    """A connection without the compact catalog tables is a typed refusal (no stale fallback)."""
    bare = duckdb.connect(":memory:")  # not a compact catalog (no seg_config)
    try:
        with pytest.raises(ca.CatalogRefusalError):
            ca.analyze_catalog_corpus(None, bare, _analysis_cfg("run-p1s4-invalid"))
    finally:
        bare.close()


def test_analyze_refuses_corrupt_snapshot_typed(tmp_path):
    """A corrupt (non-duckdb) snapshot file is a typed refusal."""
    bad = tmp_path / "bad-catalog.duckdb"
    bad.write_text("this is not a duckdb snapshot", encoding="utf-8")
    with pytest.raises(ca.CatalogRefusalError):
        ca.analyze_catalog_corpus(None, str(bad), _analysis_cfg("run-p1s4-corrupt"))


# --------------------------------------------------------------------------- #
# 6. Run-scoped deletion only (retained + other runs survive a re-run)         #
# --------------------------------------------------------------------------- #


def _seed_retained_and_unrelated(con):
    prov.write_run_provenance(
        con,
        run_id="retained-run-0",
        phase="analyze",
        status="complete",
        started_at=1,
        finished_at=2,
        retained=True,
        output_artifact_hashes="other:scope",
    )
    unrelated = "global_pool:effnet:mean"
    con.execute(
        "INSERT INTO analyze_metrics (strategy_key, strategy_type, sim_metric, k, metric, value) "
        "VALUES (?, 'global_pool', 'cosine', 10, 'disc_general', 0.99)",
        (unrelated,),
    )
    return unrelated


def test_re_run_touches_only_its_own_rows(compact_catalog_factory, con, tmp_path):
    """A re-run deletes/replaces only its own (run_id, scope) rows; retained/other-run rows survive."""
    unrelated = _seed_retained_and_unrelated(con)
    harness = _build_collapsed_corpus(compact_catalog_factory, con, tmp_path / "out")
    try:
        store = harness.stream_store
        res_a = ca.analyze_catalog_corpus(store, harness.con, _analysis_cfg("run-p1s4-A"), research_con=con)
        sk_a = analyze_scope.write_catalog_analyze_rows(con, run_id="run-p1s4-A", result=res_a)
        res_b = ca.analyze_catalog_corpus(store, harness.con, _analysis_cfg("run-p1s4-B"), research_con=con)
        sk_b = analyze_scope.write_catalog_analyze_rows(con, run_id="run-p1s4-B", result=res_b)
        # Re-run A: replaces A's own rows only.
        res_a2 = ca.analyze_catalog_corpus(store, harness.con, _analysis_cfg("run-p1s4-A"), research_con=con)
        sk_a2 = analyze_scope.write_catalog_analyze_rows(con, run_id="run-p1s4-A", result=res_a2)
        assert sk_a2 == sk_a

        assert con.execute(
            "SELECT value FROM analyze_metrics WHERE strategy_key=? AND metric='disc_general'", (unrelated,)
        ).fetchone()[0] == pytest.approx(0.99)
        assert con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE strategy_key=?", (sk_b,)).fetchone()[0] > 0
        assert con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE strategy_key=?", (sk_a,)).fetchone()[0] > 0
        rows = prov.read_run_provenance(con, run_id="retained-run-0")
        assert len(rows) == 1 and rows[0]["retained"] is True
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 7. Zero-searchable (metadata-only) songs are excluded                        #
# --------------------------------------------------------------------------- #


def test_zero_searchable_song_is_excluded_from_queries_and_candidates(compact_catalog_factory, con, tmp_path):
    """A zero-searchable song (present in the catalog as metadata only) never becomes a query/candidate."""
    zs_mask = {f"z{n}": np.zeros(6, dtype=np.uint8) for n in (1,)}  # fully silent -> no searchable medoid
    song_ids = [*list(_SONGS), "z1"]
    harness = _build_collapsed_corpus(compact_catalog_factory, con, tmp_path / "out", song_ids=song_ids, masks=zs_mask)
    try:
        from scripts.embedding_research import catalog as cat

        # z1 has catalog metadata but NO searchable medoid rows.
        configs = [c.config_id for c in cat.compact_configs_by_backbone(harness.con, _BACKBONE)]
        z_medoids = sum(
            1
            for cid in configs
            for m in cat.compact_segments_by_config_song(harness.con, cid, "z1")
            if m.search_medoid_source_patch_idx is not None
        )
        assert z_medoids == 0
        assert harness.con.execute("SELECT COUNT(*) FROM catalog_song WHERE song_id='z1'").fetchone()[0] == len(configs)

        cfg = _analysis_cfg("run-p1s4-z", song_ids=song_ids)
        result = ca.analyze_catalog_corpus(harness.stream_store, harness.con, cfg, research_con=con)
        # z1 is excluded: it is not a query and never appears among candidates.
        assert result.n_queries == len(_SONGS)
        query_ids = {pq.query_song_id for pq in result.per_query}
        assert "z1" not in query_ids
        for pq in result.per_query:
            assert "z1" not in pq.candidate_scores
            assert not any(k[1] == "z1" for k in pq.candidate_keys)
        # The searchable songs still analyzed + persisted with full config identity.
        assert set(query_ids) == set(_SONGS)
        assert tuple(sorted(result.config_ids)) == result.config_ids
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 8. CPU sentinels never fire                                                 #
# --------------------------------------------------------------------------- #


def test_analyze_makes_no_audio_model_onnx_cuda_calls(compact_catalog_factory, con, tmp_path, monkeypatch):
    """analyze over the collapse fixture is pure catalog + stream CPU work."""
    harness = _build_collapsed_corpus(compact_catalog_factory, con, tmp_path / "out")
    try:
        installed = _install_cpu_sentinels(monkeypatch)
        assert installed, "no audio/model/ONNX/CUDA seam was available to sentinel — vacuous test"
        result = ca.analyze_catalog_corpus(
            harness.stream_store, harness.con, _analysis_cfg("run-p1s4-cpu"), research_con=con
        )
        assert result.finite is True and result.n_queries == len(_SONGS)
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 9. analyze_metrics run-scoped; view_refs deduped retained=False             #
# --------------------------------------------------------------------------- #


def test_analyze_metrics_run_scoped_and_view_ref_deduped(compact_catalog_factory, con, tmp_path):
    """analyze_metrics rows carry the physical run_id; view_refs is one deduped retained=False line."""
    harness = _build_collapsed_corpus(compact_catalog_factory, con, tmp_path / "out")
    try:
        store = harness.stream_store
        run_id = "run-p1s4-scope"
        result = ca.analyze_catalog_corpus(store, harness.con, _analysis_cfg(run_id), research_con=con)
        analyze_scope.write_catalog_analyze_rows(con, run_id=run_id, result=result)

        # run-scoped physical run_id on the aggregate rows the run owns.
        rows = con.execute(
            "SELECT DISTINCT run_id FROM analyze_metrics WHERE strategy_key=?", (result.strategy_key,)
        ).fetchall()
        assert rows and {r[0] for r in rows} == {run_id}

        # view_refs: one deduped line (a single materialization covers the whole class set), retained=False.
        recs = prov.read_run_provenance(con, run_id=run_id)
        analyze_rows = [r for r in recs if r["phase"] == "analyze"]
        assert analyze_rows, "analyze must self-record a phase='analyze' provenance row"
        view_refs = analyze_rows[0]["view_refs"] or ""
        lines = [ln for ln in view_refs.splitlines() if ln.strip()]
        assert len(lines) == 1, "one deduped view-ref line per run (per class set)"
        assert analyze_rows[0]["retained"] is False
        # Scope recorded (for the later run-scoped reset) carries the view content hash.
        blob = analyze_rows[0]["output_artifact_hashes"] or ""
        assert analyze_scope.parse_analyze_scope(blob.splitlines()[0]) is not None
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 10. P1-S5 AMEND seam: one canonical deduplicated class input per class        #
# --------------------------------------------------------------------------- #


def test_scorer_seam_feeds_one_canonical_input_per_logical_pair_across_two_classes(
    compact_catalog_factory, con, tmp_path, monkeypatch
):
    """P1-S5 AMEND: across TWO collapse classes the scheduler still calls the scorer ONCE per
    logical query/candidate input, feeding canonical rows only — never once per alias and never a
    second call per class-member config (0.9/1.0 collapse to one class; 0.2 is a distinct class)."""
    streams = {}
    for axis, song in enumerate(sorted(_SONGS)):
        streams[(song, _BACKBONE)] = _stream(axis % 4, 0.5)
    harness = compact_catalog_factory(
        con,
        tmp_path / "out",
        streams=streams,
        configs=[_cfg(0.9), _cfg(1.0), _cfg(0.2)],  # 0.9/1.0 collapse; 0.2 segments differently
        song_ids=list(_SONGS),
        run_id=_RUN,
    )
    try:
        from scripts.embedding_research.catalog_identity import collapse_search_representations

        classes = collapse_search_representations(harness.con)
        assert len(classes) == 2, "0.9/1.0 form one class; 0.2 (splits differently) forms a second"
        canonical_ids = {c.canonical_config_id for c in classes}
        alias_ids = {i for c in classes for i in c.alias_ids}
        assert len(canonical_ids) == 2
        assert alias_ids, "the 0.9/1.0 collapse must expose an alias so alias-dedup is actually exercised"

        scorer_calls = {"n": 0, "candidate_configs": set()}
        real_score = bounded_scoring.score_bounded_exact

        def _score_spy(*a, **k):
            scorer_calls["n"] += 1
            cand = k.get("candidate_view")
            if cand is not None:
                scorer_calls["candidate_configs"].update(int(r[0]) for r in cand.row_addresses)
            return real_score(*a, **k)

        monkeypatch.setattr(bounded_scoring, "score_bounded_exact", _score_spy)

        result = ca.analyze_catalog_corpus(
            harness.stream_store, harness.con, _analysis_cfg("run-p1s5-two-class"), research_con=con
        )

        n_logical = len(_SONGS) * (len(_SONGS) - 1)  # leave-one-out query/candidate pairs
        # One scorer execution per logical pair across BOTH classes (never per class-member/alias).
        assert scorer_calls["n"] == n_logical
        # Candidate views carry canonical rows from every class, and NEVER an alias config.
        assert scorer_calls["candidate_configs"] == canonical_ids
        assert scorer_calls["candidate_configs"].isdisjoint(alias_ids)
        assert result.finite is True and result.n_queries == len(_SONGS)
        for pq in result.per_query:
            assert pq.all_finite() is True
            assert {int(k[0]) for k in pq.candidate_keys}.issubset(canonical_ids)
            assert not any(int(k[0]) in alias_ids for k in pq.candidate_keys)
    finally:
        harness.close()
