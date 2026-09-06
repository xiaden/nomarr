"""Plan B P1-S1 — spec-first adversarial identity fixtures for the semantic hashes.

These fixtures encode the authoritative preimage contract that P1-S2 implements in
``catalog._song_leaves`` / ``catalog_identity``: the exact/search leaves bind each song to
its immutable provenance digest inputs and ordered scoring rows, so

* (a) search identity CHANGES when song-ID changes, stream payload bytes/digest change,
  aligned mask digest changes, semantics/version changes, the ordered medoid source-index
  list is permuted, normalized weights are permuted, or weight VALUES change;
* (b) search identity is UNCHANGED (class preserved) for exact structural-only changes that
  leave the actual ordered scoring inputs equal (boundaries that do not alter the ordered
  searchable medoid source indices or weights) — while the EXACT identity still changes;
* (c) exact identity changes remain visible when the searchable scoring inputs are
  equivalent;
* (d) fixed tagged ordering, exact SHA-256 determinism (white-box recompute reproduces the
  stored leaf), and NO path-derived identity (identical content at different filesystem
  paths hashes identically).

Assertions use exact deterministic hashes where feasible (leaf recompute == stored leaf,
deterministic repeat equality).  Every mutation changes ONE input at a time.
"""

from __future__ import annotations

import hashlib

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import catalog
from scripts.embedding_research import catalog_identity as ci
from scripts.embedding_research.db._schema import ensure_schema

pytestmark = pytest.mark.unit


# ── Fixture-contract build helpers ─────────────────────────────────────────────


def _mat(blocks: list[int], *, dim: int = 4, seed: float = 1.0, sign: float = 1.0) -> np.ndarray:
    """Deterministic unit song stream: alternating ``+x`` / ``-x`` unit blocks."""
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
        "bin_mode": "temporal_global",
        "threshold_configured": threshold,
        "threshold_effective": threshold,
    }


def _fresh_con():
    """A second independent research connection (schema applied) for cross-catalog builds."""
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    return connection


def _build(
    con,
    out,
    factory,
    *,
    streams: dict | None = None,
    configs: list | None = None,
    song_ids: list[str] | None = None,
    threshold: float = 0.9,
    run_id: str | None = None,
):
    streams = streams if streams is not None else {("s1", "effnet"): _mat([5, 3])}
    configs = configs if configs is not None else [_cfg(threshold)]
    song_ids = song_ids if song_ids is not None else sorted({s for (s, _b) in streams})
    return factory(
        con,
        out,
        streams=streams,
        configs=configs,
        song_ids=song_ids,
        run_id=run_id,
    )


def _config_id(harness) -> int:
    cfgs = catalog.compact_configs_by_backbone(harness.con, "effnet")
    assert cfgs, "expected at least one compact config row"
    return cfgs[0].config_id


def _stored_leaves(harness, cid: int, song: str) -> tuple[str, str]:
    row = harness.con.execute(
        "SELECT exact_leaf, search_leaf FROM catalog_song WHERE config_id = ? AND song_id = ?",
        [cid, song],
    ).fetchone()
    assert row is not None, f"expected catalog_song row for ({cid}, {song})"
    return str(row[0]), str(row[1])


def _recompute(harness, cid: int, song: str) -> tuple[str, str]:
    """White-box: recompute (exact, search) leaves via catalog._song_leaves from the CURRENT
    seg rows + the stored per-song digest/semantics provenance.  Feeds the adversarial
    per-input-axis fixtures cheaply without rebuilding a whole catalog per axis."""
    row = harness.con.execute(
        "SELECT stream_digest, mask_digest, patch_count, total_searchable_count "
        "FROM catalog_song WHERE config_id = ? AND song_id = ?",
        [cid, song],
    ).fetchone()
    assert row is not None, f"expected catalog_song row for ({cid}, {song})"
    stream_digest, mask_digest, patch_count, total = (str(row[0]), str(row[1]), int(row[2]), int(row[3]))
    return catalog._song_leaves(
        harness.con,
        cid,
        song,
        patch_count=patch_count,
        total_searchable=total,
        stream_digest=stream_digest,
        mask_digest=mask_digest,
        mask_semantics_version=catalog._MASK_SEMANTICS_VERSION,
        scoring_semantics_version=int(catalog._SCORING_SEMANTICS_VERSION),
    )


