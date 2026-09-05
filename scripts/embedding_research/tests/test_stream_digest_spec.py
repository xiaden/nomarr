"""Plan B P1-S2 — spec-first coverage for the digest-only immutable stream core.

Pins the post-migration invariants that make stream/head artifacts self-describing,
content-addressed filesystem objects while the registry stays a rebuildable cache:

* the ONLY accepted artifact grammar is ``<sid>.<backbone>.<64-lowercase-hex><suffix>``
  (``parse_artifact_name`` returns a typed identity; bare ``<sid>.<bb>.npy`` and legacy
  ``.vN`` names are REJECTED);
* ``publish`` writes a digest-named payload whose SHA-256 equals ``fingerprint_sha256``
  and a self-describing ``.json`` manifest sibling (kind / schema_version / payload_sha256 /
  byte_size / logical identity / patch_count), readable back without the registry;
* no byte replacement at an existing digest (the write-proxy ``durable_write_if_absent``
  refuses to overwrite an existing file whose bytes differ from the digest-encoded sha);
* the new S3-oriented record types (``MaskRecord``, ``ObservationCommit``) and the
  ``ReindexReport`` reject invalid logical/root-relative identity; and
* a registry-ready stream's manifest is the filesystem-authoritative record that a later
  reindex can reconstruct the ready row from.

Live mask production and embed-integrated stream+mask observation-group publication land in
P1-S3; the types + commit-marker machinery covered here are the S2 foundation.
"""

from __future__ import annotations

import json

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.publication import (
    durable_write_if_absent,
    parse_artifact_name,
)
from scripts.embedding_research.streams.records import (
    MaskRecord,
    ObservationCommit,
    ReindexReport,
    payload_to_manifest_ref,
)
from scripts.embedding_research.streams.store import StreamStore


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _arr(rows=3, cols=4):
    return np.arange(rows * cols, dtype=np.float32).reshape(rows, cols)


# ── digest-only artifact grammar ────────────────────────────────────────────────


@pytest.mark.unit
def test_parse_artifact_name_accepts_only_digest_grammar():
    digest = "a" * 64
    parsed = parse_artifact_name(f"s1.effnet.{digest}.npy", ".npy")
    assert parsed is not None
    assert (parsed.song_id, parsed.backbone, parsed.digest) == ("s1", "effnet", digest)
    assert parsed.family == "digest"
    # Bare pre-migration and .vN versioned names are NOT valid post-migration grammar.
    assert parse_artifact_name("s1.effnet.npy", ".npy") is None
    assert parse_artifact_name(f"s1.effnet.{digest}.v3.npy", ".npy") is None
    # Malformed digests (wrong length / non-hex) are rejected.
    assert parse_artifact_name("s1.effnet." + "z" * 64 + ".npy", ".npy") is None
    assert parse_artifact_name("s1.effnet.abcd.npy", ".npy") is None


@pytest.mark.unit
def test_publish_payload_digest_is_content_sha_and_matches_grammar(con, tmp_path):
    store = StreamStore(con, output_root=tmp_path / "out")
    arr = _arr()
    rec = store.publish("song1", "effnet", arr, run_id="r1")
    # The artifact name is exactly the digest grammar and the digest == payload sha.
    assert rec.artifact_ref.startswith("streams/song1.effnet.")
    assert rec.artifact_ref.endswith(".npy")
    parsed = parse_artifact_name(rec.artifact_ref.rsplit("/", 1)[-1], ".npy")
    assert parsed is not None
    payload = store._path(rec.artifact_ref).read_bytes()
    assert _sha256(payload) == rec.fingerprint_sha256 == parsed.digest


# ── self-describing manifest (filesystem-authoritative) ────────────────────────


@pytest.mark.unit
def test_manifest_is_self_describing_and_rebuildable(con, tmp_path):
    store = StreamStore(con, output_root=tmp_path / "out")
    arr = _arr()
    rec = store.publish("song1", "effnet", arr, run_id="r1")
    store.reconcile()

    manifest_ref = payload_to_manifest_ref(rec.artifact_ref)
    assert manifest_ref == rec.artifact_ref[:-4] + ".json"
    data = json.loads((tmp_path / "out" / manifest_ref).read_text())
    # Every field a filesystem-only reindex needs to reconstruct the ready row.
    assert data["kind"] == "stream"
    assert data["schema_version"] == "1"
    assert data["payload_sha256"] == rec.fingerprint_sha256
    assert data["byte_size"] == (tmp_path / "out" / rec.artifact_ref).stat().st_size
    assert (data["song_id"], data["backbone"]) == ("song1", "effnet")
    assert data["patch_count"] == arr.shape[0]
    assert data["dim"] == arr.shape[1]
    assert data["dtype"] == "float32"
    # Manifest content is digest-deterministic: it omits publish-time cache-row bookkeeping.
    assert "created_at" not in data and "updated_at" not in data

    # The manifest alone (no registry knowledge of shape) round-trips the artifact.
    payload = np.load(tmp_path / "out" / rec.artifact_ref, allow_pickle=False)
    assert payload.shape == (data["patch_count"], data["dim"])


