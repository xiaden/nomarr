"""Post-migration tests for immutable digest publication (Plan B P1-S2).

Covers the staged fsync/rename publication order through the write-proxy seam (payload
then manifest, each fsync(file) -> close -> rename -> fsync(dir)), the transactional
pending-registration -> reconcile lifecycle, immutable content-addressed digest naming
(no byte replacement, no ``.vN`` supersession), filesystem-authoritative reconciliation
and the staging ``.tmp`` file-level condition.  Uses the ``con`` fixture (schema applied)
plus pytest ``tmp_path`` for isolated artifact output under ``<root>/out/streams``.

Legacy/supersession concepts are deleted post-migration: a re-published identity points
at a NEW digest-named artifact while the OLD digest bytes survive untouched (both are
immutable, content-addressed) and the registry row simply moves.  Rowless-orphan
classification (legacy/superseded/stray) is NOT a reconcile concern here.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.embedding_research.streams import StreamNotReadyError
from scripts.embedding_research.streams.publication import RecordingFileOps, parse_artifact_name
from scripts.embedding_research.streams.store import StreamStore

_STAGING = ".staging"


def _store(con, tmp_path) -> StreamStore:
    return StreamStore(con, output_root=tmp_path / "out")


def _streams(tmp_path):
    return tmp_path / "out" / "streams"


def _arr(rows=2, cols=3):
    return np.arange(rows * cols, dtype=np.float32).reshape(rows, cols)


def _digest_name(artifact_ref: str) -> str:
    return artifact_ref.rsplit("/", 1)[-1]


@pytest.mark.unit
def test_publish_records_exact_durable_write_order(con, tmp_path):
    """The recording write-proxy sees payload then manifest, each fsync->close->rename->fsync(dir).

    Post-migration publication writes the digest-named ``.npy`` payload AND its
    self-describing ``.json`` manifest as two independent durable sequences.
    """
    store = _store(con, tmp_path)
    recorder = RecordingFileOps()
    store.publish("song1", "effnet", _arr(), run_id="r1", file_ops=recorder)

    one_durable = [
        ("fsync", "file"),
        ("close", "file"),
        ("rename", "file"),
        ("fsync", "dir"),
    ]
    assert recorder.order == one_durable + one_durable
    # Post-success: no .tmp leftover in the staging dir.
    staging = _streams(tmp_path) / _STAGING
    assert not staging.exists() or not list(staging.glob("*.tmp"))


@pytest.mark.unit
def test_publish_uses_digest_grammar_and_writes_manifest(con, tmp_path):
    """publish names the artifact ``<sid>.<bb>.<64hex>.npy`` and writes a manifest sibling."""
    store = _store(con, tmp_path)
    rec = store.publish("song1", "effnet", _arr(), run_id="r1")
    name = _digest_name(rec.artifact_ref)
    # Strict digest grammar: dot-free song, backbone, 64 lowercase hex, no bare/.vN.
    parsed = parse_artifact_name(name, ".npy")
    assert parsed is not None
    assert parsed.song_id == "song1"
    assert parsed.backbone == "effnet"
    assert parsed.digest == rec.fingerprint_sha256
    # Payload + manifest both exist on disk.
    payload = store._path(rec.artifact_ref)
    assert payload.is_file()
    manifest = store._path(rec.artifact_ref[:-4] + ".json")
    assert manifest.is_file()
    data = json.loads(manifest.read_text())
    assert data["kind"] == "stream"
    assert data["payload_sha256"] == rec.fingerprint_sha256
    assert data["byte_size"] == payload.stat().st_size


@pytest.mark.unit
def test_publish_then_reconcile_promotes_pending_to_ready(con, tmp_path):
    """publish registers a pending row; reconcile promotes it to ready."""
    store = _store(con, tmp_path)
    store.publish("song1", "effnet", _arr(), run_id="r1")

    with pytest.raises(StreamNotReadyError):
        store.lookup("song1", "effnet")

    report = store.reconcile()
    assert report.scanned == 1
    assert report.pending == 0
    assert report.ready == 1
    assert report.clean is True

    record = store.lookup("song1", "effnet")
    assert record.status == "ready"
    np.testing.assert_array_equal(store.batch_gather("song1", "effnet", [0, 1]), _arr())


@pytest.mark.unit
def test_row_without_file_reconciles_to_missing(con, tmp_path):
    """A ready row whose artifact file disappears reconciles to missing."""
    store = _store(con, tmp_path)
    store.publish("song1", "effnet", _arr(), run_id="r1")
    store.reconcile()
    (store._path(store.lookup("song1", "effnet").artifact_ref)).unlink()

    report = store.reconcile()
    assert report.ready == 0
    assert report.missing == 1
    assert report.clean is False


@pytest.mark.unit
def test_corrupt_bytes_reconcile_to_corrupt(con, tmp_path):
    """A ready row whose bytes are tampered (hash mismatch) reconciles to corrupt."""
    store = _store(con, tmp_path)
    store.publish("song1", "effnet", _arr(), run_id="r1")
    store.reconcile()
    path = store._path(store.lookup("song1", "effnet").artifact_ref)
    with open(path, "ab") as handle:
        handle.write(b"\x00")

    report = store.reconcile()
    assert report.ready == 0
    assert report.corrupt == 1
    assert report.clean is False


@pytest.mark.unit
def test_force_republication_keeps_old_digest_bytes_and_moves_one_row(con, tmp_path):
    """Re-publishing an identity writes a NEW digest-named artifact; the old digest survives.

    Content addressing means identical bytes reuse one artifact and different bytes land in
    a different digest file.  The registry holds exactly one row pointing at the newest
    digest; there is no ``.vN`` supersession and no ``superseded`` reconcile count.
    """
    store = _store(con, tmp_path)
    v1 = _arr(rows=2, cols=3)
    pub1 = store.publish("song1", "effnet", v1, run_id="r1")
    store.reconcile()
    v1_path = store._path(pub1.artifact_ref)
    v1_bytes = v1_path.read_bytes()

    v2 = np.full((2, 3), 7.0, dtype=np.float32)
    pub2 = store.publish("song1", "effnet", v2, run_id="r2")
    store.reconcile()

    # Immutability: v1 digest bytes on disk are byte-identical to what we published.
    assert v1_path.exists()
    assert v1_path.read_bytes() == v1_bytes
    # Different content -> a different digest file.
    assert pub2.artifact_ref != pub1.artifact_ref
    assert store._path(pub2.artifact_ref).is_file()

    # Registry points at the newest digest; exactly one row for the identity.
    rows = con.execute(
        "SELECT artifact_ref FROM stream_registry WHERE song_id = 'song1' AND backbone = 'effnet'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pub2.artifact_ref
    record = store.lookup("song1", "effnet")
    assert record.artifact_ref == pub2.artifact_ref

    report = store.reconcile()
    assert report.ready == 1
    assert report.orphan == 0
    assert report.corrupt == 0
    np.testing.assert_array_equal(np.load(store._path(record.artifact_ref), allow_pickle=False), v2)


@pytest.mark.unit
def test_identical_republication_reuses_same_digest_artifact(con, tmp_path):
    """Identical bytes re-published resolve to the same digest name (content addressed)."""
    store = _store(con, tmp_path)
    arr = _arr(rows=2, cols=3)
    pub1 = store.publish("song1", "effnet", arr, run_id="r1")
    store.reconcile()
    pub2 = store.publish("song1", "effnet", arr, run_id="r2")
    store.reconcile()
    assert pub2.artifact_ref == pub1.artifact_ref
    # Still exactly one registry row.
    count = con.execute(
        "SELECT count(*) FROM stream_registry WHERE song_id = 'song1' AND backbone = 'effnet'"
    ).fetchone()[0]
    assert count == 1


@pytest.mark.unit
def test_republication_never_leaves_duplicate_rows(con, tmp_path):
    """Re-publishing an identity leaves exactly one registry row (delete-then-insert)."""
    store = _store(con, tmp_path)
    store.publish("song1", "effnet", _arr(), run_id="r1")
    store.publish("song1", "effnet", np.full((2, 3), 2.0, dtype=np.float32), run_id="r2")
    count = con.execute(
        "SELECT count(*) FROM stream_registry WHERE song_id = 'song1' AND backbone = 'effnet'"
    ).fetchone()[0]
    assert count == 1


@pytest.mark.unit
def test_staging_tmp_leftover_is_file_level_not_registry_state(con, tmp_path):
    """A .staging/*.tmp leftover is ignored by reconcile (never counted, never a state)."""
    store = _store(con, tmp_path)
    store.publish("song1", "effnet", _arr(), run_id="r1")
    staging = _streams(tmp_path) / _STAGING
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "song1.effnet.tmp").write_bytes(b"partial")

    report = store.reconcile()
    assert report.ready == 1
    assert report.clean is True
    assert report.orphan == 0