def _two_seg_harness(con, out, factory, *, song_id: str = "s1", threshold: float = 0.9, run_id: str | None = None):
    """Single-song [5,3] catalog -> two clean searchable segments (medoids 0 and 5)."""
    return _build(
        con,
        out,
        factory,
        streams={(song_id, "effnet"): _mat([5, 3])},
        song_ids=[song_id],
        threshold=threshold,
        run_id=run_id,
    )


def _seg_medoid_weights(harness, cid: int, song: str) -> list[tuple[int, float]]:
    rows = harness.con.execute(
        "SELECT seg_id, search_medoid_source_patch_idx, searchable_weight FROM seg_meta "
        "WHERE config_id = ? AND song_id = ? AND search_medoid_source_patch_idx IS NOT NULL "
        "ORDER BY seg_id",
        [cid, song],
    ).fetchall()
    return [(int(r[0]), int(r[1]), float(r[2])) for r in rows]


# ── (d) determinism + exact SHA-256 contract ───────────────────────────────────


def test_leaf_recompute_reproduces_stored_leaf_and_is_deterministic(con, tmp_path, compact_catalog_factory):
    """The exact/search leaf preimage contract is deterministic: a white-box recompute of
    ``catalog._song_leaves`` from the persisted rows reproduces the STORED leaves exactly,
    and repeated recompute is byte-stable."""
    harness = _two_seg_harness(con, tmp_path / "a", compact_catalog_factory)
    try:
        cid = _config_id(harness)
        stored_exact, stored_search = _stored_leaves(harness, cid, "s1")
        recomputed_exact, recomputed_search = _recompute(harness, cid, "s1")
        assert recomputed_exact == stored_exact
        assert recomputed_search == stored_search
        # Deterministic: recomputing again yields the identical 64-hex SHA-256.
        again_exact, again_search = _recompute(harness, cid, "s1")
        assert again_exact == recomputed_exact == stored_exact
        assert again_search == recomputed_search == stored_search
        for leaf in (stored_exact, stored_search):
            assert len(leaf) == 64
            int(leaf, 16)
        # (c) exact and search are distinct hashes for a single config.
        assert ci.exact_segmentation_hash(harness, cid) != ci.search_representation_hash(harness, cid)
    finally:
        harness.close()


def test_no_path_derived_identity(tmp_path, compact_catalog_factory):
    """Identical catalog content published under two different filesystem roots hashes
    identically: no path / output_root is folded into any identity preimage."""
    ha = _two_seg_harness(_fresh_con(), tmp_path / "root-a", compact_catalog_factory, run_id="same-run")
    hb = _two_seg_harness(_fresh_con(), tmp_path / "root-b", compact_catalog_factory, run_id="same-run")
    try:
        assert ha.snapshot_path != hb.snapshot_path  # genuinely different durable locations
        ca, cb = _config_id(ha), _config_id(hb)
        assert ci.search_representation_hash(ha, ca) == ci.search_representation_hash(hb, cb)
        assert ci.exact_segmentation_hash(ha, ca) == ci.exact_segmentation_hash(hb, cb)
        assert ci.song_signature(ha.con, "s1") == ci.song_signature(hb.con, "s1")
        assert _stored_leaves(ha, ca, "s1") == _stored_leaves(hb, cb, "s1")
    finally:
        ha.close()
        hb.close()


# ── (a) song binding ───────────────────────────────────────────────────────────


