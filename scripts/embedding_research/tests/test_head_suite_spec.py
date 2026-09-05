"""Plan B P1-S4 — spec-first coverage for the complete aligned canonical head suite.

Pins the head-suite contract delivered by P1-S2/P1-S3 (the ``HeadStreamStore.publish``
one-digest-``.npz``-plus-manifest writer, canonical one-time inference, refusal modes,
digest/no-replace identity) and the P1-S4 manifest delta: the head manifest records
committed-stream alignment provenance (``stream_ref``/``stream_digest``) and head-set
provenance/fingerprint (``head_count``/``head_set_fingerprint``/``dataset``/
``head_set_semantics_version``) using the S3 mask-manifest precedent, with the committed
``stream_record.artifact_ref`` threaded from ``infer_heads()``/``infer_heads_for_song()``.

Coverage asserted here (all synthetic, no real corpus/model/audio):

* manifest provenance round-trip: stream ref/digest, dataset, semantics, head count,
  head-set fingerprint, model/preprocess fingerprint, and root-relative refs;
* manifest identity is manifest data, never derived from the digest filename;
* complete canonical inventory — a missing/unconfigured head refuses, no partial suite;
* exact committed-stream patch-count alignment (publication and threaded writer gates);
* finite/dimension validation (a non-finite or mis-dimensioned head refuses);
* canonical-order concatenated source-index gather returning float32 ``[N, total_dim]``;
* rerun identity — identical bytes reuse the same digest artifact AND byte-identical
  manifest (content-addressed no-replace, first-committed authoritative);
* CPU-only head reads (lookup/batch_gather make no audio/model/ONNX/CUDA call).

The P1-S4 delta does NOT change the retained ``HeadStreamStore.batch_gather`` /
``HEAD_STREAM_REGISTRY_COLUMNS`` / ``HeadStreamRecord`` contract; the additional fields
are manifest-only provenance.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import Mock

import duckdb
import numpy as np
import pytest

import scripts.embedding_research.config as config_mod
from scripts.embedding_research.common import infer_heads as infer_heads_mod
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.publication import parse_artifact_name
from scripts.embedding_research.streams.records import StreamValidationError, payload_to_manifest_ref
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

_HEAD_SET = ("gender", "timbre")


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _head_arrays(patch_count: int = 4, *, heads=_HEAD_SET, seed: int = 0, finite: bool = True):
    rng = np.random.default_rng(seed)
    arrays = {}
    for _i, head in enumerate(heads):
        arr = rng.random((patch_count, 2)).astype(np.float32)
        if not finite:
            arr[0, 0] = np.nan
        arrays[head] = arr
    return arrays


def _read_manifest(out, rec) -> dict[str, object]:
    manifest_path = out / payload_to_manifest_ref(rec.artifact_ref)
    assert manifest_path.is_file(), f"missing manifest {manifest_path}"
    return json.loads(manifest_path.read_text())


def _ready_stream(out, con, song_id: str = "s1", backbone: str = "effnet", patch_rows: int = 4) -> StreamStore:
    """Register + reconcile a ready committed backbone stream and return the store."""
    store = StreamStore(con, output_root=out)
    arr = np.arange(patch_rows * 8, dtype=np.float32).reshape(patch_rows, 8)
    store.publish(song_id, backbone, arr, run_id="run-stream")
    store.reconcile()
    rec = store.lookup(song_id, backbone)
    assert rec.status == "ready"
    return store


def _publish_heads(
    out,
    con,
    *,
    stream_ref: str = "",
    dataset: str = "",
    head_set_semantics_version: str = "1",
    heads=None,
    patch_count: int = 4,
    expected=None,
    finite: bool = True,
) -> HeadStreamStore:
    head_store = HeadStreamStore(con, output_root=out)
    head_store.publish(
        "s1",
        "effnet",
        _head_arrays(patch_count, heads=heads or _HEAD_SET, finite=finite),
        run_id="run-heads",
        patch_count=patch_count,
        alignment_version="1",
        expected_head_ids=expected if expected is not None else list(heads or _HEAD_SET),
        stream_ref=stream_ref,
        dataset=dataset,
        head_set_semantics_version=head_set_semantics_version,
    )
    return head_store


# ── manifest provenance round-trip (P1-S4 delta) ───────────────────────────────


@pytest.mark.unit
def test_head_manifest_records_stream_and_head_set_provenance(con, tmp_path):
    """The head manifest records stream alignment + head-set provenance round-trip."""
    out = tmp_path / "out"
    stream_store = _ready_stream(out, con, patch_rows=4)
    stream_rec = stream_store.lookup("s1", "effnet")
    head_store = _publish_heads(
        out,
        con,
        stream_ref=stream_rec.artifact_ref,
        dataset="gtzan",
        head_set_semantics_version="1",
        patch_count=4,
    )
    head_store.reconcile()
    rec = head_store.lookup("s1", "effnet")

    data = _read_manifest(out, rec)

    # Committed-stream alignment provenance: root-relative stream ref + parsed 64-hex digest.
    assert data["stream_ref"] == stream_rec.artifact_ref
    assert data["stream_ref"].startswith("streams/s1.effnet.")
    parsed_stream = parse_artifact_name(stream_rec.artifact_ref.rsplit("/", 1)[-1], ".npy")
    assert data["stream_digest"] == parsed_stream.digest == stream_rec.fingerprint_sha256
    assert len(data["stream_digest"]) == 64

    # Head-set provenance/fingerprint.
    assert data["head_count"] == len(_HEAD_SET)
    expected_fp = hashlib.sha256(f"{rec.head_ids}|{rec.dim_by_head}".encode()).hexdigest()
    assert data["head_set_fingerprint"] == expected_fp
    assert data["dataset"] == "gtzan"
    assert data["head_set_semantics_version"] == "1"

    # Full canonical head-set identity in the manifest (not filename-derived).
    assert data["head_ids"] == "gender,timbre"
    assert data["dim_by_head"] == "gender=2;timbre=2"
    assert data["patch_count"] == 4
    assert data["kind"] == "head"
    assert data["schema_version"] == "1"
    assert data["payload_sha256"] == rec.fingerprint_sha256

    # Digest-deterministic manifest: no publish-time cache-row bookkeeping.
    assert "created_at" not in data and "updated_at" not in data


@pytest.mark.unit
def test_manifest_stream_provenance_defaults_empty_when_omitted(con, tmp_path):
    """Existing callers passing no stream provenance record empty fields (default unchanged)."""
    out = tmp_path / "out"
    head_store = _publish_heads(out, con)
    head_store.reconcile()
    rec = head_store.lookup("s1", "effnet")
    data = _read_manifest(out, rec)
    assert data["stream_ref"] == ""
    assert data["stream_digest"] == ""
    assert data["dataset"] == ""
    # head_count / head_set_fingerprint are derived from the record and always present.
    assert data["head_count"] == 2
    assert data["head_set_fingerprint"] == head_store._head_set_fingerprint(rec)


@pytest.mark.unit
def test_manifest_rejects_non_digest_grammar_stream_ref(con, tmp_path):
    """A non-digest stream ref (would break root-relative/immutable provenance) is refused."""
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="digest-grammar stream artifact"):
        _publish_heads(out, con, stream_ref="streams/s1.effnet.bare.npy")


@pytest.mark.unit
def test_head_set_identity_is_manifest_data_not_filename(con, tmp_path):
    """The manifest records the head set; the digest filename is content-only."""
    out = tmp_path / "out"
    head_store = _publish_heads(out, con)
    head_store.reconcile()
    rec = head_store.lookup("s1", "effnet")
    data = _read_manifest(out, rec)
    # The digest name is the payload sha256 (content), not a head-set-identity encoding.
    name_digest = parse_artifact_name(rec.artifact_ref.rsplit("/", 1)[-1], ".npz").digest
    assert name_digest == rec.fingerprint_sha256
    # Head-set identity comes from the manifest data, not the filename component.
    assert data["head_set_fingerprint"] != name_digest
    assert data["head_ids"] == "gender,timbre"


# ── complete canonical inventory + refusal modes ───────────────────────────────


@pytest.mark.unit
def test_complete_canonical_inventory_publishes_full_count(con, tmp_path):
    """A complete configured canonical head set publishes with the full head count."""
    out = tmp_path / "out"
    head_store = _publish_heads(out, con, patch_count=4)
    head_store.reconcile()
    rec = head_store.lookup("s1", "effnet")
    data = _read_manifest(out, rec)
    assert data["head_count"] == 2
    assert data["head_ids"] == "gender,timbre"


@pytest.mark.unit
def test_refuses_unconfigured_extra_head(con, tmp_path):
    """An UNEXPECTED (unconfigured) head in the suite is refused; no partial artifact/row."""
    out = tmp_path / "out"
    suite = _head_arrays(4, heads=("gender", "timbre", "mood_happy"))
    with pytest.raises(StreamValidationError, match="unexpected head"):
        HeadStreamStore(con, output_root=out).publish(
            "s1",
            "effnet",
            suite,
            run_id="r",
            patch_count=4,
            alignment_version="1",
            expected_head_ids=["gender", "timbre"],
        )
    assert con.execute("SELECT count(*) FROM head_stream_registry").fetchone()[0] == 0
    assert not list((out / "heads").glob("*.npz"))


@pytest.mark.unit
def test_refuses_non_finite_head_array(con, tmp_path):
    """A non-finite head array is refused at publish (finite validation on the write path)."""
    out = tmp_path / "out"
    with pytest.raises(StreamValidationError, match="non-finite"):
        _publish_heads(out, con, patch_count=4, finite=False)
    assert con.execute("SELECT count(*) FROM head_stream_registry").fetchone()[0] == 0
    assert not list((out / "heads").glob("*.npz"))


# ── exact committed-stream patch-count alignment ───────────────────────────────


@pytest.mark.unit
def test_store_refuses_heads_misaligned_to_committed_stream_patch_count(con, tmp_path):
    """Heads whose temporal length differs from the committed stream patch_count refuse."""
    out = tmp_path / "out"
    stream_store = _ready_stream(out, con, patch_rows=5)  # committed stream patch_count == 5
    stream_rec = stream_store.lookup("s1", "effnet")
    assert stream_rec.patch_count == 5
    # A suite internally consistent at T=4 disagrees with the committed stream's patch_count
    # (5). The publish patch_count is the committed stream's count; the T=4 heads must refuse.
    misaligned = _head_arrays(4, heads=_HEAD_SET)  # every head is T=4, not 5
    with pytest.raises(StreamValidationError):
        HeadStreamStore(con, output_root=out).publish(
            "s1",
            "effnet",
            misaligned,
            run_id="r",
            patch_count=stream_rec.patch_count,
            alignment_version="1",
            expected_head_ids=list(_HEAD_SET),
            stream_ref=stream_rec.artifact_ref,
        )
    assert con.execute("SELECT count(*) FROM head_stream_registry").fetchone()[0] == 0
    assert not list((out / "heads").glob("*.npz"))


@pytest.mark.unit
def test_writer_threads_committed_stream_ref_and_publishes_aligned(con, tmp_path):
    """infer_heads_for_song records the committed stream ref and aligns to its patch count."""
    out = tmp_path / "out"
    stream_store = _ready_stream(out, con, patch_rows=4)
    stream_rec = stream_store.lookup("s1", "effnet")

    sessions = {head: _session_for(_head_arrays(4)[head]) for head in _HEAD_SET}
    kwargs = {
        "song_id": "s1",
        "backbone": "effnet",
        "backbone_patches": np.arange(4 * 8, dtype=np.float32).reshape(4, 8),
        "backbone_patch_count": stream_rec.patch_count,
        "configured_heads": list(_HEAD_SET),
        "head_sessions": sessions,
        "head_store": HeadStreamStore(con, output_root=out),
        "run_id": "run-heads",
        "force": True,
        "run_in_batches_fn": _run_batches,
        "batch_size": 4,
        "stream_ref": stream_rec.artifact_ref,
    }
    assert infer_heads_mod.infer_heads_for_song(**kwargs) is True
    head_store = kwargs["head_store"]
    head_store.reconcile()
    rec = head_store.lookup("s1", "effnet")
    data = _read_manifest(out, rec)
    # The committed stream ref threaded from infer_heads_for_song is recorded verbatim.
    assert data["stream_ref"] == stream_rec.artifact_ref
    assert data["stream_digest"] == stream_rec.fingerprint_sha256
    assert rec.patch_count == stream_rec.patch_count == 4


def _session_for(acts: np.ndarray) -> Mock:
    session = Mock()
    session.run.return_value = [acts]
    return session


def _run_batches(predict, data, _batch_size):
    return predict(data)


# ── canonical-order source-index gather (concatenated contract) ────────────────


@pytest.mark.unit
def test_gather_is_canonical_order_concatenated_finite_source_rows(con, tmp_path):
    """batch_gather returns float32 [N, total_dim] columns in canonical head order."""
    out = tmp_path / "out"
    arrays = _head_arrays(4, seed=3)
    head_store = HeadStreamStore(con, output_root=out)
    head_store.publish(
        "s1",
        "effnet",
        arrays,
        run_id="r",
        patch_count=4,
        alignment_version="1",
        expected_head_ids=["timbre", "gender"],  # intentionally shuffled -> canonical order still
        stream_ref="streams/s1.effnet." + "a" * 64 + ".npy",
    )
    head_store.reconcile()
    got = head_store.batch_gather("s1", "effnet", [0, 2, 3])
    assert got.shape == (3, 4)
    assert got.dtype == np.float32
    assert np.isfinite(got).all()
    np.testing.assert_allclose(got[:, :2], arrays["gender"][[0, 2, 3]])
    np.testing.assert_allclose(got[:, 2:], arrays["timbre"][[0, 2, 3]])


# ── rerun identity / no byte replacement ───────────────────────────────────────


@pytest.mark.unit
def test_rerun_identical_bytes_reuse_digest_artifact_and_manifest(con, tmp_path):
    """Re-publishing identical bytes reuses the digest .npz AND a byte-identical manifest."""
    out = tmp_path / "out"
    head_store = _publish_heads(out, con, stream_ref="streams/s1.effnet." + "b" * 64 + ".npy")
    head_store.reconcile()
    rec1 = head_store.lookup("s1", "effnet")
    npz1 = out / rec1.artifact_ref
    man1_path = out / payload_to_manifest_ref(rec1.artifact_ref)
    npz1_bytes = npz1.read_bytes()
    man1_bytes = man1_path.read_bytes()

    # Re-publish IDENTICAL head bytes (same provenance). Content-addressed no-replace: the
    # digest .npz and its first-committed manifest are reused byte-identical, never replaced.
    head_store2 = HeadStreamStore(con, output_root=out)
    head_store2.publish(
        "s1",
        "effnet",
        _head_arrays(4, seed=0),
        run_id="run-heads-2",
        patch_count=4,
        alignment_version="1",
        expected_head_ids=list(_HEAD_SET),
        stream_ref="streams/s1.effnet." + "b" * 64 + ".npy",
    )
    head_store2.reconcile()
    rec2 = head_store2.lookup("s1", "effnet")
    assert rec2.artifact_ref == rec1.artifact_ref
    npz2 = out / rec2.artifact_ref
    assert npz2.read_bytes() == npz1_bytes
    man2_path = out / payload_to_manifest_ref(rec2.artifact_ref)
    assert man2_path.read_bytes() == man1_bytes
    assert len(list((out / "heads").glob("*.npz"))) == 1


# ── CPU-only head reads ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_head_read_surface_makes_no_audio_or_model_call(con, tmp_path, monkeypatch):
    """lookup/batch_gather complete with discover_audio sentinel raised => zero ML calls."""
    out = tmp_path / "out"
    _ready_stream(out, con, patch_rows=4)
    head_store = _publish_heads(out, con, patch_count=4)
    head_store.reconcile()

    events: list[str] = []

    def _forbidden(*_a, **_k):
        events.append("forbidden")
        raise AssertionError("audio discovery during a CPU-only head read")

    # The read surface must never reach audio discovery / model loading. Discover_audio is
    # always attachable on config; onnxruntime/torch may be absent in this env (the module
    # import guard in test_stream_cpu_boundary covers those separately).
    monkeypatch.setattr(config_mod, "discover_audio", _forbidden)

    rec = head_store.lookup("s1", "effnet")
    got = head_store.batch_gather("s1", "effnet", list(range(rec.patch_count)))
    assert got.shape == (rec.patch_count, 4)
    assert np.isfinite(got).all()
    assert events == []  # the sentinel never fired
