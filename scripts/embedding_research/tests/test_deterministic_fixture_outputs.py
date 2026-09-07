"""P1-S3 spec-first: full phase-output + provenance proofs over the P1-S2 deterministic run.

Plan ``TASK-frozen-observation-semantic-runtime-corrective-pass-D-deterministic-fixture-
verification`` step P1-S3.  These tests drive the :class:`FixtureCliRunner` (the real eight-command
CLI dispatch) once over a fresh deterministic corpus and then prove, against the DURABLE artifacts
and DB rows that run left behind, every output/provenance clause of the step:

1. committed stream / mask / head payloads + per-song observation-commit markers, all named by the
   payload grammar ``<song_id>.<backbone>.<64-hex-sha256><suffix>`` and carrying the identity fields;
2. the per-song group CURRENT markers (the commit markers binding stream+mask) and the
   ``heads/current/<sid>.<bb>.json`` head CURRENT markers with their binding fields;
3. the compact catalog + ``catalogs/current.json`` pointer and the catalog rows matching the fixture
   literals (configs 0.9/1.0/0.2; per-song segments, absorbed indices/count, searchable counts and
   weights, segment boundaries, medoid source indices);
4. the catalog-report output artifact with the expected content;
5. exactly ONE analyze execution per unique search class (the 0.9/1.0 alias class scored once over
   its canonical rows + the distinct 0.2 class once), aliases adding ZERO executions and classes
   never unioned — asserted on the recorded analyze strategy rows / view refs / collapse classes;
6. weights normalise to one for every searchable song under every config;
7. silence / absorbed-outlier / zero-searchable exclusion on the PERSISTED data (``sil`` silent run,
   ``abs`` absorbed index, ``z0`` metadata-only + absent from search/baseline/head coverage);
8. the observed ``global_pool:effnet:medoid`` baseline rows + finite winner deltas for every
   segmented result, with per-song baseline medoid sources equal to the frozen fixture literals;
9. canonical head-analysis rows over the committed masks (finite, done, z0 absent);
10. the seven-section machine report + human HTML, all finite, with no CTP/ANN/compatibility output;
11. analyze / head-analysis / report run ids recorded in ``run_provenance``; timings finite.

Every expected VALUE below is an explicit synthetic fixture literal (hand-computable from the
P1-S1 corpus) or a structural/format contract — never a number derived from the implementation
under test at runtime.  All artifacts are synthetic; this run makes no empirical retrieval claim.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.helpers.segmentation import observed_global_medoid
from scripts.embedding_research.tests.fixture_cli_harness import (
    ALL_THRESHOLDS,
    BACKBONE,
    BASELINE_MEDOID_SOURCE,
    SEARCHABLE_SONGS,
    SONGS,
    song_mask,
    stream_matrix,
)
from scripts.embedding_research.tests.fixture_runtime_harness import FixtureCliRunner

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: Analyze config surface used by :class:`FixtureCliRunner` in this proof (P1-S1 golden).
ALIAS_CONFIG_THRESHOLDS = (0.9, 1.0)
DISTINCT_CONFIG_THRESHOLD = 0.2
#: The one head configured for the infer-heads phase in the runner.
HEAD_ID = "timbre"
#: k used by the analyze phase.
K = 10
#: The observed-medoid baseline strategy identity for the effnet backbone.
MEDOID_BASELINE_KEY = f"global_pool:{BACKBONE}:medoid"

#: Whole-song searchable (mask-aware, structural) counts per song — hand-computable literals.
SEARCHABLE_TOTAL: dict[str, int] = {
    "s1": 6,
    "s2": 6,
    "s3": 6,
    "s4": 6,
    "sil": 3,
    "abs": 5,
    "hard": 6,
    "z0": 0,
}

#: The suffixed retrieval vocabulary each analyze class / medoid baseline emits (fixed set
#: produced by the analyze phase, amended P3-S2).  No generic unsuffixed or composite key.
REPORT_METRICS = (
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
)

#: Payload-grammar regex: <song_id>.<backbone>.<64-hex-sha256><.suffix>.
_PAYLOAD_RE = re.compile(r"^([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\.([0-9a-f]{64})\.(npy|npz|json)$")

#: Forbidden vocabulary that must not appear in any pipeline machine output (report.json/
#: report.html/catalog_report.txt/commit-marker JSON/manifests over the real deterministic run).
#: ``ann`` is checked as a standalone word only (substrings like ``canonical`` legitimately
#: contain "ann").  Plan C P3-S2 adds the removed analyze emit/migration tokens and the
#: back-compat/deprecated transitional phrasings to the P1-era set; ``legacy``/``compat`` already
#: subsume ``legacy_run_id``/``back-compat``/``backward-compatibility``.
_FORBIDDEN_SUBSTRINGS = (
    "ctp",
    "compat",
    "fallback",
    "legacy",
    "onnx",
    "cuda",
    "dual-write",
    # P3-S2 transitional tokens (``disc_score`` alias and removed analyze surface).
    "disc_score",
    "emit_medoid_baseline",
    "emit-medoid-baseline",
    "back_compat",
    "deprecated",
    "migrate_analyze_metrics_provenance",
    "analyze_metrics_backup",
)


@dataclass
class RunSnapshot:
    """The single P1-S2-equivalent deterministic run under test + artifact access helpers."""

    runner: Any = field(repr=False)
    con: Any = field(repr=False)
    output_root: Path = field(repr=False)

    @property
    def evidence(self):
        return self.runner.evidence

    # -- catalog access ------------------------------------------------------ #
    def catalog_info(self) -> tuple[Path, dict[str, Any]]:
        """Resolve ``catalogs/current.json`` -> the real catalog dir + its manifest."""
        cur = json.loads((self.output_root / "catalogs" / "current.json").read_text())
        cat_id = cur["catalog_id"]
        cat_dir = self.output_root / "catalogs" / cat_id
        assert cat_dir.is_dir(), "catalogs/current.json must point at a real catalog dir"
        manifest = json.loads((cat_dir / "catalog.manifest.json").read_text())
        return cat_dir, manifest

    def open_catalog(self):
        """Open the current compact catalog duckdb read-only."""
        cat_dir, _manifest = self.catalog_info()
        return duckdb.connect(str(cat_dir / "catalog.duckdb"), read_only=True)

    def config_id_for(self, threshold: float) -> int:
        """The compact catalog ``seg_config.config_id`` whose effective threshold is *threshold*."""
        with self.open_catalog() as c:
            rows = c.execute(
                "SELECT config_id FROM seg_config WHERE threshold_effective=?", (float(threshold),)
            ).fetchall()
        assert len(rows) == 1, f"expected exactly one config at threshold {threshold}"
        return int(rows[0][0])

    def threshold_for_config(self, config_id: int) -> float:
        """The ``threshold_effective`` recorded for a compact catalog ``seg_config.config_id``."""
        with self.open_catalog() as c:
            rows = c.execute(
                "SELECT threshold_effective FROM seg_config WHERE config_id=?", (int(config_id),)
            ).fetchall()
        assert len(rows) == 1
        return float(rows[0][0])


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> RunSnapshot:
    """Drive the real eight-phase CLI dispatch once (module scope) and keep the durable outputs."""
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    out = tmp_path_factory.mktemp("det-outputs")
    runner = FixtureCliRunner(con, out, thresholds=(*ALIAS_CONFIG_THRESHOLDS, DISTINCT_CONFIG_THRESHOLD))
    runner.run_all()
    return RunSnapshot(runner=runner, con=con, output_root=out)


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #
def _payload_files(directory: Path, suffix: str) -> list[tuple[re.Match, Path]]:
    """Return (regex-match, path) for payload files in *directory* of the given *suffix*."""
    out = []
    for f in sorted(x for x in directory.iterdir() if x.is_file() and x.suffix == suffix):
        m = _PAYLOAD_RE.match(f.name)
        assert m, f"payload filename {f.name} violates the payload grammar"
        out.append((m, f))
    return out


def _assert_no_forbidden_vocabulary(text: str, label: str) -> None:
    low = text.lower()
    for token in _FORBIDDEN_SUBSTRINGS:
        assert token not in low, f"{label} contains forbidden vocabulary {token!r}"
    assert not re.search(r"\bann\b", low), f"{label} contains the word 'ann'"


def _segment_literal(row) -> tuple[int, int, list[int], int, int, float]:
    """Normalise a ``seg_meta`` row (name order) to hand-comparable literal fields."""
    _song, _seg_id, start, end, absorbed, absorbed_count, searchable, _medoid, weight = row
    return (int(start), int(end), json.loads(absorbed), int(absorbed_count), int(searchable), float(weight))


def _winner_delta_rows(report: dict[str, Any]) -> list[dict[str, str]]:
    """Return the ``winner_delta_*`` table rows from the report winners section."""
    rows: list[dict[str, str]] = []
    for section in report["sections"]:
        if section["id"] != "winners":
            continue
        for sub in section.get("subsections", []):
            for table in sub.get("tables", []):
                if table["id"].startswith("winner_delta_"):
                    cols = table["columns"]
                    rows.extend(dict(zip(cols, r, strict=False)) for r in table["rows"])
    return rows


# --------------------------------------------------------------------------- #
# 1. Committed stream / mask / head payloads + commit markers                   #
# --------------------------------------------------------------------------- #
def test_committed_stream_and_mask_payloads_are_published_bytes(run):
    """Every song has an immutable stream + aligned uint8 mask payload, byte-equal to the corpus."""
    streams = run.output_root / "streams"
    masks = run.output_root / "audio_masks"
    assert streams.is_dir() and masks.is_dir()

    stream_files = _payload_files(streams, ".npy")
    mask_files = _payload_files(masks, ".npy")
    # One committed stream and one committed mask per song.
    assert {m.group(1) for m, _ in stream_files} == set(SONGS)
    assert {m.group(1) for m, _ in mask_files} == set(SONGS)
    assert {m.group(2) for m, _ in stream_files} == {BACKBONE}

    for song in SONGS:
        sfile = next(f for m, f in stream_files if m.group(1) == song)
        mfile = next(f for m, f in mask_files if m.group(1) == song)
        # Payload byte content equals the deterministic corpus literal.
        assert np.array_equal(np.load(sfile, allow_pickle=False), stream_matrix(song)), song
        assert np.array_equal(np.load(mfile, allow_pickle=False), song_mask(song)), song
        # Sidecar manifest identity: digest in the filename matches the sidecar payload_sha256.
        sj = json.loads(sfile.with_suffix(".json").read_text())
        mj = json.loads(mfile.with_suffix(".json").read_text())
        assert sj["kind"] == "stream" and sj["payload_sha256"] == sfile.name.split(".")[-2]
        assert sj["dim"] == stream_matrix(song).shape[1] and sj["dtype"] == "float32"
        assert sj["patch_count"] == stream_matrix(song).shape[0]
        assert mj["kind"] == "mask" and mj["payload_sha256"] == mfile.name.split(".")[-2]
        assert mj["dtype"] == "uint8" and mj["song_id"] == song


def test_observation_commit_markers_and_head_payloads(run):
    """Commit markers (group CURRENT) + head payloads exist per song with the identity fields."""
    commits = run.output_root / "observation_commits"
    heads = run.output_root / "heads"
    commit_files = _payload_files(commits, ".json")
    head_files = _payload_files(heads, ".npz")
    assert {m.group(1) for m, _ in commit_files} == set(SONGS)
    assert {m.group(1) for m, _ in head_files} == set(SONGS)
    assert {m.group(2) for m, _ in commit_files} == {BACKBONE}
    assert {m.group(2) for m, _ in head_files} == {BACKBONE}

    for song in SONGS:
        cmarker = json.loads(next(f for m, f in commit_files if m.group(1) == song).read_text())
        # The commit marker is the group CURRENT identity: it binds the committed stream + mask.
        assert cmarker["song_id"] == song and cmarker["backbone"] == BACKBONE
        assert cmarker["status"] == "ready"
        assert cmarker["run_id"] == run.evidence.phase_run_id("embed")
        for identity_key in (
            "stream_ref",
            "mask_ref",
            "alignment_token",
            "audio_content_sha256",
            "mask_semantics_version",
            "commit_sha256",
        ):
            assert identity_key in cmarker, f"commit marker missing {identity_key}"
        # Grammar: stream/mask refs are <dir>/<song>.<bb>.<64hex>.npy and resolve to real files.
        for ref_key in ("stream_ref", "mask_ref"):
            ref = cmarker[ref_key]
            assert _PAYLOAD_RE.match(ref.rsplit("/", 1)[-1]), f"bad {ref_key} grammar {ref}"
            assert (run.output_root / ref).is_file(), f"{ref_key} {ref} does not exist"
        # The marker's commit digest equals the digest in its filename (written-last publication).
        assert cmarker["commit_sha256"] == next(f for m, f in commit_files if m.group(1) == song).name.split(".")[-2]

        # Head payload identity binds back to the committed stream (same song/backbone/digest).
        hfile = next(f for m, f in head_files if m.group(1) == song)
        hj = json.loads(hfile.with_suffix(".json").read_text())
        assert hj["kind"] == "head" and hj["song_id"] == song and hj["backbone"] == BACKBONE
        assert hj["payload_sha256"] == hfile.name.split(".")[-2]
        assert hj["head_ids"] == HEAD_ID
        assert hj["dim_by_head"] == f"{HEAD_ID}=2"
        assert hj["patch_count"] == stream_matrix(song).shape[0]
        # The head payload is aligned to the committed stream digest.
        assert hj["stream_digest"] == cmarker["stream_ref"].rsplit(".", 1)[0].rsplit(".", 1)[-1]


# --------------------------------------------------------------------------- #
# 2. Group CURRENT + head CURRENT markers                                       #
# --------------------------------------------------------------------------- #
def test_group_and_head_current_markers_exist_with_binding_fields(run):
    """Commit markers + heads/current/<song>.<bb>.json bind head payload to stream + head suite."""
    # Group CURRENT mechanism: one ready committed observation group per song (registry single row).
    ready = run.con.execute(
        "SELECT song_id, status FROM stream_registry WHERE backbone=? ORDER BY song_id", (BACKBONE,)
    ).fetchall()
    assert {s for s, st in ready if st == "ready"} == set(SONGS)
    # Head registry: one ready head suite per song.
    head_ready = run.con.execute(
        "SELECT song_id, status FROM head_stream_registry WHERE backbone=? ORDER BY song_id", (BACKBONE,)
    ).fetchall()
    assert {s for s, st in head_ready if st == "ready"} == set(SONGS)

    # Head CURRENT markers live under heads/current/<song>.<backbone>.json.
    cur_dir = run.output_root / "heads" / "current"
    assert cur_dir.is_dir()
    markers = {}
    for song in SONGS:
        marker = cur_dir / f"{song}.{BACKBONE}.json"
        assert marker.is_file(), f"missing head CURRENT marker for {song}"
        markers[song] = json.loads(marker.read_text())

    for song, m in markers.items():
        assert m["kind"] == "head-current"
        assert m["song_id"] == song and m["backbone"] == BACKBONE
        # Binding fields: head payload ref/digest + the committed stream digest it aligns to.
        for identity_key in (
            "stream_ref",
            "stream_digest",
            "head_payload_ref",
            "head_payload_sha256",
            "head_set_fingerprint",
            "alignment_token",
            "generation",
        ):
            assert identity_key in m, f"head CURRENT marker missing {identity_key}"
        assert (run.output_root / m["head_payload_ref"]).is_file(), "head payload ref must resolve"
        # Head marker binds to the same committed stream digest as the group commit marker.
        assert m["stream_digest"] == m["stream_ref"].rsplit(".", 1)[0].rsplit(".", 1)[-1]


# --------------------------------------------------------------------------- #
# 3. Compact catalog + current pointer                                          #
# --------------------------------------------------------------------------- #
def test_compact_catalog_and_current_pointer(run):
    """catalogs/current.json points at a real catalog; seg_config rows match {0.9, 1.0, 0.2}."""
    cat_dir, manifest = run.catalog_info()
    assert (cat_dir / "catalog.duckdb").is_file()
    assert manifest["catalog_id"] == cat_dir.name
    assert manifest["seg_config_rows"] == 3
    with run.open_catalog() as c:
        rows = c.execute(
            "SELECT config_id, threshold_configured, threshold_effective, threshold_semantics"
            " FROM seg_config ORDER BY config_id"
        ).fetchall()
    # config ids are the integer app identity 1..3 (hash-derived ORDER is not pinned across
    # encoder-version changes); thresholds are the fixture's configured==effective set.
    assert [int(r[0]) for r in rows] == [1, 2, 3]
    assert sorted(float(r[1]) for r in rows) == sorted(ALL_THRESHOLDS)
    assert sorted(float(r[2]) for r in rows) == sorted(ALL_THRESHOLDS)
    assert [r[3] for r in rows] == ["direct_distance"] * 3


def test_catalog_song_and_seg_meta_match_fixture_literals(run):
    """catalog_song totals + seg_meta (alias config 0.9) rows equal the hand-computed corpus."""
    alias_cid = run.config_id_for(ALIAS_CONFIG_THRESHOLDS[0])  # 0.9
    other_alias_cid = run.config_id_for(ALIAS_CONFIG_THRESHOLDS[1])  # 1.0
    with run.open_catalog() as c:
        # Whole-song searchable totals + status across every config.
        for cid in (alias_cid, other_alias_cid, run.config_id_for(DISTINCT_CONFIG_THRESHOLD)):
            song_rows = c.execute(
                "SELECT song_id, total_searchable_count, status FROM catalog_song WHERE config_id=?", (cid,)
            ).fetchall()
            by_song = {s: (int(t), st) for s, t, st in song_rows}
            assert set(by_song) == set(SONGS)
            for song in SONGS:
                total, status = by_song[song]
                assert total == SEARCHABLE_TOTAL[song], f"{song}@{cid} total_searchable_count"
                if song == "z0":
                    assert status == "metadata_only"
                else:
                    assert status == "searchable"

        # seg_meta structural literals under the alias config (0.9) — golden hand-computed shape.
        seg_rows = {
            song: c.execute(
                "SELECT song_id, seg_id, start_idx, end_idx, absorbed_indices, absorbed_count,"
                " searchable_count, search_medoid_source_patch_idx, searchable_weight"
                " FROM seg_meta WHERE config_id=? AND song_id=? ORDER BY seg_id",
                (alias_cid, song),
            ).fetchall()
            for song in SONGS
        }
        # z0 is metadata-only: zero structural segment rows.
        assert seg_rows["z0"] == []
        # Single-segment songs span the whole stream; weight 1.0; medoid source = frozen literal.
        for song in ("s1", "s2", "s3", "s4", "sil", "abs"):
            assert len(seg_rows[song]) == 1, song
            start, end, _absorbed, _absorbed_count, searchable, weight = _segment_literal(seg_rows[song][0])
            assert start == 0 and end == stream_matrix(song).shape[0]
            assert searchable == SEARCHABLE_TOTAL[song]
            assert weight == pytest.approx(1.0)
            assert int(seg_rows[song][0][7]) == BASELINE_MEDOID_SOURCE[song]
        # sil silent run: searchable 3 (5 patches minus silent run at 1,2), never a silent medoid.
        assert _segment_literal(seg_rows["sil"][0]) == (0, 5, [], 0, 3, 1.0)
        assert int(seg_rows["sil"][0][7]) == 0
        # abs absorbed outlier: index 2 absorbed, 5 searchable, medoid source never the outlier.
        assert _segment_literal(seg_rows["abs"][0]) == (0, 6, [2], 1, 5, 1.0)
        assert int(seg_rows["abs"][0][7]) != 2
        # hard: 2 SEARCHABLE segments (weights 1/3 + 2/3), not absorbed.
        assert [_segment_literal(r) for r in seg_rows["hard"]] == [
            (0, 2, [], 0, 2, 1.0 / 3.0),
            (2, 6, [], 0, 4, 2.0 / 3.0),
        ]
        assert [int(r[7]) for r in seg_rows["hard"]] == [0, 2]

        # The 1.0 alias config has identical structural segmentation to the 0.9 config.
        alias_shape = {song: [_segment_literal(r)[:5] for r in seg_rows[song]] for song in SONGS}
        for song in SONGS:
            other = c.execute(
                "SELECT song_id, seg_id, start_idx, end_idx, absorbed_indices, absorbed_count,"
                " searchable_count, search_medoid_source_patch_idx, searchable_weight"
                " FROM seg_meta WHERE config_id=? AND song_id=? ORDER BY seg_id",
                (other_alias_cid, song),
            ).fetchall()
            assert [_segment_literal(r)[:5] for r in other] == alias_shape[song], song

        # stream/mask digests on the committed catalog rows are the standard 64-hex identity form.
        for song in SONGS:
            digests = c.execute(
                "SELECT stream_digest, mask_digest FROM catalog_song WHERE config_id=? AND song_id=?",
                (alias_cid, song),
            ).fetchone()
            assert all(re.fullmatch(r"[0-9a-f]{64}", d) for d in digests), song


# --------------------------------------------------------------------------- #
# 4. Catalog-report output artifact                                             #
# --------------------------------------------------------------------------- #
def test_catalog_report_artifact_has_expected_content(run):
    """catalog-report wrote catalog_report.txt describing the canonical/alias/empty-songs surface."""
    txt = (run.output_root / "report" / "catalog_report.txt").read_text()
    assert txt.startswith("catalog-report")
    from scripts.embedding_research.catalog_identity import collapse_search_representations

    distinct_cid = run.config_id_for(DISTINCT_CONFIG_THRESHOLD)
    with run.open_catalog() as c:
        classes = list(collapse_search_representations(c))
    alias_cls = next(cls for cls in classes if distinct_cid not in (set(cls.config_ids) | set(cls.alias_ids)))
    alias_cid = alias_cls.canonical_config_id  # representative (0.9 or 1.0 — hash-order chosen)
    other_alias_cid = next(iter(alias_cls.alias_ids))  # the folded non-representative alias
    # The report lists the two canonical search classes (alias representative + distinct) and the alias.
    canon_cids = ", ".join(str(i) for i in sorted([alias_cid, distinct_cid]))
    assert f"canonical configs (2): {canon_cids}" in txt
    assert f"alias {other_alias_cid} -> canonical {alias_cid}" in txt
    # z0 is the empty song under every config (metadata-only, zero searchable mass).
    for cid in (alias_cid, other_alias_cid, distinct_cid):
        assert f"config {cid} song 'z0'" in txt
    # No forbidden vocabulary in the catalog report.
    _assert_no_forbidden_vocabulary(txt, "catalog_report.txt")


# --------------------------------------------------------------------------- #
# 5. One execution per unique search class; aliases add zero; never unioned     #
# --------------------------------------------------------------------------- #
def test_analyze_one_execution_per_unique_search_class(run):
    """Exactly one catalog pass per search class: alias {0.9,1.0} once + distinct 0.2 once."""
    analyze_run = run.evidence.phase_run_id("analyze")
    keys = run.con.execute(
        "SELECT DISTINCT strategy_key FROM analyze_metrics WHERE strategy_type='catalog' AND run_id=?",
        (analyze_run,),
    ).fetchall()
    # Two distinct search classes -> exactly two catalog strategy keys (aliases add ZERO).
    assert len(keys) == 2
    assert all(k[0].startswith(f"catalog:{BACKBONE}:") for k in keys)

    # Every metric was scored exactly once per class (2 classes) — no alias duplicate pass.
    per_metric = run.con.execute(
        "SELECT metric, count(*) FROM analyze_metrics WHERE strategy_type='catalog' AND run_id=?"
        " GROUP BY metric ORDER BY metric",
        (analyze_run,),
    ).fetchall()
    assert len(per_metric) == len(REPORT_METRICS)
    assert all(n == 2 for _m, n in per_metric)

    # Distinct classes were never unioned: two independent materialized search views are recorded.
    view_refs = run.con.execute("SELECT view_refs FROM run_provenance WHERE run_id=?", (analyze_run,)).fetchone()[0]
    assert view_refs.count("\n") == 1 and len(view_refs.splitlines()) == 2

    # The two classes are exactly the alias pair and the distinct threshold (collapse classes),
    # and distinct classes are never unioned together.
    from scripts.embedding_research.catalog_identity import collapse_search_representations

    with run.open_catalog() as c:
        classes = collapse_search_representations(c)
    # Rebuild memberships from config thresholds to compare against the golden literals.
    th_of = {cid: run.threshold_for_config(cid) for cls in classes for cid in cls.config_ids}
    memberships = [frozenset(round(th_of[cid], 3) for cid in cls.config_ids) for cls in classes]
    assert frozenset(ALIAS_CONFIG_THRESHOLDS) in memberships
    assert frozenset((DISTINCT_CONFIG_THRESHOLD,)) in memberships
    assert len(memberships) == 2  # distinct classes never unioned into one


def test_alias_members_add_zero_executions_and_never_appear_alone(run):
    """The two alias thresholds fold into ONE canonical class (one canonical, one folded alias).

    Which threshold is the representative is hash-order-determined (0.9 and 1.0 are equal
    search representations), so the assertions are representative-agnostic.
    """
    from scripts.embedding_research.catalog_identity import collapse_search_representations

    with run.open_catalog() as c:
        classes = list(collapse_search_representations(c))
    alias_members = {run.config_id_for(t) for t in ALIAS_CONFIG_THRESHOLDS}
    distinct_cid = run.config_id_for(DISTINCT_CONFIG_THRESHOLD)
    alias_cls = next(cls for cls in classes if distinct_cid not in (set(cls.config_ids) | set(cls.alias_ids)))
    # both alias thresholds are members; exactly one is the canonical representative, the sibling folds
    assert set(alias_cls.config_ids) | set(alias_cls.alias_ids) == alias_members
    assert alias_cls.canonical_config_id in alias_members
    assert set(alias_cls.alias_ids) == alias_members - {alias_cls.canonical_config_id}
    assert distinct_cid not in set(alias_cls.config_ids) | set(alias_cls.alias_ids)
    # The distinct class is its own canonical with no alias.
    distinct_cls = next(cls for cls in classes if distinct_cid in set(cls.config_ids) | set(cls.alias_ids))
    assert tuple(distinct_cls.config_ids) == (distinct_cid,) and not distinct_cls.alias_ids


# --------------------------------------------------------------------------- #
# 6. Weights normalise to one per searchable song                               #
# --------------------------------------------------------------------------- #
def test_searchable_weights_normalize_to_one_in_catalog(run):
    """For every config and every searchable song the seg_meta weights sum to exactly one."""
    for threshold in ALL_THRESHOLDS:
        cid = run.config_id_for(threshold)
        with run.open_catalog() as c:
            for song in SEARCHABLE_SONGS:
                rows = c.execute(
                    "SELECT searchable_weight FROM seg_meta WHERE config_id=? AND song_id=?",
                    (cid, song),
                ).fetchall()
                assert rows, f"{song}@{threshold} must be searchable"
                total = sum(float(r[0]) for r in rows)
                assert total == pytest.approx(1.0), f"{song}@{threshold} weights do not sum to one"


# --------------------------------------------------------------------------- #
# 7. Silence / absorbed-outlier / zero-searchable exclusion on persisted data    #
# --------------------------------------------------------------------------- #
def test_silent_run_and_absorbed_outlier_excluded_on_persisted_data(run):
    """sil's silent run and abs's absorbed index contribute zero searchable mass on disk."""
    sil_mask = song_mask("sil")
    assert sil_mask.tolist() == [1, 0, 0, 1, 1]
    # The committed mask payload on disk carries that exact literal.
    mfile = next(f for m, f in _payload_files(run.output_root / "audio_masks", ".npy") if m.group(1) == "sil")
    assert np.load(mfile, allow_pickle=False).tolist() == [1, 0, 0, 1, 1]
    alias_cid = run.config_id_for(ALIAS_CONFIG_THRESHOLDS[0])
    with run.open_catalog() as c:
        sil_medoid = c.execute(
            "SELECT search_medoid_source_patch_idx, searchable_count FROM seg_meta WHERE config_id=? AND song_id='sil'",
            (alias_cid,),
        ).fetchone()
        # Medoid never the silent indices {1,2}; searchable 3 (of 5).
        assert sil_medoid[0] == 0 and sil_medoid[1] == 3
        abs_medoid = c.execute(
            "SELECT search_medoid_source_patch_idx, searchable_count, absorbed_count FROM seg_meta"
            " WHERE config_id=? AND song_id='abs'",
            (alias_cid,),
        ).fetchone()
        assert abs_medoid[0] != 2 and abs_medoid[1] == 5 and abs_medoid[2] == 1


def test_zero_searchable_song_retained_but_excluded_from_search_and_baseline(run):
    """z0 keeps catalog metadata but is excluded from search/baseline/head-analysis coverage."""
    alias_cid = run.config_id_for(ALIAS_CONFIG_THRESHOLDS[0])
    # Committed z0 mask is fully silent on disk.
    mfile = next(f for m, f in _payload_files(run.output_root / "audio_masks", ".npy") if m.group(1) == "z0")
    assert np.load(mfile, allow_pickle=False).tolist() == [0, 0, 0]
    with run.open_catalog() as c:
        row = c.execute(
            "SELECT status, total_searchable_count FROM catalog_song WHERE config_id=? AND song_id='z0'",
            (alias_cid,),
        ).fetchone()
        assert row == ("metadata_only", 0)
        assert c.execute("SELECT count(*) FROM seg_meta WHERE song_id='z0'").fetchone()[0] == 0
    # z0 is not among the baseline population (no per-song baseline medoid) and is excluded from
    # the head-analysis coverage (n_songs == len(SEARCHABLE_SONGS) == 7).
    assert BASELINE_MEDOID_SOURCE["z0"] is None
    n_head_songs = run.con.execute(
        "SELECT n_songs FROM head_phase_provenance WHERE run_id=? AND config_id=?",
        (run.evidence.phase_run_id("head-analysis"), alias_cid),
    ).fetchone()[0]
    assert int(n_head_songs) == len(SEARCHABLE_SONGS) == 7


# --------------------------------------------------------------------------- #
# 8. Observed medoid baseline + finite deltas for every segmented result        #
# --------------------------------------------------------------------------- #
def test_global_pool_medoid_baseline_rows_exist_and_never_win(run):
    """global_pool:effnet:medoid rows exist per metric; the medoid is never a winner candidate."""
    analyze_run = run.evidence.phase_run_id("analyze")
    medoid = run.con.execute(
        "SELECT strategy_type, strategy_key, sim_metric, k, metric FROM analyze_metrics"
        " WHERE strategy_type='global_pool' AND run_id=? ORDER BY metric",
        (analyze_run,),
    ).fetchall()
    # One observed-medoid baseline row per metric (strategy_type distinct from 'catalog').
    assert len(medoid) == len(REPORT_METRICS)
    assert all(r[0] == "global_pool" and r[1] == MEDOID_BASELINE_KEY for r in medoid)
    assert all(r[2] == "cosine" and int(r[3]) == K for r in medoid)
    assert {r[4] for r in medoid} == set(REPORT_METRICS)

    # The medoid baseline is never a winner candidate in the report (winners are catalog classes).
    report = json.loads((run.output_root / "report" / "report.json").read_text())
    for row in _winner_delta_rows(report):
        assert row["baseline_strategy_key"] == MEDOID_BASELINE_KEY
        assert row["winner_strategy_key"].startswith("catalog:")
        # delta = winner - baseline, finite.  winner/baseline/delta each pass through the
        # report JSON as floats sourced from np.float32 aggregate cells, so a near-equal
        # winner-vs-baseline cell (common for the per-ruler genre/head cells added in P3-S2)
        # can differ from ``baseline + delta`` at ~float32 scale (~1e-4); compare with an
        # absolute tolerance that absorbs that quantization while still pinning the invariant.
        delta = float(row["delta"])
        assert math.isfinite(delta)
        assert float(row["winner_value"]) == pytest.approx(float(row["baseline_value"]) + delta, abs=1e-3)


def test_per_song_baseline_medoid_sources_match_frozen_literals_on_committed_bytes(run):
    """Feeding the committed stream+mask through the observed medoid reproduces the golden sources."""
    streams = {m.group(1): f for m, f in _payload_files(run.output_root / "streams", ".npy")}
    masks = {m.group(1): f for m, f in _payload_files(run.output_root / "audio_masks", ".npy")}
    for song in SEARCHABLE_SONGS:
        vecs = np.load(streams[song], allow_pickle=False)
        mask = np.load(masks[song], allow_pickle=False)
        population = [i for i in range(len(mask)) if mask[i] == 1]
        med = observed_global_medoid(vecs, population)
        assert med.source_index == BASELINE_MEDOID_SOURCE[song], song


# --------------------------------------------------------------------------- #
# 9. Canonical head-analysis rows over the committed masks                       #
# --------------------------------------------------------------------------- #
def test_canonical_head_analysis_rows_over_committed_masks(run):
    """head-analysis emitted one canonical row per config; finite, done, 7 searchable songs pooled."""
    rows = run.con.execute(
        "SELECT config_id, backbone, head, bin_mode, semantics, boundary_source, head_pool_variant,"
        " status, n_songs, n_pooled, finite, threshold_effective"
        " FROM head_phase_provenance WHERE run_id=? ORDER BY config_id",
        (run.evidence.phase_run_id("head-analysis"),),
    ).fetchall()
    assert len(rows) == 3  # one canonical row per seg_config (configs 0.9 / 1.0 / 0.2)
    cids = [int(r[0]) for r in rows]
    assert cids == sorted(run.config_id_for(t) for t in ALL_THRESHOLDS)
    for r in rows:
        assert r[1] == BACKBONE and r[2] == HEAD_ID
        assert r[3] == "temporal_global" and r[4] == "direct_distance"
        assert r[5] == "catalog" and r[6] == "shared_catalog_boundary"
        assert r[7] == "done" and int(r[8]) == len(SEARCHABLE_SONGS) == 7 and int(r[9]) == 7
        assert int(r[10]) == 1  # finite
        # threshold_effective matches the catalog seg_config for this config id.
        assert float(r[11]) == pytest.approx(run.threshold_for_config(r[0]))


# --------------------------------------------------------------------------- #
# 10. Seven-section machine + human report, finite, no forbidden vocabulary     #
# --------------------------------------------------------------------------- #
def test_seven_section_report_json_and_html_present(run):
    """report.json has the seven sections in order; report.html exists; all values finite."""
    report = json.loads((run.output_root / "report" / "report.json").read_text())
    assert report["schema_version"] == 2
    ids = [s["id"] for s in report["sections"]]
    assert ids == ["summary", "corpus", "analysis", "winners", "head-analysis", "provenance", "efficiency"]
    # Human-readable report present.
    html = (run.output_root / "report" / "report.html").read_text()
    assert len(html) > 1000

    # Every numeric value in the machine report is finite (no NaN/Inf anywhere).
    def _assert_finite(node):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            assert math.isfinite(float(node)), f"non-finite report value {node!r}"
        elif isinstance(node, dict):
            for v in node.values():
                _assert_finite(v)
        elif isinstance(node, list):
            for v in node:
                _assert_finite(v)

    _assert_finite(report)
    # No forbidden vocabulary in the machine report JSON.
    _assert_no_forbidden_vocabulary(json.dumps(report), "report.json")


def test_no_forbidden_vocabulary_in_any_machine_output(run):
    """No CTP/ANN/compatibility/onnx/cuda vocabulary in committed markers / manifest / report."""
    blobs: list[str] = []
    for directory in ("streams", "audio_masks", "observation_commits", "heads"):
        blobs.extend(f.read_text() for f in (run.output_root / directory).glob("*.json"))
    blobs.extend(f.read_text() for f in (run.output_root / "heads" / "current").glob("*.json"))
    _cat_dir, manifest = run.catalog_info()
    blobs.append(json.dumps(manifest))
    blobs.append((run.output_root / "report" / "catalog_report.txt").read_text())
    for i, blob in enumerate(blobs):
        _assert_no_forbidden_vocabulary(blob, f"machine-output #{i}")


def test_real_seam_run_report_is_not_mislabeled_synthetic(run):
    """P3-S4: a real seam run's report is NOT mislabeled with the generator-only SYNTHETIC banner.

    ``generate_fixture_report.py`` injects ``SYNTHETIC_WARNING`` into its GENERATED fixture
    report (the validator requires it there).  The real ``FixtureCliRunner`` eight-phase run is a
    genuine OBSERVED run over the deterministic synthetic data — labeling it with the generator's
    "SYNTHETIC FIXTURE — no empirical retrieval claim." banner would be a false statement, so the
    real run's machine + human reports must NOT carry that marker.  This pins the P3-S4 labeling
    boundary (measured evidence labeled correctly; real seam runs never mislabeled synthetic).
    """
    from scripts.embedding_research.generate_fixture_report import SYNTHETIC_WARNING

    marker = SYNTHETIC_WARNING["message"]
    assert "SYNTHETIC" in marker and "no empirical retrieval claim" in marker
    report_json = (run.output_root / "report" / "report.json").read_text()
    report_html = (run.output_root / "report" / "report.html").read_text()
    assert marker not in report_json, "real seam run report.json must not carry the generator-only synthetic banner"
    assert marker not in report_html, "real seam run report.html must not carry the generator-only synthetic banner"


# --------------------------------------------------------------------------- #
# 11. Run provenance ids + finite timings                                       #
# --------------------------------------------------------------------------- #
def test_analyze_head_analysis_report_run_ids_recorded_with_finite_timing(run):
    """analyze / head-analysis / report run ids are recorded in run_provenance with finite timing."""
    wanted = {"analyze": "analyze", "head-analysis": "head-analysis", "report": "report"}
    rows = run.con.execute("SELECT run_id, phase, status, started_at, finished_at FROM run_provenance").fetchall()
    by_phase = {r[1]: r for r in rows}
    for phase in wanted:
        assert phase in by_phase, f"{phase} missing a run_provenance row"
        run_id, _got_phase, status, started, finished = by_phase[phase]
        assert run_id == run.evidence.phase_run_id(phase)
        assert status in {"completed", "complete"}
        # started_at / finished_at are finite millisecond timestamps with a valid ordering.
        assert isinstance(started, int) and isinstance(finished, int)
        assert started <= finished
    # The active efficiency source (phase_timings) holds only finite elapsed_s rows (empty here: the
    # real CLI dispatch records run_provenance, not phase_timings; only the report generator seeds it).
    timings = run.con.execute("SELECT elapsed_s FROM phase_timings").fetchall()
    for (elapsed,) in timings:
        assert math.isfinite(float(elapsed))


# --------------------------------------------------------------------------- #
# Plan D P1-S3: the ONE per-backbone evaluation-corpus identity on the durable #
# analyze scope (real effnet fixture, incl. sil / abs included, z0 excluded).  #
# --------------------------------------------------------------------------- #
def test_durable_analyze_scope_carries_one_real_evaluation_corpus_identity(run):
    """P1-S3: the persisted analyze scope lines all share the resolve_evaluation_corpus identity.

    Corpus identity flows from ``catalog_identity.resolve_evaluation_corpus`` over the compact
    catalog's requested song ids (the same seam ``run.py::_run_analyze`` threads into every class
    and the mandatory baseline).  For THIS fixture backbone (effnet) the catalog-requested set is
    exactly the seven searchable songs: ``sil`` and ``abs`` are present (their committed silence
    masks are honoured — at least one non-silent whole-song patch each), and ``z0`` is absent from
    ``seg_meta`` (metadata-only, zero searchable) so it is never even requested.  Re-resolving the
    durable catalog after the run must reproduce the SAME hash/count/comparability that every
    class scope and the baseline scope persisted — proving report/durable identity does not depend
    on a later catalog pointer or a disposable view keyset.
    """
    from scripts.embedding_research.catalog_identity import (
        catalog_requested_song_ids,
        resolve_evaluation_corpus,
    )
    from scripts.embedding_research.db import analyze_scope as _scope
    from scripts.embedding_research.streams import StreamStore

    with run.open_catalog() as cat:
        # Mirror run.py's requested population seam (P2-S1): the catalog-REQUESTED surface
        # (catalog_song leaves under a config of the backbone), resolved BEFORE seg_meta /
        # representation searchability — NOT the seg_meta-derived set.
        requested = catalog_requested_song_ids(cat, BACKBONE)
        identity = resolve_evaluation_corpus(
            cat, StreamStore(run.con, output_root=str(run.output_root)), requested, backbone=BACKBONE
        )
    # The seven searchable songs are the ELIGIBLE population: sil + abs included (mask-aware,
    # still non-silent), and z0 (committed but fully-silent, metadata-only catalog_song leaf with
    # no seg_meta rows) is REQUESTED and carried as excluded missing evidence — never silently
    # dropped from the requested population.
    assert set(identity.song_ids) == set(SEARCHABLE_SONGS) and len(SEARCHABLE_SONGS) == 7
    assert identity.eligible is True and identity.comparable is True
    assert identity.count == len(SEARCHABLE_SONGS) == 7
    assert identity.missing_song_ids == ("z0",) and identity.missing_count == 1

    # Every corpus-bearing persisted analyze scope line (each distinct class scope AND the
    # mandatory observed-medoid baseline scope) names this ONE real identity.
    parsed: list[dict[str, Any]] = []
    for (blob,) in run.con.execute(
        "SELECT output_artifact_hashes FROM run_provenance WHERE phase='analyze'"
    ).fetchall():
        if not blob:
            continue
        for line in blob.splitlines():
            p = _scope.parse_analyze_scope(line.strip())
            if p is not None and "evaluation_corpus_hash" in p:
                parsed.append(p)
    assert parsed, "analyze must persist at least one corpus-bearing scope line"
    hashes = {p["evaluation_corpus_hash"] for p in parsed}
    assert hashes == {identity.corpus_hash}, "all scope lines must share the real resolve_evaluation_corpus hash"
    for p in parsed:
        assert p["evaluation_corpus_count"] == identity.count == 7
        assert p["evaluation_corpus_comparable"] is True
        assert p["evaluation_corpus_missing_count"] == identity.missing_count == 1


# --------------------------------------------------------------------------- #
# Plan D Phase 2 (P2-S2 / P2-S3 / P2-S4): evidence over the REAL fixture render #
# --------------------------------------------------------------------------- #
def _report_analysis_rows(report: dict, backbone: str = "effnet") -> list[dict]:
    """The decoded ``catalog_analysis_{backbone}`` rows from a real ``report.json``."""
    analysis = next(s for s in report["sections"] if s["id"] == "analysis")
    sub = next(s for s in analysis["subsections"] if s["title"] == backbone)
    table = next(t for t in sub["tables"] if t["id"] == f"catalog_analysis_{backbone}")
    return [dict(zip(table["columns"], r, strict=False)) for r in table["rows"]]


def test_report_rendered_semantic_hash_equals_durable_catalog_search_hash(run):
    """P2-S2: the real report's rendered representation_hash IS the durable catalog identity.

    Reads the REAL deterministic fixture ``report.json`` analysis rows and recomputes each
    analyzed class's semantic hash over the surviving compact catalog with
    ``catalog_identity.search_representation_hash`` — the same primitive the analyze phase
    consumed.  The rendered semantic identity must equal that durable catalog hash for every
    analyzed class and every metric row, never a disposable view/keyset hash (rendered in its
    own separate column).
    """
    from scripts.embedding_research.catalog_identity import collapse_search_representations

    report = json.loads((run.output_root / "report" / "report.json").read_text())
    rows = _report_analysis_rows(report)
    assert rows, "the real report must render catalog analysis rows"

    with run.open_catalog() as cat:
        classes = collapse_search_representations(cat)
    durable = {int(c.canonical_config_id): c.search_representation_hash for c in classes}
    assert len(durable) == 2, "fixture collapses to the alias 0.9/1.0 class + the distinct 0.2 class"

    for r in rows:
        cid = int(r["canonical_config_id"])
        assert r["representation_hash"] == durable[cid], (
            "rendered representation_hash must equal the durable catalog search_representation_hash"
        )
        assert r["representation_hash"] != r["view_keyset_hash"], (
            "semantic hash must never equal the disposable view keyset hash"
        )
        assert r["catalog_id"] and r["catalog_fingerprint"], "catalog anchor must render on every row"
    assert {r["representation_hash"] for r in rows} == set(durable.values())


def test_report_matched_rows_share_one_durable_corpus_identity(run):
    """P2-S2: rendered segmented rows and the matched medoid baseline carry the SAME corpus.

    Every rendered catalog analysis row names one durable evaluation-corpus identity
    (hash/count/comparable) that re-resolves to the catalog's ``resolve_evaluation_corpus``
    identity; the observed ``global_pool:{backbone}:medoid`` baseline they are matched against
    carries that SAME corpus identity.  Because every real representation is comparable, the
    report renders NO incomplete-representation diagnostics — nothing is silently dropped.
    """
    from scripts.embedding_research.catalog_identity import (
        catalog_requested_song_ids,
        resolve_evaluation_corpus,
    )
    from scripts.embedding_research.report._retrieval import query_medoid_baselines
    from scripts.embedding_research.streams import StreamStore

    report = json.loads((run.output_root / "report" / "report.json").read_text())
    rows = _report_analysis_rows(report)
    assert rows

    with run.open_catalog() as cat:
        # Mirror run.py's requested population seam (P2-S1): catalog-requested surface, NOT seg_meta.
        requested = catalog_requested_song_ids(cat, BACKBONE)
        identity = resolve_evaluation_corpus(
            cat, StreamStore(run.con, output_root=str(run.output_root)), requested, backbone=BACKBONE
        )

    # Every rendered segmented row names this ONE durable corpus identity.  The requested surface
    # includes z0 (committed, fully-silent, metadata-only) which is excluded as missing evidence.
    for r in rows:
        assert r["evaluation_corpus_hash"] == identity.corpus_hash
        assert int(r["evaluation_corpus_count"]) == identity.count == len(SEARCHABLE_SONGS) == 7
        assert r["evaluation_corpus_comparable"] == "True"
        assert int(r["evaluation_corpus_missing_count"]) == identity.missing_count == 1

    # The medoid baseline the segmented rows are matched against carries the SAME corpus hash.
    analyze_rid = run.evidence.phase_run_id("analyze")
    base = query_medoid_baselines(run.con, run_id=analyze_rid)
    assert not base.empty and (base["backbone"] == BACKBONE).all()
    assert set(base["evaluation_corpus_hash"]) == {identity.corpus_hash}

    # Nothing was dropped on the fully-comparable real corpus.
    winners = next(s for s in report["sections"] if s["id"] == "winners")
    incomplete_ids = [
        t["id"]
        for sub in winners.get("subsections", [])
        for t in sub.get("tables", [])
        if t["id"].startswith("incomplete_representations_")
    ]
    assert incomplete_ids == [], f"comparable real corpus must not render incomplete diagnostics: {incomplete_ids}"


def test_report_carries_complete_corpus_identity_evidence_on_report_frames(run):
    """P2-S3: the report-consumed frames carry the FULL complete 13-column corpus surface.

    Plan C Phase 1 extended the persisted evaluation-corpus identity from the legacy
    hash/count/comparable surface to a COMPLETE evidence surface (requested + eligible digest
    proofs, requested population size, observation-binding digest, an explicit completeness
    marker, and an integrity self-check).  This seam test proves that the frames the report
    winner/delta and incomplete gates actually compare -- the segmented ``catalog`` analysis
    frame AND the matched ``global_pool:{backbone}:medoid`` baseline frame -- expose every one
    of the 13 columns with evidence consistent with the re-resolved COMPLETE identity
    (``completeness=True`` + non-empty integrity), so a delta decision never runs on a
    truncated/identity-less corpus view.
    """
    from scripts.embedding_research.catalog_identity import (
        catalog_requested_song_ids,
        resolve_evaluation_corpus,
    )
    from scripts.embedding_research.report._retrieval import (
        query_analyze_metrics,
        query_medoid_baselines,
    )
    from scripts.embedding_research.streams import StreamStore

    with run.open_catalog() as cat:
        requested = catalog_requested_song_ids(cat, BACKBONE)
        identity = resolve_evaluation_corpus(
            cat, StreamStore(run.con, output_root=str(run.output_root)), requested, backbone=BACKBONE
        )
    # The re-resolved identity is COMPLETE (flagged complete, integrity self-check present).
    assert identity.completeness is True
    assert identity.integrity

    analyze_rid = run.evidence.phase_run_id("analyze")

    # The full 13-column surface columns, as named on the decoded report frames.
    thirteen = [
        "evaluation_corpus_hash",
        "evaluation_corpus_count",
        "evaluation_corpus_comparable",
        "evaluation_corpus_missing_count",
        "evaluation_corpus_missing_digest",
        "evaluation_corpus_semantics_version",
        "evaluation_corpus_eligible",
        "evaluation_corpus_eligible_digest",
        "evaluation_corpus_requested_count",
        "evaluation_corpus_requested_digest",
        "evaluation_corpus_observation_digest",
        "evaluation_corpus_complete",
        "evaluation_corpus_integrity",
    ]

    # Segmented catalog analysis frame: every class row carries the complete surface.
    cat_df = query_analyze_metrics(run.con, run_id=analyze_rid)
    assert not cat_df.empty
    for col in thirteen:
        assert col in cat_df.columns, f"segmented report frame missing complete corpus column {col}"
    for _, row in cat_df.iterrows():
        assert row["evaluation_corpus_hash"] == identity.corpus_hash
        assert int(row["evaluation_corpus_count"]) == identity.count
        assert str(row["evaluation_corpus_comparable"]).lower() == "true"
        assert int(row["evaluation_corpus_requested_count"]) == identity.requested_count
        assert row["evaluation_corpus_requested_digest"] == identity.requested_digest
        assert row["evaluation_corpus_eligible_digest"] == identity.eligible_digest
        assert row["evaluation_corpus_observation_digest"] == identity.observation_digest
        assert bool(row["evaluation_corpus_complete"]) is True
        assert row["evaluation_corpus_integrity"] == identity.integrity

    # Matched medoid-baseline frame carries the SAME complete surface.
    base = query_medoid_baselines(run.con, run_id=analyze_rid)
    assert not base.empty and (base["backbone"] == BACKBONE).all()
    for col in thirteen:
        assert col in base.columns, f"medoid baseline frame missing complete corpus column {col}"
    for _, row in base.iterrows():
        assert row["evaluation_corpus_hash"] == identity.corpus_hash
        assert bool(row["evaluation_corpus_complete"]) is True
        assert row["evaluation_corpus_integrity"] == identity.integrity
        assert row["evaluation_corpus_observation_digest"] == identity.observation_digest

    # Emitted report JSON surfaces the digest/observation evidence (not just legacy hash/count).
    report = json.loads((run.output_root / "report" / "report.json").read_text())
    rows = _report_analysis_rows(report)
    assert rows
    for r in rows:
        assert r["evaluation_corpus_hash"] == identity.corpus_hash
        assert r["evaluation_corpus_comparable"] == "True"
    # On the comparable fixture the corpus/observation evidence appears complete on the baseline
    # carrier rows (see the complete-delta gate tests for field-level adversarial mismatch).
    del rows


def test_report_member_and_equivalence_evidence_rendered_on_real_run(run):
    """P2-S4: the real report renders per-member threshold/bin/exact evidence + alias equivalence.

    The ``catalog_members_effnet`` table must surface one row per member of every collapsed
    search class carrying the configured==effective threshold (equal to the durable catalog
    ``seg_config``), the ``temporal_global`` bin mode and an exact segmentation hash distinct
    from the class's semantic hash.  The analysis rows must surface the alias-equivalence
    collapse (the 1.0 alias folds under the 0.9 canonical; the 0.2 config is its own singleton).
    """
    report = json.loads((run.output_root / "report" / "report.json").read_text())
    analysis = next(s for s in report["sections"] if s["id"] == "analysis")
    sub = next(s for s in analysis["subsections"] if s["title"] == "effnet")
    members = next(t for t in sub["tables"] if t["id"] == "catalog_members_effnet")
    mrows = [dict(zip(members["columns"], r, strict=False)) for r in members["rows"]]
    # One member row per member of every collapsed class (alias class members 0.9 + 1.0 and
    # the distinct 0.2 singleton -> exactly the three fixture seg_config ids).
    assert {int(m["config_id"]) for m in mrows} == {run.config_id_for(t) for t in ALL_THRESHOLDS}
    for m in mrows:
        cid = int(m["config_id"])
        assert float(m["threshold_configured"]) == pytest.approx(run.threshold_for_config(cid))
        assert m["threshold_configured"] == m["threshold_effective"]
        assert m["bin_mode"] == "temporal_global"
        assert m["exact_segmentation_hash"] not in ("", "—")
        assert m["representation_hash"] != m["exact_segmentation_hash"], (
            "the exact per-config segmentation hash must differ from the class semantic hash"
        )

    # Alias equivalence: rendered analysis rows expose canonical + alias ids per collapsed class.
    distinct_cid = run.config_id_for(DISTINCT_CONFIG_THRESHOLD)
    alias_members = {run.config_id_for(t) for t in ALIAS_CONFIG_THRESHOLDS}
    alias_of = {}
    for r in _report_analysis_rows(report):
        cid = int(r["canonical_config_id"])
        alias_of.setdefault(cid, set()).update(int(a) for a in r["alias_ids"].split(",") if a not in ("", "—"))
    # the two alias thresholds fold under ONE canonical class (representative is either one)
    assert any({k} | aliases == alias_members for k, aliases in alias_of.items()), (
        f"the alias thresholds {sorted(alias_members)} must fold under a single canonical class"
    )
    assert distinct_cid in alias_of and not alias_of[distinct_cid], (
        f"distinct config {distinct_cid} must be its own canonical singleton"
    )


def test_report_semantic_identity_stable_across_rerender_independent_of_disposable_views(run, tmp_path):
    """P2-S3: re-rendering the report over the same durable DB yields stable semantic identity.

    The report is rendered VERBATIM from the persisted analyze scope/metrics (never from any
    disposable view file that may have been regenerated between renders).  Re-rendering the real
    DB into a fresh output directory reproduces byte-for-byte the same durable semantic
    ``representation_hash`` set (equal to the catalog recompute) while the disposable view
    keyset stays in its own column and is never equal to the semantic identity — the report
    compares/identifies rows by durable semantic identity, never by a disposable view identity.
    Combined with the DB+view deletion/reindex re-run byte-stability proof in
    ``test_deterministic_fixture_durability`` this closes the view-regeneration independence
    clause on the real seam.
    """
    from scripts.embedding_research.catalog_identity import collapse_search_representations
    from scripts.embedding_research.report import run as report_run

    analyze_rid = run.evidence.phase_run_id("analyze")
    first = json.loads((run.output_root / "report" / "report.json").read_text())
    first_rows = _report_analysis_rows(first)

    # Re-render the SAME durable DB into a fresh directory (an independent second render).
    second = report_run(run.con, tmp_path / "rerender", run_id=analyze_rid)
    second_rows = _report_analysis_rows(second)
    assert len(second_rows) == len(first_rows)

    with run.open_catalog() as cat:
        durable = {c.search_representation_hash for c in collapse_search_representations(cat)}

    for a, b in zip(first_rows, second_rows, strict=True):
        assert a["strategy_key"] == b["strategy_key"]
        assert a["representation_hash"] == b["representation_hash"], "semantic identity must be stable"
        assert a["representation_hash"] in durable
        assert a["representation_hash"] != a["view_keyset_hash"]
        assert b["representation_hash"] != b["view_keyset_hash"]
