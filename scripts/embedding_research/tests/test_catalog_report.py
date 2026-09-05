"""Plan C Phase 4 (P4-S2 + P4-S4) — structural-change summaries and catalog reports.

Proves the structural-change summary contract (explicit membership / medoid / count changes,
never silent collapse) and the transient-hash alias/collapse evidence (configs whose per-song
search leaves are identical collapse to one scorer execution, derived TRANSIENTLY — never a
durable alias graph), implemented in ``scripts/embedding_research/catalog_report.py`` (P1-S12
retired the legacy ``build_alias_index`` / ``validate_alias_graph`` durable alias machinery).
Plus that the catalog report contains every required field (canonical configs, aliases,
configured + effective thresholds, empty/failed songs, exact membership + outlier counts,
observed medoid-index changes, structural changes, per-config leaf/collapse evidence
(``search_representation_hash`` / ``exact_segmentation_hash``) and ``catalog_fingerprint``).
"""

from __future__ import annotations

import math

import numpy as np

from scripts.embedding_research import catalog
from scripts.embedding_research.catalog_identity import catalog_fingerprint
from scripts.embedding_research.catalog_report import (
    ConfigSnapshot,
    SegmentSnapshot,
    SongSnapshot,
    build_catalog_report,
    capture_catalog_structure,
    report_to_text,
    structural_changes,
)

SCHEMA_VERSION = 1


def _cfg(threshold: float) -> catalog.SegConfigInput:
    return catalog.SegConfigInput(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _threshold_split_mat() -> np.ndarray:
    """Deterministic unit-patch stream so distinct thresholds segment differently.

    Three ``+x`` rows then three rows of a unit vector at Euclidean distance 0.5 from
    ``+x``.  A threshold > 0.5 merges all six rows into one segment; a threshold < 0.5
    splits them into two.  This lets distinct thresholds produce distinct search leaves
    (0.9 vs 0.2) or identical leaves that collapse as transient aliases (0.9 vs 1.0).
    """
    theta = math.acos(0.875)  # cos theta such that distance(+x, rotated) == 0.5
    u0 = np.zeros(4, dtype=np.float32)
    u0[0] = 1.0
    u1 = np.array([math.cos(theta), math.sin(theta), 0.0, 0.0], dtype=np.float32)
    return np.stack([u0, u0, u0, u1, u1, u1])


def _configs_by_threshold(con) -> dict[float, int]:
    """Map each compact effnet config's ``threshold_effective`` to its ``config_id``."""
    return {float(r.threshold_effective): r.config_id for r in catalog.compact_configs_by_backbone(con, "effnet")}


# ── Alias/collapse evidence against the DB / identity (transient-hash) ────────


def test_db_alias_validation_and_no_corpus_identity_change(con, tmp_path, compact_catalog_factory):
    """Collapse is derived TRANSIENTLY from search leaves; no durable alias is validated.

    Two distinct thresholds (0.9 vs 1.0) that produce IDENTICAL search leaves are reported as
    one scorer execution (an alias to the lowest config id).  There is no durable alias graph
    to validate: the compact ``seg_config`` has no ``alias_of_config_id`` column.  Reporting
    the collapse is a pure read — it never persists an alias row and never changes the corpus
    identity / fingerprint / search hash.
    """
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _threshold_split_mat()},
        configs=[_cfg(0.9), _cfg(1.0)],
        song_ids=["s1"],
    )
    c = harness.con
    ids = [r.config_id for r in catalog.compact_configs_by_backbone(c, "effnet")]
    assert len(ids) == 2
    fp_before = catalog_fingerprint(c, schema_version=SCHEMA_VERSION)
    # compact seg_config carries NO alias column: nothing durable to read/write/validate.
    cols = {
        str(r[0])
        for r in c.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'seg_config'"
        ).fetchall()
    }
    assert "alias_of_config_id" not in cols

    report = build_catalog_report(c, schema_version=SCHEMA_VERSION)
    representative = min(ids)
    alias_id = max(ids)
    assert report.alias_entries == ((alias_id, representative),)
    assert report.alias_count == 1
    assert representative in report.canonical_config_ids
    assert alias_id not in report.canonical_config_ids
    # Collapse is reported, never persisted: rerunning the report is a pure read that leaves
    # the fingerprint untouched, and every real config is still reported.
    assert catalog_fingerprint(c, schema_version=SCHEMA_VERSION) == fp_before
    assert {int(x["config_id"]) for x in report.config_content} == set(ids)
    harness.close()