def test_song_id_change_changes_search_identity(con, tmp_path, compact_catalog_factory):
    """Two songs with byte-identical streams never share a search/exact leaf or config hash:
    per-song leaves are bound to song_id, and a config's hash is bound to its song set."""
    # Config over TWO songs with identical streams -> their leaves/signatures differ per song.
    h_two = _build(
        con,
        tmp_path / "two",
        compact_catalog_factory,
        streams={("s1", "effnet"): _mat([5, 3]), ("s2", "effnet"): _mat([5, 3])},
        song_ids=["s1", "s2"],
        run_id="two-song-run",
    )
    # Config over ONE of those songs -> its search hash differs from the two-song config
    # (cross-corpus ambiguity: a song-set difference must change identity, not sort away).
    h_one = _two_seg_harness(
        _fresh_con(), tmp_path / "one", compact_catalog_factory, song_id="s1", run_id="one-song-run"
    )
    try:
        c_two = _config_id(h_two)
        s1_exact, s1_search = _stored_leaves(h_two, c_two, "s1")
        s2_exact, s2_search = _stored_leaves(h_two, c_two, "s2")
        assert s1_search != s2_search
        assert s1_exact != s2_exact
        assert ci.song_signature(h_two.con, "s1") != ci.song_signature(h_two.con, "s2")
        # Recompute with the OTHER song's id (same rows) changes the leaf -> song_id is bound.
        row = h_two.con.execute(
            "SELECT stream_digest, mask_digest, patch_count, total_searchable_count "
            "FROM catalog_song WHERE config_id = ? AND song_id = 's1'",
            [c_two],
        ).fetchone()
        other = catalog._song_leaves(
            h_two.con,
            c_two,
            "s2",
            patch_count=int(row[2]),
            total_searchable=int(row[3]),
            stream_digest=str(row[0]),
            mask_digest=str(row[1]),
            mask_semantics_version=catalog._MASK_SEMANTICS_VERSION,
            scoring_semantics_version=int(catalog._SCORING_SEMANTICS_VERSION),
        )
        assert other[1] != s1_search

        c_one = _config_id(h_one)
        assert ci.search_representation_hash(h_two, c_two) != ci.search_representation_hash(h_one, c_one)
        assert ci.exact_segmentation_hash(h_two, c_two) != ci.exact_segmentation_hash(h_one, c_one)
    finally:
        h_two.close()
        h_one.close()


# ── (a) immutable stream payload digest ────────────────────────────────────────


def test_identical_structure_different_stream_bytes_never_collapse(con, tmp_path, compact_catalog_factory):
    """Two streams producing IDENTICAL segmentation structure (same medoid source indices +
    weights) but different vector bytes must NOT collapse: the search leaf folds the frozen
    stream digest.  Under the old preimage these configs collapsed -> an end-to-end no-union
    guarantee restored here."""
    mat_a = _mat([5, 3])
    mat_b = -mat_a  # structural mirror: identical cosines/structure, different bytes/digest
    ha = _build(
        con,
        tmp_path / "a",
        compact_catalog_factory,
        streams={("s1", "effnet"): mat_a},
        song_ids=["s1"],
        run_id="bytes-a",
    )
    hb = _build(
        _fresh_con(),
        tmp_path / "b",
        compact_catalog_factory,
        streams={("s1", "effnet"): mat_b},
        song_ids=["s1"],
        run_id="bytes-b",
    )
    try:
        ca, cb = _config_id(ha), _config_id(hb)
        # Prove the actual ordered scoring inputs are identical (only vector bytes differ).
        assert _seg_medoid_weights(ha, ca, "s1") == _seg_medoid_weights(hb, cb, "s1")
        assert (
            ha.con.execute(
                "SELECT stream_digest FROM catalog_song WHERE config_id=? AND song_id='s1'", [ca]
            ).fetchone()[0]
            != hb.con.execute(
                "SELECT stream_digest FROM catalog_song WHERE config_id=? AND song_id='s1'", [cb]
            ).fetchone()[0]
        )
        # Yet the search identities differ -> these configs form two classes, never unioned.
        assert _stored_leaves(ha, ca, "s1")[1] != _stored_leaves(hb, cb, "s1")[1]
        assert ci.search_representation_hash(ha, ca) != ci.search_representation_hash(hb, cb)
        assert ci.exact_segmentation_hash(ha, ca) != ci.exact_segmentation_hash(hb, cb)
        # Collapsing a corpus holding both keeps them distinct.
        classes_a = ci.collapse_search_representations(ha)
        classes_b = ci.collapse_search_representations(hb)
        assert len(classes_a) == 1 and len(classes_b) == 1
        assert classes_a[0].search_representation_hash != classes_b[0].search_representation_hash
    finally:
        ha.close()
        hb.close()


# ── (a) aligned mask digest / semantics / versions (white-box recompute axes) ──


