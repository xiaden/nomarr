"""Labelled FIXTURES-ONLY bounded-scoring benchmark helper + validator (Plan D, Phase 4).

Phase 4 (P4-S3 / P4-S2e) benchmark-report requirement
------------------------------------------------------
ANY benchmark / fixture-report output in the research tree must state **songs, patch
distribution, dimension, backbone/model hash, hardware, software, peak RSS, elapsed
time, and chunk budget** BEFORE its numbers can be called *empirical*.

No real corpus / real model run exists in this environment (no ONNX models, no audio
corpus), so every benchmark produced here is a **FIXTURES-ONLY, deterministic synthetic
benchmark** over generated unit-norm rows — explicitly **NOT** an empirical corpus claim.
This module realises that policy as:

* :data:`REQUIRED_BENCHMARK_FIELDS` — the canonical field set a benchmark record must
  carry (the vocabulary above, plus a ``fixtures_only`` label and a tracemalloc peak);
* :class:`BenchmarkRecord` + :func:`run_bounded_benchmark` — a labelled producer that runs
  one deterministic bounded-exact score over a sized synthetic K x M cosine surface and
  records peak tracemalloc / peak RSS (``resource``), elapsed time, the effective chunk
  budget, and the full-product byte reference;
* :func:`validate_benchmark_report` — the consumer: rejects a report missing ANY required
  field, and rejects a report not labelled ``fixtures_only`` (an unlabelled report must
  never be mistaken for an empirical claim).

The recorded peak/RSS/timing are environment-observed measurements of a *fixture*
workload, so they are labelled fixtures and are never presented as a real-corpus/model
result.  ``validate_benchmark_report`` is the gate a benchmark output must pass before
any of its numbers may be presented at all.
"""

from __future__ import annotations

import hashlib
import platform
import resource
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from scripts.embedding_research.bounded_scoring import (
    BoundedScoreResult,
    ScoringCandidateView,
    score_bounded_exact,
)
from scripts.embedding_research.search_views import APPLICATION_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "FIXTURES_ONLY",
    "REQUIRED_BENCHMARK_FIELDS",
    "BenchmarkRecord",
    "run_bounded_benchmark",
    "validate_benchmark_report",
]

#: Every benchmark/fixture-report output must carry this fixtures-only label (truthy).
FIXTURES_ONLY = True

#: Canonical field set a benchmark record must carry before its numbers may be used.
#: Vocabulary maps to the P4-S3 requirement: ``n_songs`` (songs), ``patch_distribution``,
#: ``dimension``, ``backbone`` + ``model_hash`` (backbone/model hash), ``hardware``,
#: ``software``, ``peak_rss_bytes`` / ``peak_tracemalloc_bytes`` (peak RSS), ``elapsed_ms``
#: (elapsed time), ``query_chunk_size`` / ``candidate_chunk_size`` / ``working_memory_bytes``
#: (chunk budget), and the ``fixtures_only`` label.
REQUIRED_BENCHMARK_FIELDS: tuple[str, ...] = (
    "n_songs",
    "patch_distribution",
    "dimension",
    "backbone",
    "model_hash",
    "hardware",
    "software",
    "peak_rss_bytes",
    "peak_tracemalloc_bytes",
    "elapsed_ms",
    "query_chunk_size",
    "candidate_chunk_size",
    "working_memory_bytes",
    "fixtures_only",
)

#: Error message prefix used by validate_benchmark_report for a missing required field.
_MISSING = "missing required benchmark metadata field"


def validate_benchmark_report(record: Mapping[str, Any]) -> list[str]:
    """Return the list of validation errors for *record* (empty == valid).

    Rejects a report missing ANY of :data:`REQUIRED_BENCHMARK_FIELDS` (or carrying a
    ``None`` value for one) and rejects a report that is not labelled
    ``fixtures_only=True`` — an unlabelled benchmark must never be presented as if its
    numbers were an empirical corpus/model claim.
    """
    errors = [f"{_MISSING}: {name}" for name in REQUIRED_BENCHMARK_FIELDS if name not in record or record[name] is None]
    if "fixtures_only" in record and record["fixtures_only"] is not True:
        errors.append(
            "benchmark is not labelled fixtures_only=True; it must never be "
            "presented as an empirical corpus/model claim"
        )
    return errors


#: Deterministic synthetic backbone/model identity for the fixtures-only surface.  There is
#: NO real model here — this is a documented FIXTURE model hash, never a measured claim.
def _fixture_model_hash(backbone: str) -> str:
    return hashlib.sha256(f"fixtures-only-synthetic-backbone:{backbone}".encode()).hexdigest()


def _fixture_software() -> str:
    """Installed software versions that executed the fixture (never an empirical claim)."""
    import duckdb

    return (
        f"application={APPLICATION_VERSION};python={platform.python_version()};"
        f"numpy={np.__version__};duckdb={duckdb.__version__}"
    )


def _fixture_hardware() -> str:
    """Host hardware the synthetic fixture ran on (labelled fixtures-only)."""
    return f"{platform.machine()}|{platform.system()}|{platform.platform()}"


