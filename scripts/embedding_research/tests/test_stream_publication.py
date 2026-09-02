"""Phase 2 tests for immutable durable publication, supersession and legacy handling.

Covers P2-S1 (staged fsync/rename publication order through the write-proxy seam), P2-S2
(transactional pending registration -> reconcile lifecycle, immutable supersession, legacy
classification) and the staging ``.tmp`` file-level condition.  Uses the ``con`` fixture
(schema applied) plus pytest ``tmp_path`` for isolated artifact output.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.streams import DuplicateStreamError, StreamNotFoundError, StreamNotReadyError
from scripts.embedding_research.streams.publication import RecordingFileOps
from scripts.embedding_research.streams.store import StreamStore


def _store(con, tmp_path) -> StreamStore:
    return StreamStore(con, output_root=tmp_path / "out")


def _patches(tmp_path):
    return tmp_path / "out" / "patches"


def _arr(rows=2, cols=3):
    return np.arange(rows * cols, dtype=np.float32).reshape(rows, cols)


@pytest.mark.unit
def test_publish_records_exact_durable_write_order(con, tmp_path):
    """The recording write-proxy sees fsync(file) -> close -> rename -> fsync(dir)."""
    store = _store(con, tmp_path)
    recorder = RecordingFileOps()
    store.publish("song1", "effnet", _arr(), run_id="r1", file_ops=recorder)

    assert recorder.order == [
        ("fsync", "file"),
        ("close", "file"),
        ("rename", "file"),
        ("fsync", "dir"),
    ]
    # Post-success: no .tmp leftover in the staging dir.
    staging = _patches(tmp_path) / ".staging"
    assert not staging.exists() or not list(staging.glob("*.tmp"))


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
def test_force_republication_keeps_old_bytes_and_supersedes(con, tmp_path):
    """Re-publishing an identity writes a NEW versioned artifact; v1 bytes survive.

    Reconcile reports v1 as superseded (not corrupt/stray), and the registry holds exactly
    one row pointing at v2.
    """
    store = _store(con, tmp_path)
    v1 = _arr(rows=2, cols=3)
    store.publish("song1", "effnet", v1, run_id="r1")
    store.reconcile()
    v1_path = _patches(tmp_path) / "song1.effnet.npy"
    v1_bytes = v1_path.read_bytes()

    v2 = np.full((2, 3), 7.0, dtype=np.float32)
    store.publish("song1", "effnet", v2, run_id="r2")
    store.reconcile()

    # Immutability: v1 bytes on disk are byte-identical to what we published.
    assert v1_path.exists()
    assert v1_path.read_bytes() == v1_bytes
    # Registry points at the versioned v2 artifact; exactly one row for the identity.
    rows = con.execute(
        "SELECT artifact_ref FROM stream_registry WHERE song_id = 'song1' AND backbone = 'effnet'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "patches/song1.effnet.v2.npy"
    record = store.lookup("song1", "effnet")
    assert record.artifact_ref == "patches/song1.effnet.v2.npy"

    report = store.reconcile()
    assert report.ready == 1
    assert report.superseded == 1
    assert report.orphan == 1
    assert report.corrupt == 0
    assert report.stray == 0
    # v2 bytes are the newly-published ones.
    np.testing.assert_array_equal(np.load(store._path(record.artifact_ref), allow_pickle=False), v2)


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
def test_legacy_bare_file_reconciles_to_legacy_never_ready(con, tmp_path):
    """A bare canonical pre-registry file with no row is reported as legacy, not auto-adopted."""
    store = _store(con, tmp_path)
    patches = _patches(tmp_path)
    patches.mkdir(parents=True, exist_ok=True)
    legacy_arr = np.ones((2, 3), dtype=np.float32)
    np.save(patches / "song-legacy.effnet.npy", legacy_arr)

    report = store.reconcile()
    assert report.scanned == 0
    assert report.legacy == 1
    assert report.orphan == 1
    assert report.clean is False
    # The identity is not registered and not readable.
    assert not store.has_ready("song-legacy", "effnet")
    with pytest.raises(StreamNotFoundError):
        store.lookup("song-legacy", "effnet")


@pytest.mark.unit
def test_explicit_legacy_registration_marks_provenance_and_is_never_complete(con, tmp_path):
    """register_legacy records provenance_source='legacy' + an explicit assumption."""
    store = _store(con, tmp_path)
    patches = _patches(tmp_path)
    patches.mkdir(parents=True, exist_ok=True)
    legacy_arr = np.ones((2, 3), dtype=np.float32)
    np.save(patches / "song-legacy.effnet.npy", legacy_arr)

    record = store.register_legacy(
        "song-legacy",
        "effnet",
        run_id="legacy-adopt",
        provenance_assumption="bare pre-registry sidecar from prior run; provenance unknown",
    )
    assert record.provenance_source == "legacy"
    assert record.provenance_assumption
    assert record.status == "ready"

    read_back = store.lookup("song-legacy", "effnet")
    assert read_back.provenance_source == "legacy"
    assert read_back.provenance_assumption
    # Legacy is readable (ready) but never provenance-complete.
    assert read_back.provenance_source != "embed"
    np.testing.assert_array_equal(store.batch_gather("song-legacy", "effnet", [0, 1]), legacy_arr)

    # A duplicate legacy registration for an already-registered identity is rejected.
    with pytest.raises(DuplicateStreamError):
        store.register_legacy(
            "song-legacy",
            "effnet",
            run_id="legacy-adopt-2",
            provenance_assumption="duplicate attempt",
        )


@pytest.mark.unit
def test_force_reembed_of_legacy_identity_supersedes_but_legacy_bytes_survive(con, tmp_path):
    """Re-embedding a legacy-occupied identity publishes a versioned provenance-complete
    artifact while the legacy bytes remain (reconcile reports superseded, not legacy)."""
    store = _store(con, tmp_path)
    patches = _patches(tmp_path)
    patches.mkdir(parents=True, exist_ok=True)
    legacy_arr = np.full((2, 3), 1.0, dtype=np.float32)
    legacy_path = patches / "song-legacy.effnet.npy"
    np.save(legacy_path, legacy_arr)
    legacy_bytes = legacy_path.read_bytes()

    store.register_legacy(
        "song-legacy",
        "effnet",
        run_id="adopt",
        provenance_assumption="bare pre-registry sidecar; provenance unknown",
    )
    # Force re-embed publishes a provenance-complete artifact at a versioned ref.
    new_arr = np.full((2, 3), 5.0, dtype=np.float32)
    store.publish("song-legacy", "effnet", new_arr, run_id="embed-forced")
    store.reconcile()

    new_record = store.lookup("song-legacy", "effnet")
    assert new_record.provenance_source == "embed"
    assert new_record.artifact_ref == "patches/song-legacy.effnet.v2.npy"
    # Legacy bytes survive byte-identically on disk.
    assert legacy_path.read_bytes() == legacy_bytes
    report = store.reconcile()
    assert report.ready == 1
    assert report.superseded == 1
    assert report.legacy == 0


@pytest.mark.unit
def test_staging_tmp_leftover_is_file_level_not_registry_state(con, tmp_path):
    """A .staging/*.tmp leftover is ignored by reconcile (never counted, never a state)."""
    store = _store(con, tmp_path)
    store.publish("song1", "effnet", _arr(), run_id="r1")
    staging = _patches(tmp_path) / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "song1.effnet.npy.tmp").write_bytes(b"partial")

    report = store.reconcile()
    assert report.ready == 1
    assert report.clean is True
    assert report.orphan == 0
    assert report.legacy == 0
    assert report.stray == 0
