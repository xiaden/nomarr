"""Plan C Phase 4 (P4-S2 + P4-S4) — aliases, structural-change summaries, catalog reports.

Proves the DD alias contract (threshold-collapse aliases preserved as ``alias_of_config_id``
to ONE canonical meaning; cycles / alias-of-alias / self-alias / missing-target / meaning
conflicts rejected) and the structural-change summary contract (explicit membership / medoid
/ count changes, never silent collapse) implemented in
``scripts/embedding_research/catalog_report.py``, plus that the catalog report contains every
required field (canonical configs, aliases, configured + effective thresholds, empty/failed
songs, exact membership + outlier counts, observed medoid-index changes, structural changes,
``search_view_hash`` and ``catalog_fingerprint``).
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research import catalog
from scripts.embedding_research.catalog_identity import catalog_fingerprint, search_view_hash
from scripts.embedding_research.catalog_report import (
    AliasMeaningConflictError,
    AliasSelfError,
    AliasTargetMissingError,
    AliasTargetNotCanonicalError,
    ConfigSnapshot,
    SegmentSnapshot,
    SongSnapshot,
    build_alias_index,
    build_catalog_report,
    capture_catalog_structure,
    report_to_text,
    resolve_alias_id,
    structural_changes,
    validate_alias_graph,
)
from scripts.embedding_research.streams.store import StreamStore

SCHEMA_VERSION = 1


def _unit(rng, n: int, d: int, spread: float = 1.5) -> np.ndarray:
    m = rng.standard_normal((n, d)) * spread
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _cfg(threshold: float) -> catalog.SegConfigInput:
    return catalog.SegConfigInput(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _seed_stream(con, out, song: str, *, seed: int = 1, threshold: float = 0.9) -> tuple[StreamStore, int]:
    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(seed)
    store.publish(song, "effnet", _unit(rng, 60, 8), run_id="run-embed")
    store.reconcile()
    rep = catalog.build_segmentation_catalog(con, store, [_cfg(threshold)], [song], "run-cat-1", verify=True)
    assert rep.verify_ok is True
    return store, int(rep.configs[0].config_id)


def _cfgrow(
    cid: int,
    effective: float,
    *,
    configured: float | None = None,
    alias: int | None = None,
    backbone: str = "effnet",
) -> dict:
    """A synthetic ``seg_config`` row dict for pure alias-graph validation."""
    return {
        "config_id": cid,
        "backbone": backbone,
        "bin_mode": "temporal_global",
        "threshold_configured": configured if configured is not None else effective,
        "threshold_effective": effective,
        "semantics": "direct_l2",
        "calibration_record": "none",
        "outlier_window": 3,
        "strategy_version": 1,
        "alias_of_config_id": alias,
        "canonical_config_hash": "hash",
        "created_at": 1,
        "run_id": "r",
    }


def _insert_alias_row(con, alias_id: int, canonical_id: int, effective: float, configured: float) -> None:
    con.execute(
        "INSERT INTO seg_config (config_id, backbone, bin_mode, threshold_configured, "
        "threshold_effective, semantics, calibration_record, outlier_window, strategy_version, "
        "alias_of_config_id, canonical_config_hash, created_at, run_id) "
        "VALUES (?, 'effnet', 'temporal_global', ?, ?, 'direct_l2', 'none', 3, 1, ?, 'alias-hash', 1, 'r')",
        [alias_id, configured, effective, canonical_id],
    )


# ── Alias resolution (pure) ────────────────────────────────────────────────────


def test_alias_resolves_to_canonical_and_canonical_resolves_to_self():
    canonical = _cfgrow(1, 0.9)
    alias = _cfgrow(2, 0.9, configured=0.95, alias=1)  # configured differs, meaning collapses
    index = build_alias_index([canonical, alias])
    assert index.canonical_config_ids == (1,)
    assert index.alias_targets == {2: 1}
    assert resolve_alias_id(1, index) == 1
    assert resolve_alias_id(2, index) == 1
    assert index.alias_config_ids == (2,)


def test_self_alias_rejected():
    with pytest.raises(AliasSelfError):
        build_alias_index([_cfgrow(1, 0.9), _cfgrow(2, 0.9, alias=2)])


def test_missing_alias_target_rejected():
    with pytest.raises(AliasTargetMissingError):
        build_alias_index([_cfgrow(1, 0.9), _cfgrow(2, 0.9, alias=99)])


def test_alias_of_alias_rejected():
    # 2 aliases 1, and 1 is itself an alias of canonical 3 — alias targets must be canonical.
    with pytest.raises(AliasTargetNotCanonicalError):
        build_alias_index([_cfgrow(1, 0.9, alias=3), _cfgrow(2, 0.9, alias=1), _cfgrow(3, 0.9)])


def test_meaning_conflict_alias_rejected():
    # An alias claiming a DIFFERENT effective meaning under one canonical = two meanings.
    with pytest.raises(AliasMeaningConflictError):
        build_alias_index([_cfgrow(1, 0.9), _cfgrow(2, 0.5, alias=1)])


def test_two_valid_aliases_share_one_canonical():
    index = build_alias_index(
        [_cfgrow(1, 0.9), _cfgrow(2, 0.9, configured=0.95, alias=1), _cfgrow(3, 0.9, configured=0.88, alias=1)]
    )
    assert index.canonical_config_ids == (1,)
    assert index.alias_targets == {2: 1, 3: 1}


# ── Alias graph against the DB / identity ──────────────────────────────────────


def test_db_alias_validation_and_no_corpus_identity_change(con, tmp_path):
    _, canonical_id = _seed_stream(con, tmp_path, "s1")
    hash_before = search_view_hash(con)
    alias_id = canonical_id + 100
    _insert_alias_row(con, alias_id, canonical_id, effective=0.9, configured=0.95)
    index = validate_alias_graph(con)
    assert index.alias_targets == {alias_id: canonical_id}
    # Aliasing is reported, never multiplied into corpus identity: the search hash is unchanged.
    assert search_view_hash(con) == hash_before


def test_db_invalid_alias_raises_meaning_conflict(con, tmp_path):
    _, canonical_id = _seed_stream(con, tmp_path, "s1")
    _insert_alias_row(con, canonical_id + 100, canonical_id, effective=0.5, configured=0.5)
    with pytest.raises(AliasMeaningConflictError):
        validate_alias_graph(con)


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


def test_catalog_report_contains_required_fields(con, tmp_path):
    _, config_id = _seed_stream(con, tmp_path, "s1")
    # A ready stream for a song that was never cataloged => an "empty song" under this config.
    store2 = StreamStore(con, output_root=str(tmp_path / "s2"))
    store2.publish("s2", "effnet", _unit(np.random.default_rng(3), 40, 8), run_id="run-embed")
    store2.reconcile()

    snap_after = capture_catalog_structure(con)
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

    report = build_catalog_report(con, schema_version=SCHEMA_VERSION, baseline_structure=baseline)
    assert report.catalog_fingerprint == catalog_fingerprint(con, schema_version=SCHEMA_VERSION)
    assert report.search_view_hash == search_view_hash(con)
    assert len(report.catalog_fingerprint) == 64
    assert len(report.search_view_hash) == 64
    assert config_id in report.canonical_config_ids
    # configured + effective thresholds are carried on each canonical config row.
    assert any(c["config_id"] == config_id and float(c["threshold_effective"]) == 0.9 for c in report.canonical_configs)
    # exact membership + outlier counts.
    assert report.membership_row_total >= 1
    assert report.absorbed_outlier_total >= 0
    assert report.config_content[0]["segments"] >= 1
    # empty songs reconstructed from ready-stream space minus covered membership.
    assert (config_id, "s2") in report.empty_songs
    # run provenance is surfaced.
    assert report.run.get("phase") == "catalog"
    # structural / observed-medoid changes are reported against the baseline (no silent collapse).
    assert report.structural_changes is not None
    assert report.changes
    assert any("medoid_source_patch_idx" in line for line in report.changes)
    # report_to_text is a human listing containing every required field.
    text = report_to_text(report)
    for token in (
        "catalog_fingerprint=",
        "search_view_hash=",
        "canonical configs",
        "membership_rows_total=",
        "absorbed_outliers_total=",
        "empty_songs",
    ):
        assert token in text


def test_catalog_report_lists_alias(con, tmp_path):
    _, canonical_id = _seed_stream(con, tmp_path, "s1")
    alias_id = canonical_id + 100
    _insert_alias_row(con, alias_id, canonical_id, effective=0.9, configured=0.95)
    report = build_catalog_report(con, schema_version=SCHEMA_VERSION)
    assert (alias_id, canonical_id) in report.alias_entries
    assert report.alias_count == 1
    assert canonical_id in report.canonical_config_ids
    assert alias_id not in report.canonical_config_ids
    assert f"alias {alias_id} -> canonical {canonical_id}" in report_to_text(report)


def test_catalog_report_reports_threshold_semantics_change(con, tmp_path):
    # Rebuilding under a different threshold yields a second distinct config + membership; the
    # structural diff between the two runs must surface the change, never collapse them.
    _, config_id = _seed_stream(con, tmp_path, "s1", seed=1, threshold=0.9)
    prev_snap = capture_catalog_structure(con)
    store2 = StreamStore(con, output_root=str(tmp_path / "low"))
    store2.publish("s1", "effnet", _unit(np.random.default_rng(1), 60, 8), run_id="run-embed")
    store2.reconcile()
    rep2 = catalog.build_segmentation_catalog(con, store2, [_cfg(0.2)], ["s1"], "run-cat-2", verify=True)
    assert rep2.verify_ok is True
    capture_catalog_structure(con)
    new_config_id = int(rep2.configs[0].config_id)
    assert new_config_id != config_id
    report = build_catalog_report(con, schema_version=SCHEMA_VERSION, baseline_structure=prev_snap)
    assert any("config added" in line for line in report.changes)
    # Every distinct config is listed explicitly (no silent collapse of the two thresholds).
    assert config_id in report.canonical_config_ids
    assert new_config_id in report.canonical_config_ids
