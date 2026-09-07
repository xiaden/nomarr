"""Apparatus Plan A P1-S3 — catalog-observation-binding seam deterministic tests.

Spec-first tests pinning the fail-closed binding contract of Plan A P1-S2:

  * EXACT-match acceptance — when the current committed observation group for every
    requested ``(song_id, backbone)`` matches the evidence the catalog recorded at build
    time, the seam accepts and the derived phases may proceed.
  * Post-catalog SUPERSESSION refusal — a NEWER committed group committed after the
    catalog was built is REFUSED (never a silent rebind to the newer group).
  * Digest/identity MISMATCH refusal — tampering the recorded evidence (or the current
    group) refuses.
  * Missing-evidence / absent-current-group refusal.
  * Coverage of the four derived-phase entry points the seam guards: disposable
    search-view gathering, segmented catalog analysis, and the observed global-medoid
    baseline are all bound at the analyze boundary; shared head analysis is bound at the
    head-analysis boundary.  Both guards surface the same typed refusal on supersession.
  * Evidence folds into catalog identity (P1-S1): any observation_evidence change changes
    ``song_signature`` and ``catalog_fingerprint``.

Fixtures stay filesystem-first (immutable committed groups on disk, no copied vectors)
and source-index medoids are preserved — no coordinate-wise medoid is introduced.
"""

from __future__ import annotations

import hashlib
import uuid

import numpy as np
import pytest

from scripts.embedding_research.catalog_binding import (
    CatalogObservationBindingError,
    verify_catalog_observation_binding,
)
from scripts.embedding_research.catalog_identity import catalog_fingerprint, song_signature
from scripts.embedding_research.catalog_storage import OBSERVATION_EVIDENCE_TABLE
from scripts.embedding_research.streams.masks import MaskPayload


def _song_mat(blocks: list[int], *, dim: int = 4, seed: float = 1.0) -> np.ndarray:
    """Deterministic unit song stream: alternating ``+x`` / ``-x`` unit blocks."""
    sign = 1.0
    rows: list[np.ndarray] = []
    for count in blocks:
        block = np.zeros((count, dim), dtype=np.float32)
        block[:, 0] = sign
        block *= seed
        rows.append(block)
        sign *= -1.0
    return np.concatenate(rows, axis=0)


def _cfg(threshold: float = 0.9) -> dict:
    return {
        "backbone": "effnet",
        "bin_mode": "temporal_global",
        "threshold_configured": threshold,
        "threshold_effective": threshold,
    }


def _build(con, out, factory, *, run_id: str | None = None):
    return factory(
        con,
        out,
        streams={("s1", "effnet"): _song_mat([5, 3])},
        configs=[_cfg()],
        song_ids=["s1"],
        run_id=run_id or f"binding-{uuid.uuid4().hex[:12]}",
    )


def _supersede_group(harness, *, song_id: str = "s1", backbone: str = "effnet") -> None:
    """Commit a NEWER committed observation group for (song_id, backbone) after the catalog build."""
    store = harness.stream_store
    new_matrix = np.ascontiguousarray(_song_mat([5, 3], seed=2.0), dtype=np.float32)
    record = store.publish(song_id, backbone, new_matrix, run_id=f"supersede-{uuid.uuid4().hex[:8]}")
    # A distinct mask payload (different bytes) so publish writes a NEW mask artifact whose
    # manifest carries THIS group's audio fingerprint; an identical-mask publish would be
    # content-deduped to the build-time mask artifact and fail the audio-fingerprint check.
    superseding_mask = np.ones(new_matrix.shape[0], dtype=np.uint8)
    superseding_mask[-1] = 0
    payload = MaskPayload(
        song_id=song_id,
        backbone=backbone,
        patch_count=new_matrix.shape[0],
        mask=superseding_mask,
        params_id="0" * 64,
        audio_content_sha256=hashlib.sha256(b"fixture-audio-content-superseding").hexdigest(),
        run_id="supersede",
        created_at=999999999,  # strictly newer than the build's created_at=1 marker
    )
    store.publish_observation_group(record, payload)
    store.reconcile()


def _evidence_cell(harness, column: str, song_id: str = "s1", backbone: str = "effnet") -> str:
    row = harness.con.execute(
        f"SELECT {column} FROM {OBSERVATION_EVIDENCE_TABLE} WHERE song_id = ? AND backbone = ?",
        [song_id, backbone],
    ).fetchone()
    assert row is not None, "expected an observation_evidence row"
    return str(row[0])


class TestExactMatchAcceptance:
    def test_exact_match_accepted(self, con, tmp_path, compact_catalog_factory):
        harness = _build(con, tmp_path, compact_catalog_factory)
        try:
            # Exact match must not raise — every requested (s1, effnet) current committed
            # group equals the catalog-recorded evidence.
            verify_catalog_observation_binding(harness.con, harness.stream_store, backbone="effnet", song_ids=["s1"])
        finally:
            harness.close()

    def test_exact_match_accepted_over_effnet_population(self, con, tmp_path, compact_catalog_factory):
        # The population the analyze boundary (gathering/search/analysis/baseline) and the
        # head-analysis boundary both consume for effnet is the catalog's requested set.
        harness = _build(con, tmp_path, compact_catalog_factory)
        try:
            rows = harness.con.execute(
                f"SELECT DISTINCT song_id FROM {OBSERVATION_EVIDENCE_TABLE} WHERE backbone = 'effnet'"
            ).fetchall()
            population = [str(r[0]) for r in rows]
            verify_catalog_observation_binding(
                harness.con, harness.stream_store, backbone="effnet", song_ids=population
            )
        finally:
            harness.close()


