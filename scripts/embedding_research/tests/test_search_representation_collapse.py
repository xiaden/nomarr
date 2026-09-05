"""Plan D P1-S3 — spec-first tests for search-representation equivalence collapse.

These tests pin the §D ``SearchRepresentationClass`` / ``collapse_search_representations``
contract (parts CONTRACTS.md §D; DD-frozen-observation-corrective-pass requirements 9, L246-266)
delivered by ``scripts/embedding_research/catalog_identity.py``:

* ``search_representation_hash`` aggregates a config's CURRENT per-song ``search_leaf`` values
  (encoder_version + scoring-input semantics + sorted search leaves) and EXCLUDES the canonical
  config fields — so two distinct direct thresholds that segment the SAME frozen streams into
  identical searchable medoid sets have EQUAL search hashes and collapse.
* ``exact_segmentation_hash`` ALSO includes the canonical config fields (``threshold_effective``
  etc.), so the two collapsed configs carry DISTINCT exact hashes and remain structurally
  distinguishable in report / structural-change surfaces.
* ``collapse_search_representations(catalog)`` recomputes the equivalence classes from CURRENT
  stored ``catalog_song`` search leaves EVERY call — a pure read.  There is deliberately NO
  durable alias graph / alias column / alias file.  The class canonical config is the lowest
  member ``config_id``; members/aliases are sorted ascending.

The synthetic collapse fixture is a TWO-threshold config pair (direct-L2 ``0.9`` vs ``1.0``) on
frozen streams that segment IDENTICALLY under both thresholds: the actual scoring inputs
(ordered per-song searchable medoid source indices + normalized weights) are byte-identical while
``threshold_effective`` (hence ``exact_segmentation_hash``) differs.  This proves the §D
property that structural differences do NOT prevent collapse when the actual scoring inputs match.

Requirement 3 (ONE materialize + ONE scorer execution for a collapsed class) is proven at the
collapse -> materialize -> scorer-call level, since the per-config scorer scheduling belongs to
P1-S4 (``analyze_catalog_corpus``): a single ``score_bounded_exact`` invocation over the class
canonical config's gathered rows produces the class score, and the alias config maps to the SAME
view rows / scoring inputs (asserted by equality) so no second invocation is needed.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.embedding_research import bounded_scoring, catalog
from scripts.embedding_research import search_views as sv
from scripts.embedding_research.catalog_identity import (
    SearchRepresentationClass,
    collapse_search_representations,
    exact_segmentation_hash,
    search_representation_hash,
)
from scripts.embedding_research.catalog_report import build_catalog_report
from scripts.embedding_research.common.catalog_analysis import (
    CatalogAnalysisConfig,
    analyze_catalog_corpus,
)

pytestmark = pytest.mark.unit

_SCHEMA_VERSION = 1
_BACKBONE = "effnet"
_RUN = "run-p1s3"

# Optional CPU seams — sentinels attach only when the underlying symbol is importable.
try:  # pragma: no cover - environment dependent
    import onnxruntime  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    onnxruntime = None
try:  # pragma: no cover - environment dependent
    import torch  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    torch = None
try:  # pragma: no cover - environment dependent
    from nomarr.components.ml.onnx import ml_session_comp  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    ml_session_comp = None
try:  # pragma: no cover - environment dependent
    from scripts.embedding_research import config as _config
except Exception:  # pragma: no cover
    _config = None


class _RaisingSentinel:
    """Raises AssertionError if invoked — a seam call must fail the test."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __call__(self, *_args, **_kwargs):  # pragma: no cover - only on failure
        raise AssertionError(f"CPU-only path must not call {self._name}")


def _install_sentinels(monkeypatch) -> list[str]:
    """Patch audio/model/ONNX/CUDA seams so any call fails the test; return installed names."""
    targets: list[str] = []
    if _config is not None and hasattr(_config, "discover_audio"):
        targets.append(f"{_config.__name__}.discover_audio")
    if onnxruntime is not None:
        targets.append("onnxruntime.InferenceSession")
    if torch is not None:
        targets.append("torch.cuda.is_available")
    if ml_session_comp is not None:
        targets.extend(
            f"{ml_session_comp.__name__}.{attr}"
            for attr in ("create_session", "_run_in_batches")
            if hasattr(ml_session_comp, attr)
        )
    installed: list[str] = []
    for dotted in targets:
        try:
            monkeypatch.setattr(dotted, _RaisingSentinel(dotted))
        except (ImportError, AttributeError, ModuleNotFoundError):
            continue
        installed.append(dotted)
    return installed


