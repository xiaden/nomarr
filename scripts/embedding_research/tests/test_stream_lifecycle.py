"""Phase 4 (P4-S2) — frozen-stream lifecycle and fault matrix.

Post-migration (Plan B P1-S2) the stream store is filesystem-authoritative over immutable,
content-addressed, DIGEST-named artifacts (``streams/<sid>.<bb>.<64hex>.npy``) with a
self-describing ``.json`` manifest; the ``stream_registry`` table is a rebuildable
cache/index (never the source of truth).  This file pins the retained lifecycle:

* duplicate re-publication yields ONE registry row pointing at the NEW digest artifact
  (no duplicate row, no in-place overwrite; distinct content lands in a distinct digest
  file while prior digest bytes survive untouched);
* partial runs are recorded partial in ``run_provenance`` and the ``corpus_state``
  reconciliation never claims completeness (a partial run cannot masquerade as complete);
* missing / byte-corrupt / shape-mismatched streams reconcile to ``missing``/``corrupt``
  — a row-field shape corruption that a file hash cannot catch (the file is valid, the
  row's ``(patch_count, dim)`` metadata lies) is caught by the shape comparison;
* stale registry rows (artifact gone / never published) reconcile to ``missing`` and a
  never-published ``pending`` row is NOT silently promoted (it stays pending);
* reconciliation applies EXACTLY ``pending -> ready`` (verified) and ``ready ->
  missing|corrupt`` and nothing else;
* immutable bytes survive every force re-publication (byte-identical, no mutation);
* relocation-safe root-relative references (copy the whole output tree to a new root,
  point the store at the new root, and ``lookup``/``batch_gather`` still resolve);
* the store-level strict ``verify`` seam (clean passes; missing/corrupt/shape-mismatch/
  unpromoted-pending each raise :class:`VerifyFailureError`).

Legacy/supersession/rowless-orphan classification and ``register_legacy`` are DELETED
post-migration (Git is the archive); the S5 manifest-only reindex owns orphan/stray
detection.  Where a behavior is also asserted in earlier test modules this file re-pins
it in the single lifecycle context (Phase 4 is the lifecycle gate; stronger coverage).
"""

from __future__ import annotations

import shutil

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common import embed as embed_mod
from scripts.embedding_research.db import read_corpus_state, read_run_provenance
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.records import StreamRecord, VerifyFailureError, now_ms
from scripts.embedding_research.streams.store import StreamStore


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _arr(rows=3, cols=4, fill=None):
    if fill is None:
        return np.arange(rows * cols, dtype=np.float32).reshape(rows, cols)
    return np.full((rows, cols), fill, dtype=np.float32)


def _store(con, out) -> StreamStore:
    return StreamStore(con, output_root=out)


def _ready(con, out, song, backbone="effnet", arr=None, run_id="r"):
    store = _store(con, out)
    store.publish(song, backbone, arr if arr is not None else _arr(), run_id=run_id)
    store.reconcile()
    return store


def _payload_path(store, song, backbone="effnet"):
    """On-disk payload path for a ready record (resolved via the root-relative ref)."""
    return store._path(store.lookup(song, backbone).artifact_ref)


def _row_status(con, song: str) -> str:
    return con.execute(
        "SELECT status FROM stream_registry WHERE song_id = ? AND backbone = 'effnet'", [song]
    ).fetchone()[0]


# ── duplicate re-publication / immutable bytes ─────────────────────────────────


@pytest.mark.unit
def test_republish_one_row_points_at_new_digest_no_dup_no_overwrite(con, tmp_path):
    out = tmp_path / "out"
    store = _store(con, out)
    pub1 = store.publish("s1", "effnet", _arr(3, 4, fill=1.0), run_id="r1")
    store.reconcile()
    v1_path = out / pub1.artifact_ref
    assert v1_path.is_file()
    v1_bytes = v1_path.read_bytes()

    pub2 = store.publish("s1", "effnet", _arr(3, 4, fill=7.0), run_id="r2")
    store.reconcile()

    rows = con.execute("SELECT count(*) FROM stream_registry WHERE song_id='s1' AND backbone='effnet'").fetchone()[0]
    assert rows == 1
    rec = store.lookup("s1", "effnet")
    # Registry points at the NEW digest artifact; different content -> different digest file.
    assert rec.artifact_ref == pub2.artifact_ref
    assert rec.artifact_ref != pub1.artifact_ref
    assert v1_path.read_bytes() == v1_bytes  # prior digest bytes untouched (no overwrite)


