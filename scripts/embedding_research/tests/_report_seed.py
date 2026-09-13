"""Shared synthetic geometry-evidence seeding for report tests and the fixture report.

Builds ONLY synthetic in-memory committed observations, exact ``song_patch_geometry``
rows, exact geometry analysis/head evidence, the mandatory observed global-medoid
baseline, run provenance, and seven phase timings.  No audio, model, ONNX, CUDA, real
corpus, copied vector, or inferred provenance is created or read.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import duckdb
import numpy as np

from scripts.embedding_research.db._schema import ensure_schema, upsert_phase_timing
from scripts.embedding_research.db.geometry import GeometryRecord, write_geometry
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.identity_persistence import write_analysis_rows, write_head_evidence
from scripts.embedding_research.db.provenance import write_run_provenance
from scripts.embedding_research.db.songs import upsert_song

PHASE_NAMES = ("ingest", "embed", "infer-heads", "geometry", "analyze", "head-analysis", "report")
RUN_ID = "fixture-geometry-run"
RUN_TS = "fixture-run"
BACKBONES = ("effnet", "musicnn")
SONGS = (
    ("s1", "Alice", "jazz"),
    ("s2", "Alice", "jazz"),
    ("s3", "Bob", "rock"),
    ("s4", "Bob", "rock"),
)
THRESHOLD_IDS = ("t-000", "t-001", "t-002")
EXPERIMENT = "temporal_global"
EVALUATION_ID = "fixture-evaluation"
EXECUTION_ID = "fixture-execution"
SCORING_SEMANTICS_VERSION = 1

SYNTHETIC_WARNING = {
    "level": "info",
    "message": "SYNTHETIC FIXTURE — no empirical retrieval claim.",
    "detail": ("Deterministic in-memory geometry evidence only; no audio, model, or empirical corpus was used."),
}

MATRICES = {
    "refusal": [
        {"code": "STALE_REFUSED", "surface": "geometry binding", "expected": "refused"},
        {"code": "INTEGRITY_REFUSED", "surface": "geometry blob digest", "expected": "refused"},
    ],
    "incomplete": [
        {"code": "INCOMPLETE_EVIDENCE", "surface": "head analysis payload", "expected": "refused"},
    ],
    "resource": [
        {"code": "RESOURCE_LIMIT", "surface": "exact uint8 mask validation", "expected": "refused"},
    ],
}


class _Identity:
    def __init__(self, song_id: str, backbone: str) -> None:
        self.song_id, self.backbone = song_id, backbone
        self.mask_ref = f"synthetic-mask:{song_id}:{backbone}"
        self.mask_digest = f"synthetic-mask-digest-{song_id}-{backbone}"
        self.alignment_token = f"synthetic-alignment:{song_id}:{backbone}"
        self.audio_content_sha256 = f"synthetic-audio-{song_id}"
        self.mask_semantics_version = "mask-v1"
        self.group_format_version = "group-v1"
        self.commit_sha256 = f"synthetic-commit-{song_id}-{backbone}"
        self.observation_group_sha256 = f"synthetic-observation-group-{song_id}-{backbone}"


class _StreamRecord:
    stream_ref = "synthetic-stream"
    fingerprint_sha256 = "synthetic-stream-fingerprint"
    stream_payload_sha256 = "synthetic-stream-payload"
    patch_count = 4
    embedding_dim = 3
    stream_dtype = "float32"
    stream_format_version = "stream-v1"
    embed_semantics_version = 1
    preprocess_fn = "synthetic"
    preprocess_version = "1"
    backbone_model_hash = "synthetic-model"
    audio_params = "synthetic"
    provenance_source = "synthetic"
    provenance_assumption = "fixture-only"
    run_id = RUN_ID


class _Observation:
    def __init__(self, con, song_id: str, backbone: str) -> None:
        self.con = con
        self.identity = _Identity(song_id, backbone)
        self.stream_record = _StreamRecord()
        self.stream = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.7, 0.7, 0.0], [0.0, 0.7, 0.7]],
            dtype=np.float32,
        )
        self.provenance_identity = f"synthetic-provenance:{song_id}:{backbone}"


@dataclass
class _HeadOutput:
    geometry_id: str
    observation_group_sha256: str
    geometry_semantics_version: str
    numerical_profile_digest: str
    threshold_id: str
    evaluation_id: str
    search_representation_id: str
    execution_id: str
    head: str
    segment_id: int
    scoring_semantics_version: int = SCORING_SEMANTICS_VERSION
    structural_identity: str = "synthetic-structural"
    status: str = "done"

    def to_dict(self) -> dict:
        return {
            "head": self.head,
            "segment_id": self.segment_id,
            "status": self.status,
            "finite": True,
            "coverage": 1.0,
        }


def analysis_identity(
    record: GeometryRecord, *, threshold_id: str, structural_identity: str, search_representation_id: str
):
    """Build the exact ten-axis analysis identity for one geometry record."""
    return SimpleNamespace(
        geometry_id=record.geometry_id,
        observation_group_sha256=record.identity.observation_group_sha256,
        geometry_semantics_version=record.identity.geometry_semantics_version,
        numerical_profile_digest=record.identity.numerical_profile_digest,
        threshold_id=threshold_id,
        structural_identity=structural_identity,
        search_representation_id=search_representation_id,
        evaluation_id=EVALUATION_ID,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        execution_id=EXECUTION_ID,
    )


def head_output(record: GeometryRecord, *, head: str = "genre", segment_id: int = 0) -> _HeadOutput:
    """Build one exact head evidence output anchored on a geometry record."""
    return _HeadOutput(
        geometry_id=record.geometry_id,
        observation_group_sha256=record.identity.observation_group_sha256,
        geometry_semantics_version=record.identity.geometry_semantics_version,
        numerical_profile_digest=record.identity.numerical_profile_digest,
        threshold_id=THRESHOLD_IDS[0],
        evaluation_id=EVALUATION_ID,
        search_representation_id=f"rep:{record.identity.song_id}:{record.identity.backbone}:{THRESHOLD_IDS[0]}",
        execution_id=EXECUTION_ID,
        head=head,
        segment_id=segment_id,
    )


def seed_songs(con, songs: tuple[tuple[str, str, str], ...] = SONGS) -> None:
    for song_id, artist, genre in songs:
        upsert_song(con, song_id, f"synthetic://{song_id}", artist, "Synthetic", song_id, genre)


def seed_geometry(con, *, run_id: str = RUN_ID, backbones: tuple[str, ...] = BACKBONES) -> tuple[GeometryRecord, ...]:
    profile = GeometryProfile.current()
    records = [
        write_geometry(_Observation(con, song_id, backbone), profile, run_id)
        for song_id, _artist, _genre in SONGS
        for backbone in backbones
    ]
    return tuple(records)


def seed_analysis(con, *, run_id: str = RUN_ID, records: tuple[GeometryRecord, ...]) -> None:
    """Seed exact winner threshold evidence plus the mandatory observed baseline."""
    for record in records:
        for threshold_id in THRESHOLD_IDS:
            identity = analysis_identity(
                record,
                threshold_id=threshold_id,
                structural_identity=f"{EXPERIMENT}:{record.identity.backbone}:{threshold_id}",
                search_representation_id=f"rep:{record.identity.song_id}:{record.identity.backbone}:{threshold_id}",
            )
            write_analysis_rows(
                con,
                run_id=run_id,
                identity=identity,
                metrics={"total_searchable": 1.0, "searchable_weight_sum": 1.0},
                evidence={"role": "threshold", "experiment": EXPERIMENT},
            )
    for backbone in BACKBONES:
        anchor = next(record for record in records if record.identity.backbone == backbone)
        baseline_identity = analysis_identity(
            anchor,
            threshold_id=f"observed-baseline:{backbone}",
            structural_identity=f"{EXPERIMENT}:observed-medoid:{backbone}",
            search_representation_id=f"observed-medoid:{backbone}",
        )
        write_analysis_rows(
            con,
            run_id=run_id,
            identity=baseline_identity,
            metrics={"baseline_present": 1.0, "baseline_delta_artist": 0.05},
            evidence={"role": "mandatory-observed-baseline", "backbone": backbone},
        )


def seed_head_evidence(con, *, run_id: str = RUN_ID, records: tuple[GeometryRecord, ...]) -> None:
    outputs = [head_output(record, head="genre", segment_id=index) for index, record in enumerate(records)]
    write_head_evidence(con, run_id=run_id, outputs=outputs)


def seed_provenance(con, *, run_id: str = RUN_ID, phases: tuple[str, ...] = PHASE_NAMES) -> None:
    for index, phase in enumerate(phases):
        started = 1_700_000_000_000 + index * 2_000
        write_run_provenance(
            con,
            run_id=run_id,
            phase=phase,
            status="complete",
            started_at=started,
            finished_at=started + 500,
            input_artifact_hashes=f"synthetic-input-{phase}",
            output_artifact_hashes=f"synthetic-output-{phase}",
            config_hash="synthetic-config",
            song_count=len(SONGS),
            warning_count=0,
            command_line=f"python run.py {phase}",
        )


def seed_phase_timings(con, *, run_ts: str = RUN_TS, phases: tuple[str, ...] = PHASE_NAMES) -> None:
    for index, phase in enumerate(phases):
        upsert_phase_timing(con, run_ts, phase, float(index + 1))


def seed_geometry_report(con, *, run_id: str = RUN_ID) -> duckdb.DuckDBPyConnection:
    """Seed a fully synthetic geometry report scope onto an open (schema-ensured) connection."""
    seed_songs(con)
    seed_provenance(con, run_id=run_id)
    records = seed_geometry(con, run_id=run_id)
    seed_analysis(con, run_id=run_id, records=records)
    seed_head_evidence(con, run_id=run_id, records=records)
    seed_phase_timings(con)
    return con


def build_seeded_con(*, run_id: str = RUN_ID) -> duckdb.DuckDBPyConnection:
    """Open an in-memory schema and seed the synthetic geometry report scope."""
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    return seed_geometry_report(con, run_id=run_id)


__all__ = [
    "BACKBONES",
    "EVALUATION_ID",
    "EXECUTION_ID",
    "EXPERIMENT",
    "MATRICES",
    "PHASE_NAMES",
    "RUN_ID",
    "RUN_TS",
    "SCORING_SEMANTICS_VERSION",
    "SONGS",
    "SYNTHETIC_WARNING",
    "THRESHOLD_IDS",
    "analysis_identity",
    "build_seeded_con",
    "head_output",
    "seed_analysis",
    "seed_geometry",
    "seed_geometry_report",
    "seed_head_evidence",
    "seed_phase_timings",
    "seed_provenance",
    "seed_songs",
]
