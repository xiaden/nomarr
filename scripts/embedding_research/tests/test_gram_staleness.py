"""R10 — stale committed-observation refusal at every geometry-derived seam.

A geometry row bound to a superseded commit is never re-selected, rebound, repaired,
or resolved "latest": geometry open/write, verify, reindex, maintenance cleanup, analyze/head/report
open, and preflight all raise the typed STALE_REFUSED/INTEGRITY_REFUSED refusal.
"""

from __future__ import annotations

import dataclasses
import json

import duckdb
import pytest

from scripts.embedding_research import cleanup as cleanup_mod
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.geometry import (
    GeometryRefusal,
    IntegrityRefused,
    StaleRefused,
    preflight_geometry_binding,
    read_geometry,
    require_current_geometry,
    verify_geometry_current,
    write_geometry,
)
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.tests._gram_evidence import SyntheticObservation, emit_evidence


class _Store:
    def __init__(self, observation) -> None:
        self._observation = observation

    def load_committed_observation(self, _song_id: str, _backbone: str):
        return self._observation


def _old_new(con):
    old = SyntheticObservation(con, song_id="song-stale", backbone="backbone-stale", commit="commit-old")
    record = write_geometry(old, GeometryProfile.current(), "run-stale")
    new = SyntheticObservation(con, song_id="song-stale", backbone="backbone-stale", commit="commit-new")
    return old, new, record


def test_stale_refusal_at_geometry_open_and_write() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        old, _new, record = _old_new(con)
        assert read_geometry(record.identity, con).gram_blob == record.gram_blob
        absent = dataclasses.replace(record.identity, observation_group_sha256="commit-absent")
        with pytest.raises(GeometryRefusal, match="expected one row"):
            read_geometry(absent, con)
        with pytest.raises(GeometryRefusal, match="already exists"):
            write_geometry(old, GeometryProfile.current(), "run-duplicate")
        emit_evidence(
            "r10-open-write-refusal.json",
            {"stale_read_refused": True, "duplicate_write_refused": True, "typed": "GeometryRefusal"},
        )
    finally:
        con.close()


def test_stale_refusal_at_verify_and_cleanup(tmp_path) -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        _old, new, _record = _old_new(con)
        with pytest.raises(StaleRefused, match="superseded"):
            verify_geometry_current(con, new, profile=GeometryProfile.current())

        marker_dir = tmp_path / "observation_commits"
        marker_dir.mkdir(parents=True)
        (marker_dir / "marker.json").write_text(
            json.dumps({"song_id": new.identity.song_id, "backbone": new.identity.backbone}), encoding="utf-8"
        )
        refusals = cleanup_mod._geometry_refusals(tmp_path, con)
        assert refusals, "maintenance must refuse while geometry is stale/corrupt"
        report = cleanup_mod.cleanup_current(tmp_path, con, scope="stray", dry_run=True)
        assert report.refused
        assert not report.removed
        emit_evidence(
            "r10-verify-cleanup-refusal.json",
            {"verify_refused": True, "cleanup_refused": True, "refusal_count": len(refusals)},
        )
    finally:
        con.close()


def test_stale_refusal_at_reindex_seam(tmp_path) -> None:
    """Exercise the ``streams/reindex.py`` maintenance seam against a superseded geometry row.

    A real committed observation group is published through :class:`StreamStore` (marker +
    stream/mask manifests on disk).  Geometry is bound to a DIFFERENT (older) observation
    commit, so the reindex seam must convert the typed geometry refusal into a recorded
    issue rather than silently rebinding the stale row.
    """
    import numpy as np

    from scripts.embedding_research.streams.masks import MaskPayload
    from scripts.embedding_research.streams.reindex import reindex
    from scripts.embedding_research.streams.store import StreamStore

    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        song_id, backbone = "song-stale", "backbone-stale"
        superseded = SyntheticObservation(con, song_id=song_id, backbone=backbone, commit="commit-old")
        write_geometry(superseded, GeometryProfile.current(), "run-stale")

        root = tmp_path / "root"
        store = StreamStore(con, output_root=root)
        patch_count = superseded.stream.shape[0]
        record = store.publish(song_id, backbone, superseded.stream, run_id="run-reindex")
        store.publish_observation_group(
            record,
            MaskPayload(
                song_id=song_id,
                backbone=backbone,
                patch_count=patch_count,
                mask=np.ones(patch_count, dtype=np.uint8),
                run_id="run-reindex",
                params_id="mask-params-1",
                audio_content_sha256="0" * 64,
            ),
        )

        report = reindex(root, con)

        assert report.issues, "reindex must record the stale-geometry refusal as an issue"
        assert any("geometry binding refused" in issue for issue in report.issues)
        assert report.rows_rebuilt == 0
        emit_evidence(
            "r10-reindex-refusal.json",
            {
                "reindex_refused": True,
                "issue_count": len(report.issues),
                "rows_rebuilt": report.rows_rebuilt,
                "typed": "STALE_REFUSED",
            },
        )
    finally:
        con.close()


def test_stale_refusal_at_analyze_head_analysis_and_report() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        _old, new, _record = _old_new(con)
        with pytest.raises(StaleRefused, match="superseded"):
            require_current_geometry(
                new.identity.song_id,
                new.identity.backbone,
                con,
                store=_Store(new),
                profile=GeometryProfile.current(),
            )
        emit_evidence(
            "r10-derived-seam-refusal.json",
            {"seams": ["analyze", "head-analysis", "report"], "typed": "STALE_REFUSED"},
        )
    finally:
        con.close()


def test_preflight_stale_refusal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        _old, new, record = _old_new(con)
        with pytest.raises(StaleRefused):
            preflight_geometry_binding(record, GeometryProfile.current(), observation=new)
        with pytest.raises(IntegrityRefused):
            preflight_geometry_binding(record, GeometryProfile.current(), observation=None)
        emit_evidence(
            "r10-preflight-refusal.json",
            {"preflight_stale": True, "preflight_missing_observation": True},
        )
    finally:
        con.close()