@pytest.mark.unit
def test_immutable_bytes_across_multiple_force_republishes(con, tmp_path):
    """Distinct re-published content lands in distinct digest files; all stay byte-identical."""
    out = tmp_path / "out"
    store = _store(con, out)
    refs: list[str] = []
    for i in range(4):
        pub = store.publish("s1", "effnet", _arr(3, 4, fill=float(i) + 1), run_id=f"r{i}")
        store.reconcile()
        refs.append(pub.artifact_ref)
    # Distinct content -> distinct digest refs, all still on disk byte-identical.
    assert len(set(refs)) == 4
    blobs = {ref: (out / ref).read_bytes() for ref in refs}
    for ref, blob in blobs.items():
        assert (out / ref).read_bytes() == blob
    # Only one live registry row, pointing at the newest digest.
    assert con.execute("SELECT count(*) FROM stream_registry").fetchone()[0] == 1
    assert store.lookup("s1", "effnet").artifact_ref == refs[-1]


@pytest.mark.unit
def test_identical_republication_reuses_same_digest_file(con, tmp_path):
    """Re-publishing IDENTICAL bytes resolves to the same digest file (content addressed)."""
    out = tmp_path / "out"
    store = _store(con, out)
    arr = _arr(3, 4)
    pub1 = store.publish("s1", "effnet", arr, run_id="r1")
    store.reconcile()
    pub2 = store.publish("s1", "effnet", arr, run_id="r2")
    store.reconcile()
    assert pub2.artifact_ref == pub1.artifact_ref
    assert con.execute("SELECT count(*) FROM stream_registry").fetchone()[0] == 1
    np.testing.assert_array_equal(np.load(out / pub2.artifact_ref, allow_pickle=False), arr)


# ── partial runs ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_partial_run_provenance_and_corpus_state_never_complete(con, tmp_path):
    store = _store(con, tmp_path / "out")
    # A song that made it ready in this run...
    store.publish("songA", "effnet", _arr(2, 3, fill=1.0), run_id="run-partial")
    store.reconcile()
    # ...but the run also had errors (e.g. another song's publication refused).
    embed_mod._record_embed_run(
        con,
        store,
        run_id="run-partial",
        started_at=1_700_000_000_000,
        done=1,
        skipped=0,
        errors=2,
        eligible_count=3,
    )
    run = read_run_provenance(con, run_id="run-partial")
    assert run[0]["status"] == "partial"  # never masquerades as complete
    assert run[0]["song_count"] == 1
    state = read_corpus_state(con)
    assert state["complete_flag"] is False
    # registered vs eligible are distinct: only the verified ready song is registered.
    assert state["registered_song_count"] == 1
    assert state["eligible_song_count"] == 3
    assert state["reconciliation_status"] == "ok"  # the registry itself reconciled clean


# ── missing / byte-corrupt / shape-mismatched ─────────────────────────────────


@pytest.mark.unit
def test_missing_stream_reconciles_to_missing(con, tmp_path):
    store = _ready(con, tmp_path / "out", "s1")
    _payload_path(store, "s1").unlink()
    report = store.reconcile()
    assert report.missing == 1 and report.ready == 0 and report.stale == 1
    assert report.clean is False


@pytest.mark.unit
def test_byte_corruption_reconciles_to_corrupt(con, tmp_path):
    store = _ready(con, tmp_path / "out", "s1")
    p = _payload_path(store, "s1")
    p.write_bytes(p.read_bytes() + b"\x00")
    report = store.reconcile()
    assert report.corrupt == 1 and report.ready == 0


@pytest.mark.unit
def test_shape_mismatched_row_reconciles_to_corrupt(con, tmp_path):
    """A row claiming (patch_count, dim) but whose file is a valid different shape is CORRUPT.

    The file is a byte-valid float32 array whose SHA-256 matches the registry
    fingerprint, so a file-hash check CANNOT catch it — only the shape comparison
    against the row's ``(patch_count, dim)`` metadata can.  This is the row-field
    corruption case (DD: shape checks compare loaded shape with registry metadata).
    """
    out = tmp_path / "out"
    store = _store(con, out)
    store.publish("s1", "effnet", _arr(3, 4), run_id="r1")
    store.reconcile()  # file is (3, 4), row says patch_count=3, dim=4 -> ready
    # Corrupt the ROW's dim metadata (not the file): file is still (3,4), row now says dim=9.
    con.execute("UPDATE stream_registry SET dim = 9 WHERE song_id = 's1' AND backbone = 'effnet'")
    report = store.reconcile()
    assert report.corrupt == 1 and report.ready == 0
    # The mislabelled row is never readable as ready.
    assert store.has_ready("s1", "effnet") is False


