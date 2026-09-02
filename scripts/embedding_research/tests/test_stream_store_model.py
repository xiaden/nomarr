"""StreamRecord / HeadStreamRecord value-object tests (Plan B Phase 1, P1-S1/S2/S3).

Covers field completeness (every ledger/DD field present with the correct type),
immutability, canonical head-ID/dimension serialization, and the scope-limited input
validation (``dtype == float32``, the status vocabulary, non-negative integer counts/
dimensions/timestamps, sha256 fingerprints, safe root-relative artifact refs, head/dim
set consistency).
"""

from __future__ import annotations

import typing
from dataclasses import FrozenInstanceError, fields

import pytest

from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    STREAM_REGISTRY_COLUMNS,
    HeadStreamRecord,
    ReconcileReport,
    StreamRecord,
    canonical_dim_by_head,
    canonical_head_ids,
    parse_dim_by_head,
    parse_head_ids,
)

_TS = 1_700_000_000_000
_SHA = "a" * 64

VALID_STREAM = {
    "song_id": "s1",
    "backbone": "effnet",
    "artifact_ref": "patches/s1.effnet.npy",
    "patch_count": 3,
    "dim": 4,
    "dtype": "float32",
    "format_version": "1",
    "fingerprint_sha256": _SHA,
    "preprocess_fn": "standardize",
    "preprocess_version": "1.0",
    "backbone_model_hash": "bbhash",
    "audio_params": "44.1k/mono",
    "embed_semantics_version": 1,
    "provenance_source": "embed",
    "provenance_assumption": "",
    "status": "ready",
    "run_id": "run-1",
    "created_at": _TS,
    "updated_at": _TS,
}

VALID_HEAD = {
    "song_id": "s1",
    "backbone": "effnet",
    "artifact_ref": "heads/s1.effnet.npz",
    "patch_count": 3,
    "head_ids": "gender,timbre",
    "dim_by_head": "gender=2;timbre=2",
    "format_version": "1",
    "fingerprint_sha256": _SHA,
    "preprocess_fn": "standardize",
    "preprocess_version": "1.0",
    "backbone_model_hash": "bbhash",
    "alignment_version": "v1",
    "status": "ready",
    "run_id": "run-1",
    "created_at": _TS,
    "updated_at": _TS,
}


def make_stream(**overrides) -> StreamRecord:
    kwargs = dict(VALID_STREAM)
    kwargs.update(overrides)
    return StreamRecord(**kwargs)


def make_head(**overrides) -> HeadStreamRecord:
    kwargs = dict(VALID_HEAD)
    kwargs.update(overrides)
    return HeadStreamRecord(**kwargs)


# ── field completeness / types ────────────────────────────────────────────────


def test_stream_record_field_set_matches_registry_columns():
    names = {f.name for f in fields(StreamRecord)}
    assert names == set(STREAM_REGISTRY_COLUMNS)


def test_head_record_field_set_matches_registry_columns():
    names = {f.name for f in fields(HeadStreamRecord)}
    assert names == set(HEAD_STREAM_REGISTRY_COLUMNS)


def test_stream_record_field_types():
    hints = typing.get_type_hints(StreamRecord)
    assert hints["song_id"] is str
    assert hints["artifact_ref"] is str
    assert hints["patch_count"] is int
    assert hints["dim"] is int
    assert hints["dtype"] is str
    assert hints["embed_semantics_version"] is int
    assert hints["status"] is str
    assert hints["created_at"] is int
    assert hints["updated_at"] is int


def test_head_record_field_types():
    hints = typing.get_type_hints(HeadStreamRecord)
    assert hints["song_id"] is str
    assert hints["head_ids"] is str
    assert hints["dim_by_head"] is str
    assert hints["patch_count"] is int
    assert hints["alignment_version"] is str
    assert hints["status"] is str
    assert hints["created_at"] is int


def test_records_roundtrip_through_row_tuple():
    rec = make_stream()
    assert StreamRecord.from_row(rec.row_tuple()) == rec
    head = make_head()
    assert HeadStreamRecord.from_row(head.row_tuple()) == head


# ── immutability ──────────────────────────────────────────────────────────────


def test_stream_record_is_immutable():
    with pytest.raises(FrozenInstanceError):
        make_stream().song_id = "other"  # type: ignore[misc]


