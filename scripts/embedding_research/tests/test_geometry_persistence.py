from __future__ import annotations

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db import (
    GeometryIdentity,
    GeometryRefusal,
    ensure_schema,
    read_geometry,
    read_geometry_matrix,
    write_geometry,
)
from scripts.embedding_research.db.geometry_profile import GeometryProfile


class Identity:
    song_id = "song-1"
    backbone = "backbone-a"
    mask_ref = "mask-ref"
    mask_digest = "mask-digest"
    alignment_token = "align"
    audio_content_sha256 = "audio-digest"
    mask_semantics_version = "mask-v1"
    group_format_version = "group-v1"
    commit_sha256 = "commit-1"


class Record:
    stream_ref = "stream-ref"
    fingerprint_sha256 = "stream-fingerprint"
    stream_payload_sha256 = "stream-payload"
    patch_count = 3
    embedding_dim = 2
    stream_dtype = "float32"
    stream_format_version = "stream-v1"
    embed_semantics_version = 1
    preprocess_fn = "preprocess"
    preprocess_version = "1"
    backbone_model_hash = "model"
    audio_params = "audio"
    provenance_source = "synthetic"
    provenance_assumption = "fixture"


class Observation:
    identity = Identity()
    stream_record = Record()
    stream = np.asarray([[1, 0], [0, 1], [1, 1]], dtype=np.float32)
    provenance_identity = "provenance"

    def __init__(self, con):
        self.con = con


@pytest.fixture
def profile() -> GeometryProfile:
    return GeometryProfile.current()


def test_geometry_round_trip_duplicate_and_reopen(profile):
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation = Observation(con)
    record = write_geometry(observation, profile, "run-1")
    loaded = read_geometry(record.identity, con)
    assert loaded.geometry_id == record.geometry_id
    assert loaded.gram_blob == record.gram_blob
    assert np.array_equal(read_geometry_matrix(record.identity, con), record.matrix)
    assert not loaded.matrix.flags.writeable
    with pytest.raises(GeometryRefusal, match="already exists"):
        write_geometry(observation, profile, "run-2")
    con.close()


def test_geometry_rollback_on_insert_failure(profile):
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation = Observation(con)

    class FailingConnection:
        def execute(self, sql, params=None):
            if isinstance(sql, str) and sql.startswith("INSERT INTO song_patch_geometry"):
                raise RuntimeError("injected insert failure")
            return con.execute(sql, params) if params is not None else con.execute(sql)

    observation.con = FailingConnection()
    with pytest.raises(RuntimeError, match="injected"):
        write_geometry(observation, profile, "run-1")
    assert con.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 0
    con.close()


def test_geometry_corruption_and_profile_identity_refuse(profile):
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation = Observation(con)
    record = write_geometry(observation, profile, "run-1")
    con.execute("UPDATE song_patch_geometry SET gram_blob=? WHERE geometry_id=?", [b"bad", record.geometry_id])
    with pytest.raises(GeometryRefusal):
        read_geometry(record.identity, con)
    con.execute("DELETE FROM song_patch_geometry")
    changed = GeometryIdentity(
        record.identity.song_id,
        record.identity.backbone,
        record.identity.observation_commit_sha256,
        record.identity.geometry_semantics_version,
        "0" * 64,
    )
    with pytest.raises(GeometryRefusal):
        read_geometry(changed, con)
    con.close()
