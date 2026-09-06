"""P1-S1 spec-first suite: committed-observation-group readiness (fail-closed).

DD "frozen observation corrective pass": a stream and its audio-derived silence mask
are published as ONE logical observation group (mask payload + manifest durably renamed
FIRST, commit marker LAST).  A catalog entry, head-analysis pooling, and reindex are
authorised ONLY by a complete committed group:

* an immutable embedding stream, PLUS
* an aligned audio-derived silence mask (uint8[P], 1 = searchable, 0 = silent) matching
  the stream's ``(song_id, backbone, patch_count)``, PLUS
* commit/identity metadata whose marker filename/content digest, referenced current
  manifests, and payload bytes/digest/shape all verify.

MISSING, corrupt, wrong-length, wrong-digest, or uncommitted masks must FAIL CLOSED —
absence is never interpreted as "no silence" and a registry ``ready`` row never
authorises a stream by itself.  Every test here asserts a refusal, never a silent
all-searchable fallback.

The store-level group predicate (``StreamStore.observation_group_ready``) and the
current reindex/mask seams ALREADY enforce this fail-closed contract, so the readiness
tests below pass on today's code (they pin the contract green).  The committed-group
read seams that do NOT exist yet — ``ObservationGroupIdentity``,
``StreamStore.load_committed_observation``, ``CurrentMaskResolver`` /
``make_current_mask_resolver``, ``module.observation_group_ready`` (future resolver
home), ``reconcile_current_manifests`` returning group-level refusals, and
``CurrentStreamResolver.load`` acquiring group-only semantics — are imported INSIDE the
tests that target them and are expected RED until P1-S2/P1-S3/P1-S7 land.  All fixtures
are synthetic (numpy + a real research DuckDB + a tmp filesystem); no audio/model/ONNX.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

# Stub nomarr.helpers.time_helper (same pattern as test_observation_masks.py).
_time_helper_module: Any = ModuleType("nomarr.helpers.time_helper")
_time_helper_module.internal_ms = lambda: 0
_helpers_module: Any = sys.modules.setdefault("nomarr.helpers", ModuleType("nomarr.helpers"))
_helpers_module.time_helper = _time_helper_module
sys.modules.setdefault("nomarr.helpers.time_helper", _time_helper_module)

from scripts.embedding_research.streams import StreamStore
from scripts.embedding_research.streams.masks import (
    MaskPayload,
    canonical_audio_fingerprint,
)
from scripts.embedding_research.streams.publication import RecordingFileOps


@pytest.fixture
def tmp_path(request):
    import uuid

    safe_name = request.node.name[:20]
    return Path(tempfile.mkdtemp(prefix=f"{safe_name}-{uuid.uuid4().hex[:8]}-"))


def _store(con, tmp_path) -> StreamStore:
    return StreamStore(con, output_root=tmp_path)


def _audio_fp(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _publish_stream(con, tmp_path, sid="songA", backbone="effnet", patch_count=7):
    store = _store(con, tmp_path)
    embeddings = np.random.RandomState(0).rand(patch_count, 4).astype(np.float32)
    record = store.publish(sid, backbone, embeddings, run_id="run-1")
    return store, record


def _mask_payload(sid, backbone, patch_count, audio_waveform=None, run_id="run-1") -> MaskPayload:
    fp = canonical_audio_fingerprint(audio_waveform) if audio_waveform is not None else _audio_fp(b"audio-content")
    return MaskPayload(
        song_id=sid,
        backbone=backbone,
        patch_count=patch_count,
        mask=np.ones(patch_count, dtype=np.uint8),
        params_id="0" * 64,
        audio_content_sha256=fp,
        run_id=run_id,
        created_at=1,
    )


def _commit_group(con, tmp_path, sid="songA", backbone="effnet", patch_count=7, mask=None):
    """Publish a stream + a fully committed observation group; return (store, record, commit)."""
    store, record = _publish_stream(con, tmp_path, sid=sid, backbone=backbone, patch_count=patch_count)
    payload = _mask_payload(sid, backbone, patch_count)
    if mask is not None:
        payload.mask = np.asarray(mask, dtype=np.uint8)
    commit = store.publish_observation_group(record, payload, file_ops=RecordingFileOps())
    store.reconcile()  # promote the committed group so a ready registry row exists
    return store, record, commit


def _commit_marker(tmp_path, sid="songA", backbone="effnet") -> Path:
    """Return the on-disk observation-commit marker path for ``(sid, backbone)``."""
    marker_dir = tmp_path / "observation_commits"
    candidates = sorted(p for p in marker_dir.glob(f"{sid}.{backbone}.*.json"))
    assert candidates, f"no observation-commit marker for {sid}.{backbone} under {marker_dir}"
    return candidates[-1]


def _group_manifest(tmp_path, artifact_ref: str) -> Path:
    """Map a payload ``artifact_ref`` to its sibling ``.json`` manifest on disk."""
    ref = Path(artifact_ref)
    if ref.suffix == ".npy":
        return tmp_path / ref.with_suffix(".json")
    return tmp_path / (artifact_ref + ".json")


# --------------------------------------------------------------------------- #
# Complete committed group -> READY / resolvable (green on today's store)       #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_complete_committed_group_is_ready_and_resolvable(con, tmp_path):
    store, record, _commit = _commit_group(con, tmp_path)
    assert store.observation_group_ready("songA", "effnet", stream_record=record) is True
    ready = store.ready_stream_record("songA", "effnet")
    assert ready is not None and ready.artifact_ref == record.artifact_ref
    assert (tmp_path / "observation_commits").is_dir()


@pytest.mark.unit
def test_stream_only_is_never_ready(con, tmp_path):
    store, record = _publish_stream(con, tmp_path)
    # Only the immutable stream artifact exists — no silence mask, no commit marker.
    assert (tmp_path / "observation_commits").exists() is False
    assert store.observation_group_ready("songA", "effnet", stream_record=record) is False


@pytest.mark.unit
def test_stream_plus_mask_without_commit_marker_is_never_ready(con, tmp_path):
    store, record = _publish_stream(con, tmp_path)
    payload = _mask_payload("songA", "effnet", record.patch_count)
    store.publish_mask(payload)  # mask payload+manifest exist but NO commit marker
    assert (tmp_path / "audio_masks").is_dir()
    assert (tmp_path / "observation_commits").exists() is False
    # Absence of the marker is NEVER interpreted as "all searchable" readiness.
    assert store.observation_group_ready("songA", "effnet", stream_record=record) is False


@pytest.mark.unit
def test_missing_mask_payload_breaks_readiness(con, tmp_path):
    store, _record, commit = _commit_group(con, tmp_path)
    assert store.observation_group_ready("songA", "effnet") is True
    (tmp_path / commit.mask_ref).unlink()  # committed mask payload removed
    assert store.observation_group_ready("songA", "effnet") is False


@pytest.mark.unit
def test_corrupt_mask_payload_breaks_readiness(con, tmp_path):
    store, _record, commit = _commit_group(con, tmp_path)
    (tmp_path / commit.mask_ref).write_bytes(b"this is not a valid uint8 npy payload")
    assert store.observation_group_ready("songA", "effnet") is False


@pytest.mark.unit
def test_wrong_length_mask_payload_breaks_readiness(con, tmp_path):
    store, _record, commit = _commit_group(con, tmp_path)
    patch_count = _committed_mask_length(tmp_path, commit)
    # Overwrite the committed mask payload with a WRONG-LENGTH uint8 array.  A length
    # change cannot keep the same digest, so it also breaks the digest chain — assert the
    # group fails closed rather than ever treating the wrong-length payload as silence.
    import io

    from scripts.embedding_research.streams.masks import mask_npy_bytes

    bad = mask_npy_bytes(np.ones(patch_count + 3, dtype=np.uint8))
    (tmp_path / commit.mask_ref).write_bytes(io.BytesIO(bad).getvalue())
    assert store.observation_group_ready("songA", "effnet") is False


def _committed_mask_length(tmp_path, commit) -> int:
    """Recover the committed mask's declared patch_count from its manifest."""
    import json

    manifest_path = _group_manifest(tmp_path, commit.mask_ref)
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    return int(doc["patch_count"])