# --------------------------------------------------------------------------- #
# Fixture helpers (synthetic numpy frozen streams only)                        #
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
    """Six unit rows: three on basis *axis*, three at Euclidean distance *dist* from it.

    Segments into ONE structural segment for any threshold > ``dist``.  Because the two
    collapse configs (0.9 / 1.0) are both > ``dist``, each config segments each such stream
    IDENTICALLY -> identical per-song search leaves -> equal ``search_representation_hash``.
    """
    u = _unit_axis(axis)
    theta = math.acos(1.0 - dist * dist / 2.0)  # ||u cos + other sin - u|| == dist
    other = _unit_axis((axis + 1) % 4)
    p = (u * math.cos(theta) + other * math.sin(theta)).astype(np.float32)
    return np.stack([u, u, u, p, p, p])


def _threshold_split_mat() -> np.ndarray:
    """Two thresholds (0.9 vs 0.2) that genuinely split differently (control for req 6)."""
    theta = math.acos(0.875)  # distance(+x, rotated) == 0.5
    u0 = _unit_axis(0)
    u1 = np.array([math.cos(theta), math.sin(theta), 0.0, 0.0], dtype=np.float32)
    return np.stack([u0, u0, u0, u1, u1, u1])


def _threshold_to_config(con) -> dict[float, int]:
    """Map each compact effnet config's ``threshold_effective`` to its ``config_id``."""
    return {float(r.threshold_effective): r.config_id for r in catalog.compact_configs_by_backbone(con, _BACKBONE)}


def _catalog_input(harness, config_id: int, songs):
    """song -> ordered (seg_id, medoid_source_idx, weight) rows, purely from compact catalog rows.

    Independent of both collapse and materialize code — the requirement 2 oracle for what a
    config's ACTUAL scoring inputs are.
    """
    out: dict[str, list[tuple[int, int, float]]] = {}
    for song in sorted(songs):
        rows = sorted(
            (int(seg.seg_id), int(seg.search_medoid_source_patch_idx), float(seg.searchable_weight))
            for seg in catalog.compact_segments_by_config_song(harness.con, config_id, song)
            if seg.search_medoid_source_patch_idx is not None  # no searchable mass -> no scoring row
        )
        out[song] = rows
    return out


def _collapse_pair(harness):
    """Return ``(classes, configs_by_threshold, ids)`` for the two-threshold collapse fixture."""
    by_threshold = _threshold_to_config(harness.con)
    ids = sorted(by_threshold.values())
    assert len(ids) == 2
    classes = collapse_search_representations(harness.con)
    return classes, by_threshold, ids


def _build_pair(compact_catalog_factory, con, out, *, thresholds=(0.9, 1.0), song_ids=("s1",)):
    """Build ONE compact catalog snapshot over the two collapse thresholds + frozen streams."""
    streams = {("s1", _BACKBONE): _stream(0, 0.5)}
    if "s2" in song_ids:
        streams[("s2", _BACKBONE)] = _stream(1, 0.4)
    return compact_catalog_factory(
        con,
        out,
        streams=streams,
        configs=[_cfg(t) for t in thresholds],
        song_ids=list(song_ids),
        run_id=_RUN,
    )


# --------------------------------------------------------------------------- #
# 1. One class for the two thresholds; canonical + aliases deterministic       #
# --------------------------------------------------------------------------- #


def test_two_thresholds_collapse_to_one_deterministic_class(compact_catalog_factory, con, tmp_path):
    """0.9 vs 1.0 segment identically -> ONE class, lowest config_id canonical, alias sorted."""
    harness = _build_pair(compact_catalog_factory, con, tmp_path / "out")
    try:
        classes, by_threshold, ids = _collapse_pair(harness)
        assert len(classes) == 1
        cls = classes[0]
        assert isinstance(cls, SearchRepresentationClass)
        # deterministic canonical = lowest member config_id; members sorted ascending.
        assert cls.config_ids == tuple(ids)
        assert cls.canonical_config_id == min(ids)
        assert cls.alias_ids == (max(ids),)
        assert cls.n_configs == 2
        assert len(cls.search_representation_hash) == 64
        # distinct thresholds / structural rows, but identical SEARCH representations.
        c0, c1 = sorted(by_threshold.values())
        assert search_representation_hash(harness.con, c0) == search_representation_hash(harness.con, c1)
        assert exact_segmentation_hash(harness.con, c0) != exact_segmentation_hash(harness.con, c1)
        # recomputation is deterministic (pure read): repeated calls return the same classes.
        again = collapse_search_representations(harness.con)
        assert again == classes
        assert again[0].canonical_config_id == cls.canonical_config_id
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 2. Class members' ACTUAL scoring inputs are identical                        #
# --------------------------------------------------------------------------- #