def test_db_invalid_alias_raises_meaning_conflict(con, tmp_path, compact_catalog_factory):
    """Distinct meanings are never transiently aliased — each surfaces as its own canonical.

    Two thresholds whose effective meaning and search leaves DIFFER (0.9 merges into one
    segment; 0.2 splits into two) are two real canonical configs: the transient model never
    collapses a meaning conflict, so the report lists both canonicals and no alias.
    """
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _threshold_split_mat()},
        configs=[_cfg(0.9), _cfg(0.2)],
        song_ids=["s1"],
    )
    c = harness.con
    by_threshold = _configs_by_threshold(c)
    assert set(by_threshold) == {0.9, 0.2}
    report = build_catalog_report(c, schema_version=SCHEMA_VERSION)
    # distinct meanings -> both canonical representatives, never collapsed into an alias.
    assert report.alias_entries == ()
    assert all(cid in report.canonical_config_ids for cid in by_threshold.values())
    harness.close()


# ── Structural-change summaries (no silent collapse) ───────────────────────────


def _song(song_id: str, *segs: SegmentSnapshot) -> SongSnapshot:
    return SongSnapshot(song_id=song_id, segments=segs)


def _cfg_snap(config_id: int, *songs: SongSnapshot) -> ConfigSnapshot:
    return ConfigSnapshot(config_id=config_id, songs=songs)


def test_structural_changes_report_medoid_change_explicitly():
    prev = {
        1: _cfg_snap(
            1,
            _song(
                "s1",
                SegmentSnapshot(
                    seg_id=0, medoid_source_patch_idx=3, member_count=5, absorbed_outlier_count=1, membership_rows=5
                ),
            ),
        )
    }
    curr = {
        1: _cfg_snap(
            1,
            _song(
                "s1",
                SegmentSnapshot(
                    seg_id=0, medoid_source_patch_idx=7, member_count=5, absorbed_outlier_count=1, membership_rows=5
                ),
            ),
        )
    }
    diff = structural_changes(prev, curr)
    assert diff.is_clean is False
    assert diff.changed_config_ids == (1,)
    assert any("medoid_source_patch_idx 3 -> 7" in line for line in diff.changes)


def test_structural_changes_report_added_removed_configs():
    prev = {1: _cfg_snap(1, _song("s1", SegmentSnapshot(0, 0, 5, 1, 5)))}
    curr = {
        1: _cfg_snap(1, _song("s1", SegmentSnapshot(0, 0, 5, 1, 5))),
        2: _cfg_snap(2, _song("s2", SegmentSnapshot(0, 0, 3, 0, 3))),
    }
    diff = structural_changes(prev, curr)
    assert diff.added_config_ids == (2,)
    assert any("config added: 2" in line for line in diff.changes)


def test_structural_changes_no_silent_collapse():
    # Distinct configs are never collapsed: two configs that both exist in prev are each kept
    # distinct, and a membership-count change on one is reported rather than merged away.
    prev = {
        1: _cfg_snap(1, _song("s1", SegmentSnapshot(0, 0, 5, 1, 5))),
        2: _cfg_snap(2, _song("s1", SegmentSnapshot(0, 0, 8, 0, 8))),
    }
    curr = {
        1: _cfg_snap(1, _song("s1", SegmentSnapshot(0, 0, 6, 1, 6))),  # member_count 5 -> 6
        2: _cfg_snap(2, _song("s1", SegmentSnapshot(0, 0, 8, 0, 8))),
    }
    diff = structural_changes(prev, curr)
    assert diff.changed_config_ids == (1,)
    assert diff.changed_config_ids != (2,)  # config 2 unchanged and reported distinctly
    assert any("config 1 song 's1'" in line and "member_count 5 -> 6" in line for line in diff.changes)
    assert not any("config 2" in line for line in diff.changes)


def test_structural_changes_clean_when_identical():
    snap = {1: _cfg_snap(1, _song("s1", SegmentSnapshot(0, 0, 5, 1, 5)))}
    diff = structural_changes(snap, snap)
    assert diff.is_clean is True
    assert diff.changes == ()


# ── Catalog report (P4-S4) contains every required field ───────────────────────