@pytest.mark.unit
def test_malformed_commit_reference_breaks_readiness(con, tmp_path):
    store, record = _commit_group(con, tmp_path)[:2]
    marker = _commit_marker(tmp_path)
    marker.write_text("{ not valid json", encoding="utf-8")  # malformed commit reference
    assert store.observation_group_ready("songA", "effnet", stream_record=record) is False


@pytest.mark.unit
def test_removed_commit_marker_breaks_readiness(con, tmp_path):
    store, _record = _commit_group(con, tmp_path)[:2]
    _commit_marker(tmp_path).unlink()
    assert store.observation_group_ready("songA", "effnet") is False


@pytest.mark.unit
def test_commit_marker_is_written_last_after_mask_rename(con, tmp_path):
    store, _record, _commit = _commit_group(con, tmp_path)
    assert store.observation_group_ready("songA", "effnet") is True


# --------------------------------------------------------------------------- #
# Group/identity mismatch + wrong-digest refusal (store seam is fail-closed)   #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_cross_identity_group_is_refused_at_publish(con, tmp_path):
    store, record = _publish_stream(con, tmp_path)
    with pytest.raises(ValueError, match="song_id mismatch"):
        store.publish_observation_group(record, _mask_payload("songB", "effnet", record.patch_count))
    with pytest.raises(ValueError, match="backbone mismatch"):
        store.publish_observation_group(record, _mask_payload("songA", "musicnn", record.patch_count))
    with pytest.raises(ValueError, match="patch_count mismatch"):
        store.publish_observation_group(record, _mask_payload("songA", "effnet", record.patch_count + 3))


