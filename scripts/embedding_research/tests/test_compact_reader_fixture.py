"""Compact read-helper + shared fixture-contract smoke tests (Plan C, P1-S6(a)).

These are GREEN by design (the bounded research red set stays exactly the documented
63-test category-(b)/(c) baseline; this file adds zero new reds).  They exercise the two
additive P1-S6(a) foundations:

* the ``compact_*`` read helpers in ``catalog.py`` that read ``seg_config`` /
  ``catalog_song`` / ``seg_meta`` from a COMPACT snapshot connection (typically
  ``CatalogHandle.con``) via the ``catalog_storage`` column tuples with canonical-only
  config semantics (no ``alias_of_config_id``); and
* the shared category-(b)/(c) fixture contract (``conftest.build_compact_catalog`` via the
  ``compact_catalog_factory`` fixture): publish streams via ``StreamStore`` + reconcile on
  a research ``con``, build the compact catalog through the P1-S5 producer, and open the
  snapshot once through ``catalog_storage.open_snapshot_file`` -> ``CatalogHandle``.

Every build here is self-contained: real store publication on a research ``con``, fake
numpy streams/masks, no audio/model/ONNX/CUDA.
"""

from __future__ import annotations

import numpy as np

from scripts.embedding_research import catalog
from scripts.embedding_research.catalog_storage import open_snapshot_file
from scripts.embedding_research.helpers.segmentation import reconstruct_searchable_indices


def _song_mat(blocks: list[int], *, dim: int = 4, seed: float = 1.0) -> np.ndarray:
    """Deterministic song stream: alternating ``+x`` / ``-x`` unit blocks."""
    sign = 1.0
    rows: list[np.ndarray] = []
    for count in blocks:
        block = np.zeros((count, dim), dtype=np.float32)
        block[:, 0] = sign
        block *= seed
        rows.append(block)
        sign *= -1.0
    return np.concatenate(rows, axis=0)


def _cfg(threshold: float) -> dict:
    return {
        "backbone": "effnet",
        "bin_mode": "direct",
        "threshold_configured": threshold,
        "threshold_effective": threshold,
    }


def test_compact_read_helpers_read_back_built_snapshot(con, tmp_path, compact_catalog_factory):
    """Build one compact catalog via the fixture contract and read it back through the helpers."""
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _song_mat([5, 3])},
        configs=[_cfg(1.0), _cfg(0.9)],
        song_ids=["s1"],
        run_id="smoke-a",
    )
    try:
        assert harness.report.verify_ok is True
        # The snapshot was opened once through open_snapshot_file -> CatalogHandle.
        assert harness.snapshot_path.is_file()
        assert harness.handle.con is harness.con

        # (1) compact config reads: canonical-only rows, no alias_of_config_id.
        cfgs = catalog.compact_configs_by_backbone(harness.con, "effnet")
        assert len(cfgs) == 2
        assert sorted(c.config_id for c in cfgs) == [1, 2]
        for c in cfgs:
            assert c.backbone == "effnet"
            assert c.bin_mode == "direct"
            assert c.threshold_configured == c.threshold_effective
            assert c.canonical_config_hash
            assert not hasattr(c, "alias_of_config_id")  # canonical-only config semantics
        # config_id is assigned deterministically from sorted canonical hashes (1..n), NOT
        # from request order; both requested thresholds are present with distinct identities.
        assert {c.threshold_effective for c in cfgs} == {0.9, 1.0}
        assert catalog.compact_config_by_id(harness.con, 1) is not None
        assert catalog.compact_config_by_id(harness.con, 999) is None

        # (2) compact seg reads: structural + searchable fields with parsed absorbed indices.
        config_id = next(c.config_id for c in cfgs if c.threshold_effective == 1.0)
        segs = catalog.compact_segments_by_config_song(harness.con, config_id, "s1")
        assert len(segs) == 2  # alternating +x/-x blocks hard-split at threshold 1.0
        for s in segs:
            assert s.start_idx < s.end_idx
            assert s.song_id == "s1"
            assert s.searchable_count >= 1
            assert s.search_medoid_source_patch_idx is not None
            assert isinstance(s.absorbed_indices, tuple)
            assert s.absorbed_count == len(s.absorbed_indices)

        # (3) compact catalog_song reads: the durable per-(config, song) leaf.
        leaves = catalog.compact_catalog_songs_by_config(harness.con, config_id)
        assert len(leaves) == 1
        leaf = catalog.compact_catalog_song(harness.con, config_id, "s1")
        assert leaf is not None and leaf.song_id == "s1" and leaf.status == "searchable"
        assert leaves[0].stream_digest and leaves[0].exact_leaf and leaves[0].search_leaf
    finally:
        harness.close()


def test_compact_seg_rows_reconstruct_to_catalog_total(con, tmp_path, compact_catalog_factory):
    """Reconstructing searchable indices from CompactSegRecord rows matches catalog_song totals."""
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _song_mat([5, 3]), ("s2", "effnet"): _song_mat([4, 4])},
        configs=[_cfg(1.0)],
        song_ids=["s1", "s2"],
        run_id="smoke-b",
    )
    try:
        cfgs = catalog.compact_configs_by_backbone(harness.con, "effnet")
        assert len(cfgs) == 1
        config_id = cfgs[0].config_id
        for song in ("s1", "s2"):
            leaf = catalog.compact_catalog_song(harness.con, config_id, song)
            segs = catalog.compact_segments_by_config_song(harness.con, config_id, song)
            # No committed research masks => mask=None (whole structural range searchable).
            reconstructed = sum(int(reconstruct_searchable_indices(seg, None, leaf.patch_count).size) for seg in segs)
            assert reconstructed == leaf.total_searchable_count
    finally:
        harness.close()


def test_fixture_contract_holds_one_live_handle_per_snapshot(con, tmp_path, compact_catalog_factory):
    """The fixture holds ONE live handle; reopen only after close (DuckDB single-writer).

    DuckDB permits only one connection to a database file per process at a time, so a
    snapshot may hold exactly one live handle unless the prior handle is closed.  This
    validates the documented contract and the close/reopen lifecycle an export/import
    round-trip test needs (close the fixture handle before reopening a copy).
    """
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _song_mat([6])},
        configs=[_cfg(1.0)],
        song_ids=["s1"],
        run_id="smoke-c",
    )
    # The fixture holds exactly one live handle to the snapshot.
    assert harness.handle.con is harness.con
    assert catalog.compact_configs_by_backbone(harness.con, "effnet")
    # Close the fixture handle, then a fresh read-only handle may open the same snapshot.
    harness.close()
    second = open_snapshot_file(harness.snapshot_path, read_only=True)
    try:
        assert second.con is not harness.con
        assert catalog.compact_configs_by_backbone(second.con, "effnet")
    finally:
        second.close()