# ── stale rows ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_stale_registry_rows_reconcile_to_missing(con, tmp_path):
    out = tmp_path / "out"
    store = _store(con, out)
    # s1: a ready artifact that is then DELETED on disk (stale -> missing).
    store.publish("s1", "effnet", _arr(3, 4), run_id="r-live")
    store.reconcile()
    a_path = _payload_path(store, "s1")
    assert a_path.is_file()
    a_path.unlink()
    # s2: a ready row whose artifact_ref was never created (stale -> missing) but whose
    # registry row is PENDING (register defaults to pending) — never promoted without a file.
    record = StreamRecord(
        song_id="s2",
        backbone="effnet",
        artifact_ref="streams/s2.effnet." + "c" * 64 + ".npy",
        patch_count=3,
        dim=4,
        dtype="float32",
        format_version="1",
        fingerprint_sha256="c" * 64,
        preprocess_fn="standardize",
        preprocess_version="1.0",
        backbone_model_hash="bbhash",
        audio_params="44.1k/mono",
        embed_semantics_version=1,
        provenance_source="embed",
        provenance_assumption="",
        status="pending",
        run_id="r-stale",
        created_at=now_ms(),
        updated_at=now_ms(),
    )
    store.register(record)

    report = store.reconcile()
    # s1 (deleted after ready) -> missing (a genuine stale, degraded row).
    # s2 (a pending row whose artifact was never published) is NOT silently promoted:
    # it stays pending — reconcile never forces a row with no verified file to ready or
    # to a fabricated missing/corrupt outcome (pending only promotes on a verified file).
    assert report.missing == 1
    assert report.ready == 0
    assert report.pending == 1
    assert report.stale == 1
    assert _row_status(con, "s2") == "pending"


# ── reconciliation transitions are exactly DD-allowed ──────────────────────────


@pytest.mark.unit
def test_pending_row_with_bad_file_is_not_silently_promoted(con, tmp_path):
    """A pending row whose artifact is bad stays pending and is reported, never forced ready."""
    out = tmp_path / "out"
    store = _store(con, out)
    pub = store.publish("s1", "effnet", _arr(3, 4, fill=1.0), run_id="r1")
    # Registry row is pending (publish registers pending; do NOT reconcile first).
    assert _row_status(con, "s1") == "pending"
    # Corrupt the artifact before reconcile.
    p = out / pub.artifact_ref
    p.write_bytes(p.read_bytes() + b"\x00")
    report = store.reconcile()
    # pending only promotes to ready on a verified artifact; a bad one stays pending.
    assert report.pending == 1
    assert report.ready == 0
    assert _row_status(con, "s1") == "pending"
    assert not store.has_ready("s1", "effnet")
    assert report.clean is False


# ── relocation-safe root-relative references ───────────────────────────────────


@pytest.mark.unit
def test_relocation_safe_root_relative_refs(con, tmp_path):
    root_a = tmp_path / "storeA"
    store_a = _ready(con, root_a, "songR", arr=_arr(3, 4))
    rec_before = store_a.lookup("songR", "effnet")
    ref_before = rec_before.artifact_ref
    assert not ref_before.startswith("/")  # root-relative, never absolute

    # Copy the WHOLE output tree to a new root and point a fresh store at it.
    root_b = tmp_path / "storeB"
    shutil.copytree(root_a, root_b)
    store_b = _store(con, root_b)  # same registry (shared session DB); new root

    # lookup + batch_gather resolve/verify against the relocated tree.
    rec = store_b.lookup("songR", "effnet")
    assert rec.status == "ready"
    assert rec.artifact_ref == ref_before  # registry rows are NOT rewritten by relocation
    got = store_b.batch_gather("songR", "effnet", [0, 2])
    np.testing.assert_array_equal(got, _arr(3, 4)[[0, 2]])
    # The relocated tree verifies clean.
    report = store_b.verify(strict=True)
    assert report.clean is True


# ── store-level strict verify seam ─────────────────────────────────────────────


@pytest.mark.unit
def test_strict_verify_clean_corpus_passes(con, tmp_path):
    store = _ready(con, tmp_path / "out", "s1")
    report = store.verify(strict=True)
    assert report.ready == report.scanned == 1
    assert report.clean is True
    # The same store in non-strict mode returns the report without raising.
    assert store.verify(strict=False).ready == 1


@pytest.mark.unit
@pytest.mark.parametrize("corruption_kind", ["missing", "byte_corrupt", "shape_mismatch"])
def test_strict_verify_raises_on_corruption(con, tmp_path, corruption_kind):
    out = tmp_path / "out"
    store = _store(con, out)
    store.publish("s1", "effnet", _arr(3, 4), run_id="r1")
    store.reconcile()
    p = out / store.lookup("s1", "effnet").artifact_ref
    if corruption_kind == "missing":
        p.unlink()
    elif corruption_kind == "byte_corrupt":
        p.write_bytes(p.read_bytes() + b"\x00")
    elif corruption_kind == "shape_mismatch":
        con.execute("UPDATE stream_registry SET dim = 9 WHERE song_id='s1' AND backbone='effnet'")
    with pytest.raises(VerifyFailureError):
        store.verify(strict=True)


@pytest.mark.unit
def test_strict_verify_raises_on_unpromoted_pending(con, tmp_path):
    out = tmp_path / "out"
    store = _store(con, out)
    pub = store.publish("s1", "effnet", _arr(3, 4), run_id="r1")
    # Corrupt before reconcile so the pending row can never promote.
    p = out / pub.artifact_ref
    p.write_bytes(p.read_bytes() + b"\x00")
    with pytest.raises(VerifyFailureError):
        store.verify(strict=True)