# ── no byte replacement at an existing digest ──────────────────────────────────


@pytest.mark.unit
def test_durable_write_if_absent_refuses_differing_bytes_at_existing_path(tmp_path):
    """Writing DIFFERENT bytes to an already-existing path is refused, never overwritten.

    The write-proxy is content-addressed: a path that already exists must already contain
    the exact digest-encoded bytes.  Attempting to place different content there (which
    would silently clobber a prior immutable artifact) raises instead of replacing.
    """
    target = tmp_path / "out.npy"
    original = b"original-payload-bytes"
    target.write_bytes(original)
    with pytest.raises(OSError, match="refusing to replace bytes at existing digest"):
        durable_write_if_absent(target, b"different-payload-bytes", ops=None)
    # The original bytes are untouched.
    assert target.read_bytes() == original


# ── S3-oriented record types (S2 foundation) ───────────────────────────────────


@pytest.mark.unit
def test_mask_record_validates_identity_and_is_uint8_1d():
    digest = "a" * 64
    rec = MaskRecord(
        song_id="s1",
        backbone="effnet",
        artifact_ref=f"audio_masks/s1.effnet.{digest}.npy",
        mask_sha256=digest,
        patch_count=128,
    )
    assert rec.dtype == "uint8"
    assert rec.dimension == 1
    # Root-relative-only artifact_ref (no absolute path, no parent traversal).
    with pytest.raises(ValueError):
        MaskRecord(
            song_id="s1",
            backbone="effnet",
            artifact_ref="/absolute/s1.effnet.npy",
            mask_sha256=digest,
            patch_count=128,
        )
    with pytest.raises(ValueError):
        MaskRecord(
            song_id="s1",
            backbone="effnet",
            artifact_ref="audio_masks/../escape.npy",
            mask_sha256=digest,
            patch_count=128,
        )
    # The mask digest must be 64 lowercase hex and song_id must be dot-free.
    with pytest.raises(ValueError):
        MaskRecord(
            song_id="s1",
            backbone="effnet",
            artifact_ref=f"audio_masks/s1.effnet.{digest}.npy",
            mask_sha256="zzzz",
            patch_count=128,
        )
    with pytest.raises(ValueError):
        MaskRecord(
            song_id="s1.with.dot",
            backbone="effnet",
            artifact_ref=f"audio_masks/s1.with.dot.effnet.{digest}.npy",
            mask_sha256=digest,
            patch_count=128,
        )


@pytest.mark.unit
def test_observation_commit_validates_logical_group_identity():
    digest = "b" * 64
    commit = ObservationCommit(
        song_id="s1",
        backbone="effnet",
        stream_ref=f"streams/s1.effnet.{digest}.npy",
        mask_ref=f"audio_masks/s1.effnet.{digest}.npy",
        commit_sha256="c" * 64,
    )
    assert commit.status == "ready"
    # The commit marker is content-digest named (its own 64-hex digest).
    assert commit.commit_sha256 == "c" * 64
    # Rejects a stream ref that is not root-relative and a malformed commit digest.
    with pytest.raises(ValueError):
        ObservationCommit(
            song_id="s1",
            backbone="effnet",
            stream_ref="/abs/s1.effnet.npy",
            mask_ref=f"audio_masks/s1.effnet.{digest}.npy",
            commit_sha256="c" * 64,
        )
    with pytest.raises(ValueError):
        ObservationCommit(
            song_id="s1",
            backbone="effnet",
            stream_ref=f"streams/s1.effnet.{digest}.npy",
            mask_ref=f"audio_masks/s1.effnet.{digest}.npy",
            commit_sha256="nothex",
        )
    with pytest.raises(ValueError):
        ObservationCommit(
            song_id="s1.dotted",
            backbone="effnet",
            stream_ref=f"streams/s1.dotted.effnet.{digest}.npy",
            mask_ref=f"audio_masks/s1.dotted.effnet.{digest}.npy",
            commit_sha256="c" * 64,
        )


@pytest.mark.unit
def test_reindex_report_clean_semantics():
    assert ReindexReport().clean is False  # scanned == 0
    assert ReindexReport(scanned=3, ready=3).clean is True
    assert ReindexReport(scanned=3, ready=2).clean is False
    assert ReindexReport(scanned=3, ready=3, orphan_payloads=1).clean is False
