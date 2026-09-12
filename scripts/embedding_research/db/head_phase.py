"""Geometry-era head evidence persistence helpers.

Head rows are exact geometry/head evidence; no configuration boundary or pooled
snapshot identity is persisted here.  The durable detailed payload is owned by
``db.identity_persistence.write_head_evidence``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

HEAD_PHASE_PROVENANCE_COLUMNS = (
    "run_id",
    "geometry_id",
    "observation_id",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "threshold_id",
    "structural_identity",
    "search_representation_id",
    "evaluation_id",
    "scoring_semantics_version",
    "execution_id",
    "head",
    "segment_id",
    "finite",
    "status",
    "refusal",
)
CANONICAL_HEAD_PHASE_WHERE = "status = 'done' AND finite = 1"


@dataclass(frozen=True)
class HeadPhaseProvenanceRow:
    run_id: str
    geometry_id: str
    observation_id: str
    geometry_semantics_version: str
    numerical_profile_digest: str
    threshold_id: str
    structural_identity: str
    search_representation_id: str
    evaluation_id: str
    scoring_semantics_version: int
    execution_id: str
    head: str
    segment_id: int
    finite: bool = True
    status: str = "done"
    refusal: str | None = None

    @property
    def config_key(self) -> str:
        return ":".join(
            (
                self.geometry_id,
                self.observation_id,
                self.threshold_id,
                self.search_representation_id,
                self.head,
                str(self.segment_id),
            )
        )

    def to_tuple(self) -> tuple[Any, ...]:
        return tuple(getattr(self, key) for key in HEAD_PHASE_PROVENANCE_COLUMNS)


def head_phase_config_key(**kwargs: Any) -> str:
    """Build the stable colon-delimited identity key for one head segment."""
    return ":".join(
        str(kwargs.get(key, ""))
        for key in ("geometry_id", "observation_id", "threshold_id", "search_representation_id", "head", "segment_id")
    )


def _row(value: Any, run_id: str = "") -> HeadPhaseProvenanceRow:
    if isinstance(value, HeadPhaseProvenanceRow):
        return value
    data = dict(value)
    data.setdefault("run_id", run_id)
    return HeadPhaseProvenanceRow(**{key: data[key] for key in HEAD_PHASE_PROVENANCE_COLUMNS if key in data})


def build_head_phase_provenance_rows(
    manifest: Any, reference_corpus_hash: str | None = None
) -> list[HeadPhaseProvenanceRow]:
    """Materialize canonical provenance rows from a completed head manifest."""
    del reference_corpus_hash
    return [
        HeadPhaseProvenanceRow(
            run_id=manifest.run_id,
            geometry_id=manifest.geometry_id,
            observation_id=manifest.observation_id,
            geometry_semantics_version=manifest.geometry_semantics_version,
            numerical_profile_digest=manifest.numerical_profile_digest,
            threshold_id=output.threshold_id,
            structural_identity=output.structural_identity,
            search_representation_id=output.search_representation_id,
            evaluation_id=output.evaluation_id,
            scoring_semantics_version=output.scoring_semantics_version,
            execution_id=output.execution_id,
            head=output.head,
            segment_id=output.segment_id,
        )
        for output in manifest.outputs
    ]


def write_head_phase_provenance(con: Any, rows: Any) -> None:
    """Insert non-empty materialized head-phase provenance rows."""
    materialized = [_row(row) for row in rows]
    if not materialized:
        return
    table = "head_phase_provenance"
    columns = ", ".join(HEAD_PHASE_PROVENANCE_COLUMNS)
    placeholders = ", ".join("?" for _ in HEAD_PHASE_PROVENANCE_COLUMNS)
    con.executemany(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", [row.to_tuple() for row in materialized]
    )


def load_head_phase_provenance(con: Any) -> list[HeadPhaseProvenanceRow]:
    """Load canonical head-phase provenance rows in deterministic identity order."""
    rows = con.execute(
        f"SELECT {', '.join(HEAD_PHASE_PROVENANCE_COLUMNS)} FROM head_phase_provenance WHERE {CANONICAL_HEAD_PHASE_WHERE} ORDER BY geometry_id, observation_id, threshold_id, head, segment_id"
    ).fetchall()
    return [HeadPhaseProvenanceRow(*row) for row in rows]


__all__ = [
    "CANONICAL_HEAD_PHASE_WHERE",
    "HEAD_PHASE_PROVENANCE_COLUMNS",
    "HeadPhaseProvenanceRow",
    "build_head_phase_provenance_rows",
    "head_phase_config_key",
    "load_head_phase_provenance",
    "write_head_phase_provenance",
]