def test_class_members_have_identical_scoring_inputs(compact_catalog_factory, con, tmp_path):
    """Both collapse members derive identical ordered medoid indices + weights from the catalog."""
    harness = _build_pair(compact_catalog_factory, con, tmp_path / "out", song_ids=("s1", "s2"))
    try:
        classes, by_threshold, _ids = _collapse_pair(harness)
        assert len(classes) == 1
        c0, c1 = sorted(by_threshold.values())
        a = _catalog_input(harness, c0, ["s1", "s2"])
        b = _catalog_input(harness, c1, ["s1", "s2"])
        # The expectations come from the catalog rows, NOT from collapse code.
        assert a and b
        assert a.keys() == b.keys()
        for song in a:
            assert a[song] == b[song], f"scoring inputs differ for song {song!r}: {a[song]} vs {b[song]}"
        # Sanity: the fixture really produced searchable medoid rows on both songs.
        for song in a:
            assert a[song], f"song {song!r} produced no medoid rows under either config"
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 3. ONE materialize + ONE scorer execution per class                          #
# --------------------------------------------------------------------------- #


def _materialize(harness, *, run_id=_RUN, working_memory=2**20, song_ids=("s1", "s2")):
    return sv.materialize_search_view(
        harness.con,
        harness.stream_store,
        song_ids=song_ids,
        backbone=_BACKBONE,
        run_id=run_id,
        working_memory=working_memory,
    )


def _rows_by_song_for_config(record, config_id: int) -> dict[str, list[int]]:
    """Row positions in ``record.row_addresses`` grouped by song, for ONE config."""
    out: dict[str, list[int]] = {}
    for i, row in enumerate(record.row_addresses):
        if int(row[0]) == config_id:
            out.setdefault(row[1], []).append(i)
    return out


def test_one_materialize_and_one_scorer_execution_per_collapsed_class(
    compact_catalog_factory, con, tmp_path, monkeypatch
):
    """The real analysis scheduler executes ONE materialize + ONE scorer call per collapsed class.

    P1-S4 (AMENDED): routed through ``analyze_catalog_corpus`` (the live scheduler, not a manual
    scorer call), the two-config collapse fixture triggers exactly ONE ``materialize_search_view``
    and exactly ONE ``score_bounded_exact`` per logical query/candidate input — the alias config
    NEVER causes a second materialization or a second scorer invocation, and never leaks its rows
    into any candidate view or the result's ``candidate_keys``.
    """
    harness = _build_pair(compact_catalog_factory, con, tmp_path / "out", song_ids=("s1", "s2"))
    try:
        classes, _by_threshold, ids = _collapse_pair(harness)
        assert len(classes) == 1
        cls = classes[0]
        canonical = cls.canonical_config_id
        alias = cls.alias_ids[0]
        cfg = CatalogAnalysisConfig(
            run_id="run-p1s4-sched",
            backbone=_BACKBONE,
            song_ids=("s1", "s2"),
            artists={"s1": "A", "s2": "A"},
            working_memory=2**20,
        )

        materialize_calls = {"n": 0}
        real_materialize = sv.materialize_search_view

        def _mat_spy(*args, **kwargs):
            materialize_calls["n"] += 1
            return real_materialize(*args, **kwargs)

        scorer_calls = {"n": 0, "candidate_configs": set()}
        real_scorer = bounded_scoring.score_bounded_exact

        def _scorer_spy(*args, **kwargs):
            scorer_calls["n"] += 1
            cand = kwargs.get("candidate_view")
            if cand is not None:
                scorer_calls["candidate_configs"].update(r[0] for r in cand.row_addresses)
            return real_scorer(*args, **kwargs)

        monkeypatch.setattr(sv, "materialize_search_view", _mat_spy)
        monkeypatch.setattr(bounded_scoring, "score_bounded_exact", _scorer_spy)

        result = analyze_catalog_corpus(harness.stream_store, harness.con, cfg, research_con=con)

        # ONE materialization for the whole run (never per-config).
        assert materialize_calls["n"] == 1, "a collapsed class must need exactly one materialization"
        # ONE scorer call per logical query/candidate input (2 songs -> 2 inputs); the alias config
        # does NOT double it (would be 4 if aliases were scored separately).
        assert scorer_calls["n"] == 2, "aliases must not trigger extra scorer executions"
        # Every candidate view fed to the scorer carries ONLY canonical rows (no alias leak).
        assert scorer_calls["candidate_configs"] == {canonical}
        assert alias not in scorer_calls["candidate_configs"]

        # config_ids = ALL participating configs (canonical + alias); transient representation_classes.
        assert tuple(result.config_ids) == tuple(sorted(ids))
        assert len(result.representation_classes) == 1
        rc = result.representation_classes[0]
        assert rc.canonical_config_id == canonical
        assert rc.config_ids == tuple(sorted(ids))
        assert rc.alias_ids == (alias,)
        # candidate_keys reference canonical rows only; no alias config appears.
        for pq in result.per_query:
            assert pq.all_finite() is True
            assert {int(k[0]) for k in pq.candidate_keys} == {canonical}
            assert not any(int(k[0]) == alias for k in pq.candidate_keys)
            assert pq.candidate_keys == tuple(sorted(pq.candidate_keys))
        assert result.n_queries == 2
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 4. Structural-change reporting is preserved despite the collapse             #
# --------------------------------------------------------------------------- #