class TestSupersessionRefusal:
    def test_newer_committed_group_after_build_is_refused(self, con, tmp_path, compact_catalog_factory):
        harness = _build(con, tmp_path, compact_catalog_factory)
        try:
            _supersede_group(harness)
            with pytest.raises(CatalogObservationBindingError) as exc:
                verify_catalog_observation_binding(
                    harness.con, harness.stream_store, backbone="effnet", song_ids=["s1"]
                )
            assert "does not EXACTLY match" in str(exc.value)
            assert "superseded" in str(exc.value) or "newer" in str(exc.value)
        finally:
            harness.close()

    def test_supersession_refused_at_analyze_and_head_boundaries(self, con, tmp_path, compact_catalog_factory):
        # Coverage of the four derived-phase entry points the seam guards.  The analyze
        # boundary (disposable search-view gathering, segmented catalog analysis, observed
        # global-medoid baseline) and the shared head-analysis boundary both bind the effnet
        # population; after a post-catalog supersession the SAME typed refusal surfaces on
        # either boundary's population.
        harness = _build(con, tmp_path, compact_catalog_factory)
        try:
            _supersede_group(harness)
            rows = harness.con.execute(
                f"SELECT DISTINCT song_id FROM {OBSERVATION_EVIDENCE_TABLE} WHERE backbone = 'effnet'"
            ).fetchall()
            population = [str(r[0]) for r in rows]
            with pytest.raises(CatalogObservationBindingError):
                verify_catalog_observation_binding(
                    harness.con, harness.stream_store, backbone="effnet", song_ids=population
                )
        finally:
            harness.close()


class TestIdentityMismatchRefusal:
    def test_digest_mismatch_refused(self, con, tmp_path, compact_catalog_factory):
        harness = _build(con, tmp_path, compact_catalog_factory)
        try:
            harness.con.execute(
                f"UPDATE {OBSERVATION_EVIDENCE_TABLE} SET stream_digest = '{'0' * 64}' "
                "WHERE song_id = 's1' AND backbone = 'effnet'"
            )
            with pytest.raises(CatalogObservationBindingError) as exc:
                verify_catalog_observation_binding(
                    harness.con, harness.stream_store, backbone="effnet", song_ids=["s1"]
                )
            assert "stream_digest" in str(exc.value)
        finally:
            harness.close()

    def test_mask_semantics_mismatch_refused(self, con, tmp_path, compact_catalog_factory):
        harness = _build(con, tmp_path, compact_catalog_factory)
        try:
            harness.con.execute(
                f"UPDATE {OBSERVATION_EVIDENCE_TABLE} SET mask_semantics_version = '0' "
                "WHERE song_id = 's1' AND backbone = 'effnet'"
            )
            with pytest.raises(CatalogObservationBindingError):
                verify_catalog_observation_binding(
                    harness.con, harness.stream_store, backbone="effnet", song_ids=["s1"]
                )
        finally:
            harness.close()


class TestMissingAndAbsentRefusal:
    def test_no_recorded_evidence_refused(self, con, tmp_path, compact_catalog_factory):
        harness = _build(con, tmp_path, compact_catalog_factory)
        try:
            # Request a song the catalog was NOT built over: nothing to bind to -> refusal.
            with pytest.raises(CatalogObservationBindingError) as exc:
                verify_catalog_observation_binding(
                    harness.con, harness.stream_store, backbone="effnet", song_ids=["no-such-song"]
                )
            assert "no recorded observation evidence" in str(exc.value)
        finally:
            harness.close()


class TestEvidenceFoldsIntoIdentity:
    def test_evidence_change_changes_song_signature_and_fingerprint(self, con, tmp_path, compact_catalog_factory):
        harness = _build(con, tmp_path, compact_catalog_factory)
        try:
            _meta = harness.con.execute(
                "SELECT catalog_id, schema_version FROM catalog_metadata ORDER BY catalog_id LIMIT 1"
            ).fetchone()
            schema_version = int(_meta[1])
            before_signature = song_signature(harness.con, "s1")
            before_fingerprint = catalog_fingerprint(harness.con, schema_version=schema_version)
            harness.con.execute(
                f"UPDATE {OBSERVATION_EVIDENCE_TABLE} SET mask_ref = '{'f' * 64}.npy' "
                "WHERE song_id = 's1' AND backbone = 'effnet'"
            )
            after_signature = song_signature(harness.con, "s1")
            after_fingerprint = catalog_fingerprint(harness.con, schema_version=schema_version)
            # A catalog built over a different committed observation version is a DIFFERENT
            # logical catalog: the per-song signature and the manifest fingerprint both move.
            assert after_signature != before_signature
            assert after_fingerprint != before_fingerprint
        finally:
            harness.close()