def test_mask_digest_change_changes_search_leaf(con, tmp_path, compact_catalog_factory):
    harness = _two_seg_harness(con, tmp_path, compact_catalog_factory)
    try:
        cid = _config_id(harness)
        baseline_exact, baseline_search = _recompute(harness, cid, "s1")
        row = harness.con.execute(
            "SELECT stream_digest, mask_digest, patch_count, total_searchable_count "
            "FROM catalog_song WHERE config_id=? AND song_id='s1'",
            [cid],
        ).fetchone()
        other_mask_digest = hashlib.sha256(b"a-different-aligned-mask").hexdigest()
        assert other_mask_digest != str(row[1])
        alt = catalog._song_leaves(
            harness.con,
            cid,
            "s1",
            patch_count=int(row[2]),
            total_searchable=int(row[3]),
            stream_digest=str(row[0]),
            mask_digest=other_mask_digest,
            mask_semantics_version=catalog._MASK_SEMANTICS_VERSION,
            scoring_semantics_version=int(catalog._SCORING_SEMANTICS_VERSION),
        )
        assert alt[1] != baseline_search
        assert alt[0] != baseline_exact
        # Live-read robustness: mutating the stored mask digest flips song_signature.
        before_sig = ci.song_signature(harness.con, "s1")
        harness.con.execute(
            "UPDATE catalog_song SET mask_digest = ? WHERE config_id=? AND song_id='s1'",
            [other_mask_digest, cid],
        )
        assert ci.song_signature(harness.con, "s1") != before_sig
    finally:
        harness.close()


def test_semantics_version_changes_change_search_leaf(con, tmp_path, compact_catalog_factory):
    harness = _two_seg_harness(con, tmp_path, compact_catalog_factory)
    try:
        cid = _config_id(harness)
        baseline_exact, baseline_search = _recompute(harness, cid, "s1")
        row = harness.con.execute(
            "SELECT stream_digest, mask_digest, patch_count, total_searchable_count "
            "FROM catalog_song WHERE config_id=? AND song_id='s1'",
            [cid],
        ).fetchone()

        def with_semantics(mask_sem: str, score_sem: int) -> tuple[str, str]:
            return catalog._song_leaves(
                harness.con,
                cid,
                "s1",
                patch_count=int(row[2]),
                total_searchable=int(row[3]),
                stream_digest=str(row[0]),
                mask_digest=str(row[1]),
                mask_semantics_version=mask_sem,
                scoring_semantics_version=score_sem,
            )

        alt_mask_sem = with_semantics("uint8-searchable-ones-v2", int(catalog._SCORING_SEMANTICS_VERSION))
        alt_score_sem = with_semantics(
            str(catalog._MASK_SEMANTICS_VERSION), int(catalog._SCORING_SEMANTICS_VERSION) + 1
        )
        assert alt_mask_sem[1] != baseline_search
        assert alt_mask_sem[0] != baseline_exact
        assert alt_score_sem[1] != baseline_search
        assert alt_score_sem[0] != baseline_exact
    finally:
        harness.close()


# ── (a) ordered medoid source-index permutation / normalized-weight changes ────


def test_medoid_permutation_changes_search_leaf(con, tmp_path, compact_catalog_factory):
    """Permuting the ORDERED medoid source-index list changes the search leaf: search identity
    depends on the ordered sequence, not on an unordered set of medoid patches."""
    harness = _two_seg_harness(con, tmp_path, compact_catalog_factory)
    try:
        cid = _config_id(harness)
        medoids = _seg_medoid_weights(harness, cid, "s1")
        assert len(medoids) == 2, "expected two searchable segments"
        (seg0, src0, _w0), (seg1, src1, _w1) = medoids
        assert src0 != src1
        baseline_exact, baseline_search = _recompute(harness, cid, "s1")
        # Swap ONLY the medoid source indices between the two ordered rows (weights fixed to
        # their seg rows).  The ordered scoring input sequence changes; the medoid SET does not.
        harness.con.execute(
            "UPDATE seg_meta SET search_medoid_source_patch_idx = ? WHERE config_id=? AND song_id='s1' AND seg_id=?",
            [src1, cid, seg0],
        )
        harness.con.execute(
            "UPDATE seg_meta SET search_medoid_source_patch_idx = ? WHERE config_id=? AND song_id='s1' AND seg_id=?",
            [src0, cid, seg1],
        )
        perm_exact, perm_search = _recompute(harness, cid, "s1")
        assert perm_search != baseline_search
        assert perm_exact != baseline_exact
    finally:
        harness.close()


def test_weight_permutation_changes_search_leaf(con, tmp_path, compact_catalog_factory):
    """Permuting the normalized weights between ordered medoid rows changes the search leaf."""
    harness = _two_seg_harness(con, tmp_path, compact_catalog_factory)
    try:
        cid = _config_id(harness)
        medoids = _seg_medoid_weights(harness, cid, "s1")
        (seg0, _src0, w0), (seg1, _src1, w1) = medoids
        baseline_exact, baseline_search = _recompute(harness, cid, "s1")
        harness.con.execute(
            "UPDATE seg_meta SET searchable_weight = ? WHERE config_id=? AND song_id='s1' AND seg_id=?",
            [w1, cid, seg0],
        )
        harness.con.execute(
            "UPDATE seg_meta SET searchable_weight = ? WHERE config_id=? AND song_id='s1' AND seg_id=?",
            [w0, cid, seg1],
        )
        perm_exact, perm_search = _recompute(harness, cid, "s1")
        assert perm_search != baseline_search
        assert perm_exact != baseline_exact
    finally:
        harness.close()