def test_structural_change_reporting_preserved_across_collapse(compact_catalog_factory, con, tmp_path):
    """The two collapsed configs are reported as a transient alias while exact (structural)
    identity stays distinct — no silent collapse in the structural / report surface."""
    harness = _build_pair(compact_catalog_factory, con, tmp_path / "out")
    try:
        classes, by_threshold, ids = _collapse_pair(harness)
        assert len(classes) == 1  # they collapse for scoring...
        canonical = min(ids)
        alias = max(ids)
        c0, c1 = sorted(by_threshold.values())
        # ...but remain structurally distinct via their exact hashes.
        assert exact_segmentation_hash(harness.con, c0) != exact_segmentation_hash(harness.con, c1)

        report = build_catalog_report(harness.con, schema_version=_SCHEMA_VERSION)
        # Alias reporting present (the search-level collapse).
        assert (alias, canonical) in report.alias_entries
        assert report.alias_count == 1
        assert canonical in report.canonical_config_ids
        assert alias not in report.canonical_config_ids
        # Structural identity stays distinct: BOTH configs keep their own structural snapshot and
        # config-content rows (the report never merges them into one structural row).
        assert {int(x["config_id"]) for x in report.config_content} == set(ids)
        assert set(report.config_snapshots) == set(ids)
        assert canonical in report.config_snapshots and alias in report.config_snapshots
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 5. Recomputed from CURRENT stored hashes; no durable alias graph             #
# --------------------------------------------------------------------------- #