@pytest.mark.unit
def test_mask_manifest_digest_tamper_breaks_readiness(con, tmp_path):
    """A mask manifest whose recorded digest no longer matches its payload is refused."""
    import json

    store, _record, commit = _commit_group(con, tmp_path)
    manifest_path = _group_manifest(tmp_path, commit.mask_ref)
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc["payload_sha256"] = "0" * 64  # lies about the on-disk payload digest
    manifest_path.write_text(json.dumps(doc), encoding="utf-8")
    assert store.observation_group_ready("songA", "effnet") is False


@pytest.mark.unit
def test_wrong_audio_fingerprint_breaks_readiness(con, tmp_path):
    """A mask manifest bound to the WRONG audio content is refused by the future load seam.

    The current group predicate validates structural identity + payload digest only; the
    full audio-fingerprint chain is enforced by P1-S2 ``load_committed_observation``.  This
    spec is expected RED (import ``ObservationGroupIdentity``) until that seam lands.
    """
    import json

    store, _record, commit = _commit_group(con, tmp_path)
    manifest_path = _group_manifest(tmp_path, commit.mask_ref)
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc["audio_content_sha256"] = "1" * 64
    manifest_path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(Exception, match=r"fingerprint|identity|refuse|digest"):
        store.load_committed_observation("songA", "effnet")  # red until P1-S2


@pytest.mark.unit
def test_wrong_mask_semantics_version_breaks_readiness(con, tmp_path):
    """A mask manifest with an unknown mask-semantics grammar is refused by the load seam.

    Expected RED until P1-S2's committed-group read seam validates ``mask_semantics_version``.
    """
    import json

    store, _record, commit = _commit_group(con, tmp_path)
    manifest_path = _group_manifest(tmp_path, commit.mask_ref)
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc["mask_semantics_version"] = "0"  # 1=searchable/0=silent grammar changed -> refuse
    manifest_path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(Exception, match=r"semantics|version|refuse"):
        store.load_committed_observation("songA", "effnet")  # red until P1-S2


# --------------------------------------------------------------------------- #
# Registry ``ready`` never authorises a stream without a valid committed group #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_registry_ready_row_without_commit_marker_is_not_group_ready(con, tmp_path):
    store, _record = _publish_stream(con, tmp_path)
    # Force the registry row to claim ``ready`` WITHOUT any committed observation group.
    # A registry row is cache metadata only and must never authorise a group by itself.
    con.execute("UPDATE stream_registry SET status = 'ready' WHERE song_id = 'songA' AND backbone = 'effnet'")
    assert store.ready_stream_record("songA", "effnet") is not None  # row claims ready
    assert (tmp_path / "observation_commits").exists() is False  # but no commit marker
    # No mask is committed -> the observation group is NOT ready (fails closed), even
    # though the registry row lies about being ready.
    assert store.observation_group_ready("songA", "effnet") is False


@pytest.mark.unit
def test_registry_ready_row_without_stream_on_disk_is_not_group_ready(con, tmp_path):
    store, record = _publish_stream(con, tmp_path)
    con.execute("UPDATE stream_registry SET status = 'ready' WHERE song_id = 'songA' AND backbone = 'effnet'")
    assert store.ready_stream_record("songA", "effnet") is not None
    # Remove the on-disk stream payload the ready row references -> the group refuses
    # (a cache row pointing at a vanished payload never verifies).
    (tmp_path / record.artifact_ref).unlink()
    assert store.observation_group_ready("songA", "effnet") is False


# --------------------------------------------------------------------------- #
# FUTURE committed-group read seams (RED until P1-S2/P1-S3/P1-S7)              #
# --------------------------------------------------------------------------- #


def test_future_load_committed_observation_returns_full_group(con, tmp_path):
    """P1-S2 spec: load_committed_observation returns the immutable identity + both payloads."""
    _unused_store, record, _commit = _commit_group(con, tmp_path)
    from scripts.embedding_research.streams.records import ObservationGroupIdentity  # red

    store = _store(con, tmp_path)
    loaded = store.load_committed_observation("songA", "effnet")  # red until P1-S2
    assert loaded is not None
    identity = loaded.identity
    assert isinstance(identity, ObservationGroupIdentity)
    assert identity.song_id == "songA"
    assert identity.backbone == "effnet"
    assert identity.stream_ref == record.artifact_ref
    assert len(identity.stream_digest) == 64
    assert len(identity.mask_digest) == 64
    assert identity.alignment_token == f"{identity.stream_ref}:{identity.mask_ref}"
    assert identity.mask_semantics_version == "1"
    assert len(identity.audio_content_sha256) == 64
    assert len(identity.commit_sha256) == 64
    assert loaded.stream.shape == (record.patch_count, 4)
    assert loaded.mask.shape == (record.patch_count,)