def test_weight_value_change_changes_search_leaf(con, tmp_path, compact_catalog_factory):
    """A change in a normalized weight VALUE (ordered rows otherwise equal) changes the leaf."""
    harness = _two_seg_harness(con, tmp_path, compact_catalog_factory)
    try:
        cid = _config_id(harness)
        baseline_exact, baseline_search = _recompute(harness, cid, "s1")
        harness.con.execute(
            "UPDATE seg_meta SET searchable_weight = 0.5 WHERE config_id=? AND song_id='s1' AND seg_id=0",
            [cid],
        )
        alt_exact, alt_search = _recompute(harness, cid, "s1")
        assert alt_search != baseline_search
        assert alt_exact != baseline_exact
    finally:
        harness.close()


# ── (b)/(c) structural-only changes preserve the search class but move exact ───


def test_structural_only_change_keeps_search_leaf_changes_exact_leaf(con, tmp_path, compact_catalog_factory):
    """A structural-only change (moving a segment boundary) that leaves the ordered medoid
    source indices + normalized weights equal must NOT split a search class — the search leaf
    is unchanged — while the EXACT leaf still changes (structural evidence is exact-only)."""
    harness = _two_seg_harness(con, tmp_path, compact_catalog_factory)
    try:
        cid = _config_id(harness)
        baseline_exact, baseline_search = _recompute(harness, cid, "s1")
        assert ci.search_representation_hash(harness, cid) == ci.search_representation_hash(harness, cid)
        # Shift the boundary between the two segments (seg0.end_idx and seg1.start_idx both
        # move) WITHOUT touching the persisted medoid source index or normalized weight of
        # either row — the ordered scoring inputs are unchanged.
        harness.con.execute(
            "UPDATE seg_meta SET end_idx = end_idx + 1 WHERE config_id=? AND song_id='s1' AND seg_id=0",
            [cid],
        )
        harness.con.execute(
            "UPDATE seg_meta SET start_idx = start_idx + 1 WHERE config_id=? AND song_id='s1' AND seg_id=1",
            [cid],
        )
        assert _seg_medoid_weights(harness, cid, "s1") == [(0, 0, 5 / 8), (1, 5, 3 / 8)]
        struct_exact, struct_search = _recompute(harness, cid, "s1")
        # (b) search identity preserved across the structural-only change.
        assert struct_search == baseline_search
        # (c) exact identity changes remain visible when the searchable scoring inputs match.
        assert struct_exact != baseline_exact
    finally:
        harness.close()


# ── (d) fixed song-order set semantics ─────────────────────────────────────────


def test_song_order_permutation_of_set_is_hash_invariant(con, tmp_path, compact_catalog_factory):
    """A catalog's search/exact config hash serializes per-song leaves in FIXED song order, so
    permuting the PHYSICAL song order of a config (the song SET unchanged) is identity-stable."""
    mat = _mat([5, 3])
    ha = _build(
        con,
        tmp_path / "ab",
        compact_catalog_factory,
        streams={("s1", "effnet"): mat, ("s2", "effnet"): mat},
        song_ids=["s1", "s2"],
        run_id="order-ab",
    )
    hb = _build(
        _fresh_con(),
        tmp_path / "ba",
        compact_catalog_factory,
        streams={("s1", "effnet"): mat, ("s2", "effnet"): mat},
        song_ids=["s2", "s1"],  # physically reversed build order; same set
        run_id="order-ba",
    )
    try:
        ca, cb = _config_id(ha), _config_id(hb)
        assert ci.search_representation_hash(ha, ca) == ci.search_representation_hash(hb, cb)
        assert ci.exact_segmentation_hash(ha, ca) == ci.exact_segmentation_hash(hb, cb)
        assert len(ci.collapse_search_representations(ha)) == 1
        assert len(ci.collapse_search_representations(hb)) == 1
        assert ci.collapse_search_representations(ha) == ci.collapse_search_representations(hb)
    finally:
        ha.close()
        hb.close()