def test_collapse_recomputes_from_current_hashes_and_persists_nothing(compact_catalog_factory, con, tmp_path):
    """A fresh collapse after a stored-leaf change recomputes the classes (no stale class), and
    there is no durable alias graph / alias column / alias file anywhere."""
    harness = _build_pair(compact_catalog_factory, con, tmp_path / "out")
    try:
        classes, _by_threshold, ids = _collapse_pair(harness)
        assert len(classes) == 1
        canonical = min(ids)
        alias = max(ids)

        # ---- no durable alias surface exists (schema + files) ----
        cols = {
            str(r[0])
            for r in harness.con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'seg_config'"
            ).fetchall()
        }
        assert "alias_of_config_id" not in cols
        tables = {str(r[0]) for r in harness.con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        assert not any("alias" in t.lower() for t in tables)
        alias_files = [p for p in harness.output_root.rglob("*") if "alias" in p.name.lower()]
        assert alias_files == []

        # ---- a structural change to one config's search leaves is seen by a FRESH collapse ----
        original = harness.con.execute(
            "SELECT search_leaf FROM catalog_song WHERE config_id = ? AND song_id = 's1'", [alias]
        ).fetchone()[0]
        mutated = ("0" if original[0] != "0" else "1") + original[1:]
        harness.con.execute(
            "UPDATE catalog_song SET search_leaf = ? WHERE config_id = ? AND song_id = 's1'",
            [mutated, alias],
        )
        fresh = collapse_search_representations(harness.con)
        assert len(fresh) == 2, "mutated search leaf must separate the configs on a fresh collapse"
        assert {c.canonical_config_id for c in fresh} == set(ids)
        assert all(c.alias_ids == () for c in fresh)

        # Reverting the stored leaf restores the single class -> proof of recompute-from-current
        # (no stale class persisted anywhere between the two collapses).
        harness.con.execute(
            "UPDATE catalog_song SET search_leaf = ? WHERE config_id = ? AND song_id = 's1'",
            [original, alias],
        )
        restored = collapse_search_representations(harness.con)
        assert len(restored) == 1
        assert restored[0].canonical_config_id == canonical
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 6. Distinct-hash configs never collapse (control)                            #
# --------------------------------------------------------------------------- #


def test_distinct_search_representations_do_not_collapse(compact_catalog_factory, con, tmp_path):
    """Two configs with genuinely different searchable medoids (0.9 merges, 0.2 splits) yield
    TWO classes with no alias."""
    harness = compact_catalog_factory(
        con,
        tmp_path / "out",
        streams={("s1", _BACKBONE): _threshold_split_mat()},
        configs=[_cfg(0.9), _cfg(0.2)],
        song_ids=["s1"],
        run_id=_RUN,
    )
    try:
        by_threshold = _threshold_to_config(harness.con)
        assert set(by_threshold) == {0.9, 0.2}
        classes = collapse_search_representations(harness.con)
        assert len(classes) == 2
        for cls in classes:
            assert cls.n_configs == 1
            assert cls.alias_ids == ()
        c09, c02 = by_threshold[0.9], by_threshold[0.2]
        assert search_representation_hash(harness.con, c09) != search_representation_hash(harness.con, c02)
        # report agrees: two real canonical configs, no transient alias.
        report = build_catalog_report(harness.con, schema_version=_SCHEMA_VERSION)
        assert report.alias_entries == ()
        assert {c09, c02} <= set(report.canonical_config_ids)
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 7. CPU-only: collapse + materialize never touch audio/model/ONNX/CUDA        #
# --------------------------------------------------------------------------- #


def test_collapse_and_materialize_make_no_audio_model_onnx_cuda_calls(
    compact_catalog_factory, con, tmp_path, monkeypatch
):
    """Collapsing + materializing a view for the two-threshold fixture is pure catalog + stream
    CPU work — never audio loaders, model sessions, ONNX inference, or CUDA."""
    harness = _build_pair(compact_catalog_factory, con, tmp_path / "out", song_ids=("s1", "s2"))
    try:
        installed = _install_sentinels(monkeypatch)
        assert installed, "no audio/model/ONNX/CUDA seam was available to sentinel — vacuous test"
        classes = collapse_search_representations(harness.con)
        assert len(classes) == 1
        _materialize(harness, run_id="run-p1s3-cpu")  # must complete without touching any seam
    finally:
        harness.close()


def test_single_config_exact_and_search_hashes_are_distinct_identities(compact_catalog_factory, con, tmp_path):
    """exact_segmentation_hash != search_representation_hash even for ONE config.

    The two hashes are genuinely distinct identities over a single (already-canonical)
    direct-L2 config: ``exact_segmentation_hash`` folds in the canonical config fields
    (threshold_effective, backbone, bin_mode, outlier_window) while
    ``search_representation_hash`` deliberately excludes them and aggregates only the
    current per-song search leaves.  They must never collide, and a one-config catalog
    collapses to a self-only class with the config as its own canonical (no aliases).
    """
    harness = _build_pair(compact_catalog_factory, con, tmp_path / "out", thresholds=(0.9,), song_ids=("s1",))
    try:
        by_threshold = _threshold_to_config(harness.con)
        ids = sorted(by_threshold.values())
        assert len(ids) == 1  # exactly the single canonical config
        cid = ids[0]
        exact = exact_segmentation_hash(harness.con, cid)
        search = search_representation_hash(harness.con, cid)
        assert len(exact) == 64 and len(search) == 64
        assert exact != search  # distinct identities, never aliases of one another
        classes = collapse_search_representations(harness.con)
        assert len(classes) == 1
        assert classes[0].config_ids == (cid,)
        assert classes[0].alias_ids == ()
        assert classes[0].canonical_config_id == cid
    finally:
        harness.close()