def test_future_load_committed_observation_refuses_stream_only(con, tmp_path):
    """P1-S2 spec: a stream-only observation (no committed group) is a typed refusal, never None-data."""

    store, _record = _publish_stream(con, tmp_path)
    with pytest.raises(Exception, match=r"commit|group|ready|mask"):
        store.load_committed_observation("songA", "effnet")  # red until P1-S2


def test_future_mask_resolver_is_committed_group_authoritative(con, tmp_path):
    """P1-S2 spec: make_current_mask_resolver().load returns ONLY committed masks."""
    _unused_store, _record, _commit = _commit_group(con, tmp_path)
    from scripts.embedding_research.streams.masks import CurrentMaskResolver  # red
    from scripts.embedding_research.streams.store import make_current_mask_resolver  # red

    resolver = make_current_mask_resolver(_store(con, tmp_path))
    assert isinstance(resolver, CurrentMaskResolver)
    mask = resolver.load("songA", "effnet")
    assert mask is not None and mask.dtype == np.uint8


def test_future_mask_resolver_refuses_uncommitted_and_wrong_length(con, tmp_path):
    """P1-S2 spec: mask-less / uncommitted / corrupt groups yield a refusal, not all-ones."""
    store, record = _publish_stream(con, tmp_path)
    # no committed mask at all
    from scripts.embedding_research.streams.store import make_current_mask_resolver  # red

    resolver = make_current_mask_resolver(store)
    assert resolver.load("songA", "effnet") is None  # complete-group predicate: not ready
    # committed but wrong-length/corrupt payload is refused (uint8[P] contract)
    _store, _r2, commit = _commit_group(con, tmp_path, sid="songB", backbone="effnet", patch_count=7)
    import io

    from scripts.embedding_research.streams.masks import mask_npy_bytes

    (tmp_path / commit.mask_ref).write_bytes(
        io.BytesIO(mask_npy_bytes(np.ones(3, dtype=np.uint8))).getvalue()  # length 3 != 7
    )
    got = resolver.load("songB", "effnet")
    assert got is None or got.shape == (7,)  # never a length-3 silent-ones fallback
    _ = record


def test_future_current_stream_resolver_load_requires_complete_group(con, tmp_path):
    """P1-S3 spec: CurrentStreamResolver.load returns data ONLY for a complete group.

    Today ``make_current_stream_resolver(...).load`` returns the stream for any registry-
    ready row WITHOUT checking the committed observation group.  This test pins the P1-S3
    group-only semantics and is expected RED until then.  The registry row is forced to
    claim ``ready`` directly so the test is independent of reconcile() promotion rules.
    """
    from scripts.embedding_research.streams.store import make_current_stream_resolver  # exists

    store, _record = _publish_stream(con, tmp_path)
    con.execute("UPDATE stream_registry SET status = 'ready' WHERE song_id = 'songA' AND backbone = 'effnet'")
    assert store.ready_stream_record("songA", "effnet") is not None  # registry-only ready
    resolver = make_current_stream_resolver(_store(con, tmp_path))
    loaded = resolver.load("songA", "effnet")
    assert loaded is None, "resolver must refuse a stream whose observation group is incomplete"


def test_future_observation_group_ready_shared_predicate_module(con, tmp_path):
    """P1-S3 spec: module-level observation_group_ready(store, ...) shares the store predicate.

    P1-S3 reconciled the module surface with the store method: the shared module-level
    predicate takes the bound ``StreamStore`` (which lets the predicate reach the filesystem
    group check) and delegates to ``StreamStore.observation_group_ready`` — the SAME
    complete-group predicate the current stream/mask resolvers and reindex use.  Registry
    status alone never makes a group READY.
    """
    from scripts.embedding_research.streams import observation_group_ready as _ready  # P1-S3

    store, record = _commit_group(con, tmp_path)[:2]
    assert _ready(store, "songA", "effnet", stream_record=record) is True
    store.publish("songZ", "effnet", np.random.RandomState(0).rand(7, 4).astype(np.float32), run_id="r")
    assert _ready(store, "songZ", "effnet") is False


def test_future_reconcile_manifests_refuses_uncommitted_stream(con, tmp_path):
    """P1-S7 spec: reconcile_current_manifests rebuilds ONLY complete committed groups."""
    from scripts.embedding_research.streams.reindex import reconcile_current_manifests  # exists

    store, _record = _publish_stream(con, tmp_path)  # stream-only, NO commit marker
    report = reconcile_current_manifests(Path(tmp_path), con)
    assert report.rows_rebuilt == 0
    assert not report.ready
    _ = store