def _unit_rows(rng: np.random.Generator, n: int, d: int) -> np.ndarray:
    """Deterministic float32 L2-unit rows (a normalized frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


@dataclass(frozen=True)
class BenchmarkRecord:
    """A fully-labelled, validated fixtures-only benchmark record.

    Produced by :func:`run_bounded_benchmark` with every :data:`REQUIRED_BENCHMARK_FIELDS`
    populated.  Every value is observed on a deterministic *synthetic fixture*; the record
    is ``fixtures_only=True`` and its ``to_dict`` passes :func:`validate_benchmark_report`.
    """

    n_songs: int
    patch_distribution: dict[str, int]
    dimension: int
    backbone: str
    model_hash: str
    hardware: str
    software: str
    peak_rss_bytes: int
    peak_tracemalloc_bytes: int
    elapsed_ms: float
    query_chunk_size: int
    candidate_chunk_size: int
    working_memory_bytes: int
    fixtures_only: bool = FIXTURES_ONLY
    # Additional observed, labelled context (not required fields but informative).
    k_rows: int = 0
    m_rows: int = 0
    full_product_bytes: int = 0
    score: float = 0.0
    finite: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        """Return validation errors for this record (empty == valid + fixtures-labelled)."""
        return validate_benchmark_report(self.to_dict())


def _measure(fn: Callable[[], tuple[BoundedScoreResult, int, int]]) -> tuple[BoundedScoreResult, int, int, float]:
    """Run *fn* under tracemalloc; return ``(result, tracemalloc_peak, rss_kb_peak, elapsed_ms)``.

    ``tracemalloc.start()`` is opened immediately before the call so the recorded peak is
    the workload's own Python-level allocation (the input arrays are allocated before the
    trace starts).  Peak RSS is the process high-water mark via ``resource``; both are
    environment-observed FIXTURE measurements, never an empirical corpus claim.
    """
    tracemalloc.start()
    try:
        t0 = time.perf_counter()
        result = fn()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    rss_kb = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return result, int(peak), rss_kb, float(elapsed_ms)


def run_bounded_benchmark(
    *,
    n_songs: int = 8,
    segments_per_song: int = 12,
    dimension: int = 16,
    backbone: str = "synthetic_effnet_fixture",
    query_chunk_size: int | None = None,
    candidate_chunk_size: int | None = None,
    working_memory_bytes: int | None = None,
    seed: int = 0,
) -> BenchmarkRecord:
    """Run one deterministic bounded-exact score over a sized synthetic K x M surface.

    Builds ``n_songs`` synthetic songs each contributing ``segments_per_song`` float32
    unit rows (a uniform segments-per-song patch distribution, dimension ``dimension``),
    treats a batch of query rows as the source side and the candidate rows as the target
    side, and scores with :func:`score_bounded_exact` under the effective chunk budget.
    Every timing/RSS figure is a FIXTURE observation (deterministic synthetic data, no
    real corpus/model), so the returned record is ``fixtures_only=True`` and valid per
    :func:`validate_benchmark_report`.

    The ``query_chunk_size`` / ``candidate_chunk_size`` reported are the *effective*
    chunk budget actually used (explicit values, else derived from ``working_memory_bytes``
    by the scorer's documented arithmetic).
    """
    if n_songs <= 0 or segments_per_song <= 0:
        raise ValueError("n_songs and segments_per_song must be positive")
    if dimension <= 0:
        raise ValueError("dimension must be positive")
    if isinstance(n_songs, bool) or isinstance(segments_per_song, bool):
        raise ValueError("n_songs / segments_per_song must be ints, not bools")
    rng = np.random.default_rng(int(seed))
    m_rows = int(n_songs) * int(segments_per_song)
    cand = _unit_rows(rng, m_rows, int(dimension))
    query = _unit_rows(rng, max(1, m_rows // 2), int(dimension))
    k_rows = int(query.shape[0])
    cw = np.abs(rng.standard_normal(m_rows)) + 0.5
    qw = np.abs(rng.standard_normal(k_rows)) + 0.5
    full_product_bytes = k_rows * m_rows * 8  # float64 elements of the full K x M similarity.

    def _score():
        return score_bounded_exact(
            query,
            qw,
            ScoringCandidateView(vectors=cand, row_addresses=(), candidate_weights=cw),
            query_chunk_size=query_chunk_size,
            candidate_chunk_size=candidate_chunk_size,
            working_memory=working_memory_bytes,
        )

    result, peak_bytes, rss_kb, elapsed_ms = _measure(_score)
    # Reflect the effective chunk budget the scorer actually used.
    return BenchmarkRecord(
        n_songs=int(n_songs),
        patch_distribution={
            "songs": int(n_songs),
            "segments_per_song": int(segments_per_song),
            "row_distribution": "uniform",
        },
        dimension=int(dimension),
        backbone=str(backbone),
        model_hash=_fixture_model_hash(str(backbone)),
        hardware=_fixture_hardware(),
        software=_fixture_software(),
        peak_rss_bytes=int(rss_kb) * 1024,  # ru_maxrss is KiB on Linux
        peak_tracemalloc_bytes=int(peak_bytes),
        elapsed_ms=float(elapsed_ms),
        query_chunk_size=int(result.query_chunk_size),
        candidate_chunk_size=int(result.candidate_chunk_size),
        working_memory_bytes=int(result.working_memory),
        k_rows=k_rows,
        m_rows=m_rows,
        full_product_bytes=int(full_product_bytes),
        score=float(result.score),
        finite=bool(result.finite),
    )


if __name__ == "__main__":  # pragma: no cover - manual fixture-benchmark smoke
    record = run_bounded_benchmark()
    errors = record.validate()
    print("BenchmarkRecord.validate() errors:", errors)
    print("peak_tracemalloc_bytes:", record.peak_tracemalloc_bytes, "full_product_bytes:", record.full_product_bytes)
    print("fixtures_only:", record.fixtures_only)
    sys.exit(1 if errors else 0)
