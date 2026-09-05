"""Plan C P1-S2 — spec-first catalog scale + weight semantics.

Pins the corrective-pass weight/medoid/build-report contracts alongside a
self-contained DuckDB durability/scale guard for the ~10M-row compact catalog.

Weight/medoid semantics (§C + DD "Membership, segmentation, medoids and weights"):
``weight_g = searchable_count_g / total_searchable_song``; empty searchable segment
stays structural with a null medoid and zero weight; a zero-searchable song is
metadata-only (no search candidate); the medoid is the OBSERVED source patch with
maximal mean-cosine centrality (smallest source index on an exact tie) among finite
nonzero searchable patches, and absorbed + silent patches are excluded globally and
from the head-shared membership.

Two helpers supply the membership/medoid computations and are pinned to
``helpers/segmentation.py`` (see the P1-S1 file and the API-HOME annotations):
``reconstruct_searchable_indices`` and ``select_observed_medoid_source_index``.
They do not exist at head, so the semantic tests here fail with
``NotImplementedError`` (spec-first red) until P1-S4 implements them.

Build-level one-stream-load-per-(song, backbone) contract and the scale guard:
* the ``test_build_records_one_stream_load_per_song_backbone_pass`` test drives the
  corrective ``build_segmentation_catalog(stream_store, mask_store, configs,
  song_ids, output_root, run_id, *, verify)`` §C signature; the current (per-patch,
  pre-compact) build takes a different signature, so this test is RED now via a
  ``TypeError`` and goes green when P1-S4 lands the §C compact build;
* ``test_compact_catalog_reaches_ten_million_seg_meta_rows`` is self-contained and
  GREEN by design: it builds the intended compact tables (no per-patch membership
  table) in a temp DuckDB, loads ~10M ``seg_meta`` + 100k ``catalog_song`` rows
  SQL-side (fast, memory-light), pins the exact §C column set for P1-S3, and
  re-derives searchable membership from the stored structural rows + sparse
  absorbed sets — proving the ~10M compact shape is feasible without per-patch rows.

All tests are synthetic numpy/DuckDB only: no audio, no model, no corpus.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.helpers import segmentation as seg_mod

#: Intended compact table set — a durable catalog with NO per-patch membership table.
COMPACT_TABLES = ("catalog_metadata", "seg_config", "catalog_song", "seg_meta", "run_provenance")

#: Intended compact column sets (recorded for P1-S3).  No per-patch rows, no copied
#: threshold vectors, no new PK/UNIQUE constraints.
SEG_CONFIG_COLS = (
    "config_id",
    "backbone",
    "bin_mode",
    "threshold_configured",
    "threshold_effective",
    "threshold_semantics",
    "outlier_window",
    "strategy_version",
    "canonical_config_hash",
    "run_id",
)
CATALOG_SONG_COLS = (
    "config_id",
    "song_id",
    "stream_digest",
    "mask_digest",
    "patch_count",
    "total_searchable_count",
    "exact_leaf",
    "search_leaf",
    "encoder_version",
    "params_id",
    "status",
)
SEG_META_COLS = (
    "config_id",
    "song_id",
    "seg_id",
    "start_idx",
    "end_idx",
    "absorbed_indices",
    "absorbed_count",
    "searchable_count",
    "search_medoid_source_patch_idx",
    "searchable_weight",
    "structural_identity",
    "provenance",
)


def _future(name: str):
    """Return a not-yet-implemented §C helper or raise NotImplementedError (spec-first red)."""
    fn = getattr(seg_mod, name, None)
    if fn is None:
        raise NotImplementedError(f"P1-S4 must implement {name} in scripts.embedding_research.helpers.segmentation")
    return fn


def _reconstruct(meta, mask: np.ndarray, patch_count: int) -> np.ndarray:
    return _future("reconstruct_searchable_indices")(meta, mask, patch_count)


def _select(unit_patches: np.ndarray, source_indices) -> tuple:
    return _future("select_observed_medoid_source_index")(unit_patches, source_indices)


def _mask(patch_count: int, *, silent: tuple[int, ...] = ()) -> np.ndarray:
    mask = np.ones(patch_count, dtype=np.uint8)
    for idx in silent:
        mask[idx] = 0
    return mask


def _meta(start: int, end: int, absorbed: tuple[int, ...] = ()) -> object:
    return type("_Meta", (), {"start_idx": start, "end_idx": end, "absorbed_indices": absorbed})


def _unit_rows(angles_deg) -> np.ndarray:
    """2-D unit rows from angles in degrees."""
    rad = np.deg2rad(np.asarray(angles_deg, dtype=np.float64))
    return np.column_stack([np.cos(rad), np.sin(rad)]).astype(np.float32)


def _ref_medoid(unit_patches: np.ndarray, source_indices) -> tuple:
    """Independent reference: max mean-cosine (incl. self) over the candidate rows.

    ``np.argmax`` returns the first maximum, i.e. the smallest candidate SOURCE index on
    an exact centrality tie (candidate source indices are taken in sorted order).
    """
    ordered = sorted(source_indices)
    sub = unit_patches[np.asarray(ordered, dtype=int)]
    sims = sub @ sub.T  # rows are unit vectors, so dot product == cosine
    means = sims.mean(axis=1)
    best = int(np.argmax(means))
    return ordered[best], float(means[best])


# --------------------------------------------------------------------------- #
# Medoid centrality & tie (observed source)                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_observed_medoid_centrality_wins_over_smallest_source_index():
    """The maximal mean-cosine-centrality source wins — not simply the smallest index."""
    rows = _unit_rows([0.0, 90.0, 180.0])  # index 1 is the most central
    idx, centrality = _select(rows, (0, 1, 2))
    assert idx == 1
    assert centrality == pytest.approx(1.0 / 3.0)


@pytest.mark.unit
def test_observed_medoid_exact_tie_picks_smallest_source_index():
    """On an exact centrality tie the smallest SOURCE index is returned.

    Source index 1 must win over 2 even though index 0 (also tied in shape) is unused.
    """
    rows = _unit_rows([180.0, 0.0, 90.0])  # rows 1 and 2 are orthonormal => equal centrality
    idx, centrality = _select(rows, (1, 2))
    assert idx == 1  # smallest source index among the tied candidates
    assert centrality == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Global / head-shared membership: silent + absorbed excluded                    #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_global_medoid_excludes_silent_and_absorbed_patches():
    """Global medoid is selected only over non-silent searchable patches.

    Two structural segments with one absorbed (idx 1) and one silent (idx 5) patch; the
    returned global medoid must come from {0, 2, 3, 4} and equal the independent
    reference over exactly that reconstructed non-silent set.
    """
    rows = _unit_rows([0.0, 0.0, 170.0, 80.0, 100.0, 0.0])  # idx5 intentionally central+silent
    mask = _mask(6, silent=(5,))
    seg_a = _meta(0, 3, (1,))
    seg_b = _meta(3, 6)
    union = sorted(int(i) for i in np.concatenate([_reconstruct(seg_a, mask, 6), _reconstruct(seg_b, mask, 6)]))
    assert union == [0, 2, 3, 4]
    idx, centrality = _select(rows, tuple(union))
    ref_idx, ref_centrality = _ref_medoid(rows, tuple(union))
    assert idx == ref_idx
    assert idx not in (1, 5)  # never an absorbed or silent patch
    assert centrality == pytest.approx(ref_centrality)


@pytest.mark.unit
def test_head_membership_is_exactly_the_reconstructed_searchable_set():
    """Heads pool the exact reconstructed M_g (never the inclusive structural range).

    The membership handed to head pooling must equal structural-minus-absorbed-minus-
    silent, and the medoid source index is an observed patch within that membership.
    """
    rows = _unit_rows([0.0, 0.0, 90.0, 180.0, 180.0])
    mask = _mask(5, silent=(4,))
    seg = _meta(0, 5, (1,))  # absorbed idx 1, silent idx 4
    membership = sorted(int(i) for i in _reconstruct(seg, mask, 5))
    assert membership == [0, 2, 3]  # absorbed 1 + silent 4 excluded
    idx, _ = _select(rows, tuple(membership))
    assert idx in membership  # observed source within the head-shared membership


# --------------------------------------------------------------------------- #
# Weights: weight_g = searchable_count_g / total_searchable_song                 #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_weights_eighty_silent_fifteen_and_five_searchable():
    """DD .75/.25 example: 80 silent, 15 A searchable, 5 B searchable => weights .75, .25."""
    patch_count = 100
    silent = tuple(range(45)) + tuple(range(60, 95))  # 45 + 35 = 80 silent
    mask = _mask(patch_count, silent=silent)
    seg_a = _meta(0, 60)  # non-silent = indices 45..59  => 15 searchable
    seg_b = _meta(60, 100)  # non-silent = indices 95..99 => 5 searchable
    count_a = int(_reconstruct(seg_a, mask, patch_count).size)
    count_b = int(_reconstruct(seg_b, mask, patch_count).size)
    total = count_a + count_b
    assert (count_a, count_b) == (15, 5)
    assert total == 20
    weight_a = count_a / total
    weight_b = count_b / total
    assert weight_a == pytest.approx(0.75)
    assert weight_b == pytest.approx(0.25)
    assert weight_a + weight_b == pytest.approx(1.0)


@pytest.mark.unit
def test_empty_searchable_segment_is_structural_with_null_medoid_and_zero_weight():
    """An empty M_g keeps the segment structural: null medoid and zero weight."""
    patch_count = 10
    mask = _mask(patch_count, silent=tuple(range(6)))  # entire segment A silent
    seg_a = _meta(0, 6)
    seg_b = _meta(6, 10)
    count_a = int(_reconstruct(seg_a, mask, patch_count).size)
    count_b = int(_reconstruct(seg_b, mask, patch_count).size)
    assert count_a == 0
    assert count_b == 4
    total = count_a + count_b
    weight_a = 0 if total == 0 else count_a / total
    assert weight_a == 0
    # No finite nonzero searchable patch in the empty segment => null medoid.
    idx, centrality = _select(np.zeros((6, 2), dtype=np.float32), ())
    assert idx is None and centrality is None


@pytest.mark.unit
def test_zero_searchable_song_is_metadata_only_no_search_candidate():
    """A song whose patches are all silent yields no searchable mass or medoid."""
    patch_count = 5
    mask = _mask(patch_count, silent=(0, 1, 2, 3, 4))
    seg = _meta(0, 5)
    total = int(_reconstruct(seg, mask, patch_count).size)
    assert total == 0
    idx, centrality = _select(np.zeros((5, 2), dtype=np.float32), ())
    assert idx is None and centrality is None


# --------------------------------------------------------------------------- #
# Build-level one-stream-load-per-(song, backbone) contract (RED until P1-S4)    #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_build_records_one_stream_load_per_song_backbone_pass():
    """The §C compact build performs exactly ONE stream load per (song, backbone).

    RED now: the current per-patch build takes ``(con, stream_store, configs, song_ids,
    run_id, *, verify)`` and has no ``mask_store``/``output_root``, so invoking the §C
    signature raises ``TypeError`` until P1-S4 rebuilds it.  When green, the returned
    ``CatalogBuildReport`` must record exactly one load per (song, backbone) in
    ``load_evidence`` and ``stream_loads``.

    The fake read protocol is deliberately minimal (one method per surface) and is the
    contract P1-S4's build must satisfy: a single load call per (song, backbone) pass.
    """

    class _FakeMask:
        def load(self, _song_id: str) -> np.ndarray:
            return np.ones(8, dtype=np.uint8)

    class _FakeStream:
        def __init__(self) -> None:
            self.loads: list[tuple[str, str]] = []

        def load(self, song_id: str, backbone: str) -> np.ndarray:
            self.loads.append((song_id, backbone))
            # 8 unit patches along +x — enough for a single contiguous structural segment.
            return np.ones((8, 2), dtype=np.float32) * (1.0, 0.0)

    # Imported lazily: catalog currently triggers head-classifier discovery on import.
    from scripts.embedding_research import catalog

    stream_store = _FakeStream()
    mask_store = _FakeMask()
    configs = [
        {
            "backbone": "synthetic",
            "bin_mode": "direct",
            "threshold_configured": 1.0,
            "threshold_effective": 1.0,
        }
    ]
    report = catalog.build_segmentation_catalog(
        stream_store=stream_store,
        mask_store=mask_store,
        configs=configs,
        song_ids=["s0001", "s0002"],
        output_root=None,
        run_id="run-one-load",
        verify=True,
    )
    # §C evidence: exactly one load per (song, backbone), all recorded.
    expected_pairs = {("s0001", "synthetic"), ("s0002", "synthetic")}
    evidence = dict(report.load_evidence)
    assert set(evidence) == expected_pairs
    assert all(count == 1 for count in evidence.values())
    assert report.stream_loads == len(expected_pairs)


# --------------------------------------------------------------------------- #
# Compact ~10M-row durability + DDL-shape guard (self-contained, GREEN by design) #
# --------------------------------------------------------------------------- #


def _table_columns(con, table: str) -> set[str]:
    rows = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]).fetchall()
    return {r[0] for r in rows}


@pytest.mark.unit
@pytest.mark.scale
@pytest.mark.local_filesystem
def test_compact_catalog_reaches_ten_million_seg_meta_rows(tmp_path):
    """The intended compact shape reaches ~10M seg_meta rows without per-patch rows.

    Self-contained and green now: it creates the §C tables (the exact column sets P1-S3
    must implement), fills 10M seg_meta + 100k catalog_song rows SQL-side, asserts the
    column sets and the ABSENCE of any ``seg_membership`` table, and re-derives
    searchable membership from stored structural rows + sparse absorbed sets — no
    per-patch membership storage required.
    """
    db_path = tmp_path / "compact_scale.duckdb"
    con = duckdb.connect(str(db_path))

    con.execute(
        "CREATE TABLE seg_config ("
        "config_id INT, backbone VARCHAR, bin_mode VARCHAR, threshold_configured DOUBLE,"
        " threshold_effective DOUBLE, threshold_semantics VARCHAR, outlier_window INT,"
        " strategy_version INT, canonical_config_hash VARCHAR, run_id VARCHAR)"
    )
    con.execute(
        "CREATE TABLE catalog_song ("
        "config_id INT, song_id VARCHAR, stream_digest VARCHAR, mask_digest VARCHAR,"
        " patch_count INT, total_searchable_count INT, exact_leaf VARCHAR,"
        " search_leaf VARCHAR, encoder_version VARCHAR, params_id VARCHAR, status VARCHAR)"
    )
    con.execute(
        "CREATE TABLE seg_meta ("
        "config_id INT, song_id VARCHAR, seg_id INT, start_idx INT, end_idx INT,"
        " absorbed_indices VARCHAR, absorbed_count INT, searchable_count INT,"
        " search_medoid_source_patch_idx INT, searchable_weight DOUBLE,"
        " structural_identity VARCHAR, provenance VARCHAR)"
    )
    con.execute("CREATE TABLE catalog_metadata (format VARCHAR, created_at_ms BIGINT)")
    con.execute("CREATE TABLE run_provenance (run_id VARCHAR, status VARCHAR, started_ms BIGINT)")

    # --- Pin the exact §C column sets so P1-S3 builds to this shape. ---
    assert _table_columns(con, "seg_config") == set(SEG_CONFIG_COLS)
    assert _table_columns(con, "catalog_song") == set(CATALOG_SONG_COLS)
    assert _table_columns(con, "seg_meta") == set(SEG_META_COLS)

    # --- No per-patch membership table may exist anywhere in the compact schema. ---
    present = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert "seg_membership" not in present

    # --- Load 10k songs x 10 configs = 100k catalog_song rows. ---
    con.execute(
        "CREATE TABLE song_ids AS SELECT 's'||lpad(CAST(r AS VARCHAR), 5, '0') AS song_id FROM range(10000) t(r)"
    )
    con.execute(
        "INSERT INTO catalog_song (config_id, song_id, stream_digest, mask_digest, patch_count,"
        " total_searchable_count, exact_leaf, search_leaf, encoder_version, params_id, status)"
        " SELECT c, song_id, 'sd'||CAST(c AS VARCHAR), 'md', 1200, 1200, 'x', 's', 'v1', 'p', 'ok'"
        " FROM (SELECT * FROM range(10) t(c)) cfg CROSS JOIN song_ids"
    )
    # --- Load 10M seg_meta rows: 10 configs x 10k songs x 100 segs. ---
    con.execute(
        "INSERT INTO seg_meta (config_id, song_id, seg_id, start_idx, end_idx, absorbed_indices,"
        " absorbed_count, searchable_count, search_medoid_source_patch_idx, searchable_weight,"
        " structural_identity, provenance)"
        " SELECT c, s.song_id, sg, sg * 12, sg * 12 + 12, '[]', 0, 12, sg * 12 + 5, 1.0, 'id', 'p'"
        " FROM (SELECT * FROM range(10) t(c)) cfg"
        " CROSS JOIN song_ids s"
        " CROSS JOIN (SELECT * FROM range(100) t(sg)) seg"
    )

    assert con.execute("SELECT count(*) FROM catalog_song").fetchone()[0] == 100_000
    assert con.execute("SELECT count(*) FROM seg_meta").fetchone()[0] == 10_000_000

    # --- Reconstruction spot-check: membership is derivable from structural rows +    ---
    # --- sparse absorbed sets (all ones mask here), with NO per-patch storage needed. ---
    for song_id in ("s00000", "s05000", "s09999"):
        rows = con.execute(
            "SELECT seg_id, start_idx, end_idx, absorbed_count, searchable_count"
            " FROM seg_meta WHERE song_id = ? AND config_id = 0 ORDER BY seg_id",
            [song_id],
        ).fetchall()
        assert len(rows) == 100
        derived_total = 0
        for _, start, end, absorbed_count, searchable_count in rows:
            # membership count = structural width minus absorbed exceptions (mask all ones)
            assert end - start == 12
            assert absorbed_count == 0
            assert searchable_count == end - start
            derived_total += searchable_count
        assert derived_total == 1200
        # catalog_song.total_searchable_count must agree with the reconstructed sum.
        stored_total = con.execute(
            "SELECT total_searchable_count FROM catalog_song WHERE song_id = ? AND config_id = 0",
            [song_id],
        ).fetchone()[0]
        assert stored_total == derived_total

    con.close()