def test_head_record_is_immutable():
    with pytest.raises(FrozenInstanceError):
        make_head().head_ids = "gender"  # type: ignore[misc]


def test_stream_record_with_status_returns_new_instance():
    rec = make_stream(status="pending")
    promoted = rec.with_status("ready")
    assert rec.status == "pending"
    assert promoted.status == "ready"
    assert promoted is not rec


# ── validation rejects ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mutator", "exc"),
    [
        ({"dtype": "float16"}, ValueError),
        ({"status": "unknown"}, ValueError),
        ({"status": "legacy"}, ValueError),  # legacy is provenance_source, not a status
        ({"patch_count": -1}, ValueError),
        ({"dim": 0}, ValueError),
        ({"embed_semantics_version": -1}, ValueError),
        ({"created_at": -5}, ValueError),
        ({"updated_at": _TS - 1, "created_at": _TS + 1}, ValueError),
        ({"fingerprint_sha256": "not-a-sha"}, ValueError),
        ({"fingerprint_sha256": "A" * 64}, ValueError),  # uppercase rejected
        ({"artifact_ref": "/abs/path.npy"}, ValueError),
        ({"artifact_ref": "../escape.npy"}, ValueError),
        ({"song_id": ""}, ValueError),
        ({"dtype": True}, TypeError),
        ({"patch_count": True}, TypeError),
        ({"patch_count": 3.5}, TypeError),
    ],
)
def test_stream_record_rejects_invalid_inputs(mutator, exc):
    with pytest.raises(exc):
        make_stream(**mutator)


@pytest.mark.parametrize(
    ("mutator", "exc"),
    [
        ({"status": "broken"}, ValueError),
        ({"patch_count": -1}, ValueError),
        ({"head_ids": "gender,timbre", "dim_by_head": "gender=2"}, ValueError),  # head set mismatch
        ({"head_ids": "gender", "dim_by_head": "gender=2;timbre=2"}, ValueError),
        ({"head_ids": ""}, ValueError),
        ({"dim_by_head": "timbre=0"}, ValueError),  # dim < 1
        ({"artifact_ref": "../x.npz"}, ValueError),
        ({"alignment_version": ""}, ValueError),  # empty alignment label rejected
    ],
)
def test_head_record_rejects_invalid_inputs(mutator, exc):
    with pytest.raises(exc):
        make_head(**mutator)


def test_head_record_canonicalizes_head_ids_and_dims():
    head = make_head(head_ids="timbre,gender,timbre", dim_by_head="timbre=2;gender=2")
    assert head.head_ids == "gender,timbre"
    assert head.dim_by_head == "gender=2;timbre=2"


# ── canonical head serialization ──────────────────────────────────────────────


def test_canonical_head_serialization_roundtrip():
    ids = canonical_head_ids(["timbre", "gender", "timbre"])
    assert ids == "gender,timbre"
    dims_text = canonical_dim_by_head({"timbre": 2, "gender": 2})
    assert dims_text == "gender=2;timbre=2"
    assert parse_head_ids(ids) == ("gender", "timbre")
    assert parse_dim_by_head(dims_text) == {"gender": 2, "timbre": 2}


def test_canonical_serialization_rejects_empty():
    with pytest.raises(ValueError):
        canonical_head_ids([])
    with pytest.raises(ValueError):
        canonical_dim_by_head({})


# ── ReconcileReport shape ─────────────────────────────────────────────────────


def test_reconcile_report_default_shape():
    report = ReconcileReport()
    assert report.scanned == 0
    assert report.ready == 0 and report.missing == 0 and report.corrupt == 0
    assert report.orphan == 0 and report.stale == 0
    assert report.strict is False
    assert report.issues == ()
    assert report.clean is False  # nothing scanned


def test_reconcile_report_clean_only_when_all_ready_no_orphans():
    clean = ReconcileReport(scanned=2, ready=2)
    assert clean.clean is True
    dirty = ReconcileReport(scanned=2, ready=1, missing=1)
    assert dirty.clean is False
    strict_dirty = ReconcileReport(scanned=1, ready=1, orphan=1)
    assert strict_dirty.clean is False


def test_reconcile_report_is_immutable():
    with pytest.raises(FrozenInstanceError):
        ReconcileReport().ready = 1  # type: ignore[misc]