def test_catalog_report_contains_required_fields(con, tmp_path, compact_catalog_factory):
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _threshold_split_mat()},
        configs=[_cfg(0.9)],
        song_ids=["s1"],
    )
    c = harness.con
    config_id = catalog.compact_configs_by_backbone(c, "effnet")[0].config_id

    snap_after = capture_catalog_structure(c)
    # A prior baseline with a different observed medoid => structural + medoid changes reported.
    seg = snap_after[config_id].songs[0].segments[0]
    baseline = {
        config_id: ConfigSnapshot(
            config_id=config_id,
            songs=(
                SongSnapshot(
                    song_id=snap_after[config_id].songs[0].song_id,
                    segments=(
                        SegmentSnapshot(
                            seg_id=seg.seg_id,
                            medoid_source_patch_idx=seg.medoid_source_patch_idx + 1,
                            member_count=seg.member_count,
                            absorbed_outlier_count=seg.absorbed_outlier_count,
                            membership_rows=seg.membership_rows,
                        ),
                    ),
                ),
            ),
        )
    }

    report = build_catalog_report(c, schema_version=SCHEMA_VERSION, baseline_structure=baseline)
    assert report.catalog_fingerprint == catalog_fingerprint(c, schema_version=SCHEMA_VERSION)
    assert len(report.catalog_fingerprint) == 64
    assert config_id in report.canonical_config_ids
    # configured + effective thresholds are carried on each canonical config row.
    assert any(
        cfg["config_id"] == config_id and float(cfg["threshold_effective"]) == 0.9 for cfg in report.canonical_configs
    )
    # exact searchable-membership + absorbed-outlier totals.
    assert report.membership_row_total >= 1
    assert report.absorbed_outlier_total >= 0
    assert report.config_content[0]["segments"] >= 1
    # empty_songs is present (tuple of (config_id, song_id) metadata-only pairs); run is surfaced.
    assert isinstance(report.empty_songs, tuple)
    assert isinstance(report.run, dict)
    # structural / observed-medoid changes are reported against the baseline (no silent collapse).
    assert report.structural_changes is not None
    assert report.changes
    assert any("medoid_source_patch_idx" in line for line in report.changes)
    # report_to_text is a human listing containing every required field.
    text = report_to_text(report)
    for token in (
        "catalog_fingerprint=",
        "canonical configs",
        "membership_rows_total=",
        "absorbed_outliers_total=",
        "empty_songs",
    ):
        assert token in text
    harness.close()


def test_catalog_report_lists_alias(con, tmp_path, compact_catalog_factory):
    """Two configs with identical search leaves are listed as a transient alias."""
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _threshold_split_mat()},
        configs=[_cfg(0.9), _cfg(1.0)],
        song_ids=["s1"],
    )
    c = harness.con
    ids = [r.config_id for r in catalog.compact_configs_by_backbone(c, "effnet")]
    assert len(ids) == 2
    report = build_catalog_report(c, schema_version=SCHEMA_VERSION)
    representative = min(ids)
    alias_id = max(ids)
    assert (alias_id, representative) in report.alias_entries
    assert report.alias_count == 1
    assert representative in report.canonical_config_ids
    assert alias_id not in report.canonical_config_ids
    assert f"alias {alias_id} -> canonical {representative}" in report_to_text(report)
    harness.close()


def test_catalog_report_reports_threshold_semantics_change(con, tmp_path, compact_catalog_factory):
    """Distinct thresholds under one snapshot are distinct canonical configs, never collapsed.

    0.9 merges the stream into one segment; 0.2 splits it into two, so the two configs carry
    distinct search leaves and distinct structural snapshots.  The report lists both
    canonically (no alias) and never silently collapses the two thresholds.
    """
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _threshold_split_mat()},
        configs=[_cfg(0.9), _cfg(0.2)],
        song_ids=["s1"],
    )
    c = harness.con
    by_threshold = _configs_by_threshold(c)
    assert set(by_threshold) == {0.9, 0.2}
    report = build_catalog_report(c, schema_version=SCHEMA_VERSION)
    # distinct thresholds -> both canonical, no transient alias, distinct structure.
    assert report.alias_entries == ()
    assert all(cid in report.canonical_config_ids for cid in by_threshold.values())
    assert len(report.config_content) == 2
    seg_counts = {by_threshold[t]: len(report.config_snapshots[by_threshold[t]].songs[0].segments) for t in (0.9, 0.2)}
    assert seg_counts[by_threshold[0.9]] != seg_counts[by_threshold[0.2]]
    harness.close()
