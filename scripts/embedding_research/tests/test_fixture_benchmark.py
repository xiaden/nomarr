"""Plan D Phase 4 (P4-S3) — benchmark-report metadata validator.

The P4-S3 benchmark-report requirement: ANY benchmark / fixture-report output in the
research tree must state **songs, patch distribution, dimension, backbone/model hash,
hardware, software, peak RSS, elapsed time, and chunk budget** BEFORE its numbers can be
called *empirical* — and because no real corpus/model run exists here, every benchmark is
labelled **fixtures-only**, never an empirical corpus claim.

``fixture_benchmark.validate_benchmark_report`` is the gate a benchmark record must pass:
it rejects a record missing ANY required metadata field and rejects a record that is not
labelled ``fixtures_only=True``.  These tests pin that gate down:

* a produced :class:`~fixture_benchmark.BenchmarkRecord` validates clean and carries the
  full metadata vocabulary;
* the validator rejects a record missing EACH one of the required fields (every field is
  genuinely required, no silent omission);
* the validator rejects a ``None``-valued required field;
* the validator rejects a record that is not labelled fixtures-only (an unlabelled report
  must never be mistaken for an empirical claim).

None of these numbers are empirical — they describe the deterministic synthetic fixture
surface in ``fixture_benchmark`` and are labelled fixtures throughout.
"""

from __future__ import annotations

import pytest

from scripts.embedding_research import fixture_benchmark as fb


def test_produced_record_carries_full_metadata_and_validates_clean():
    """A produced benchmark record has every required field and passes the gate."""
    record = fb.run_bounded_benchmark(seed=0)
    assert record.validate() == []
    assert record.fixtures_only is True
    data = record.to_dict()
    # The whole required metadata vocabulary is present and populated.
    for name in fb.REQUIRED_BENCHMARK_FIELDS:
        assert data[name] is not None, name
    # The documented vocabulary pieces map to real (fixture) values.
    assert data["n_songs"] > 0
    assert data["patch_distribution"]["row_distribution"] == "uniform"
    assert data["dimension"] > 0
    assert len(data["model_hash"]) == 64  # sha256 fixture model hash
    assert data["hardware"]
    assert data["software"]
    assert data["peak_rss_bytes"] > 0
    assert data["peak_tracemalloc_bytes"] > 0
    assert data["elapsed_ms"] >= 0.0
    assert data["query_chunk_size"] > 0
    assert data["candidate_chunk_size"] > 0
    assert data["working_memory_bytes"] > 0


@pytest.mark.parametrize("field", list(fb.REQUIRED_BENCHMARK_FIELDS))
def test_validator_rejects_report_missing_each_required_field(field):
    """A report missing ANY required field is rejected (each field genuinely required)."""
    record = fb.run_bounded_benchmark(seed=1).to_dict()
    del record[field]
    errors = fb.validate_benchmark_report(record)
    assert errors, f"expected a rejection when {field!r} is missing"
    assert any(fb._MISSING in e and field in e for e in errors), errors


@pytest.mark.parametrize("field", list(fb.REQUIRED_BENCHMARK_FIELDS))
def test_validator_rejects_none_valued_required_field(field):
    """A present-but-``None`` required field is treated as missing (never silently accepted)."""
    record = fb.run_bounded_benchmark(seed=2).to_dict()
    record[field] = None
    errors = fb.validate_benchmark_report(record)
    assert any(fb._MISSING in e and field in e for e in errors), errors


def test_validator_rejects_unlabelled_fixtures_only_report():
    """A report not labelled fixtures_only=True is rejected (never an empirical claim)."""
    record = fb.run_bounded_benchmark(seed=3).to_dict()
    record["fixtures_only"] = False
    errors = fb.validate_benchmark_report(record)
    assert errors
    assert any("fixtures_only" in e and "empirical" in e for e in errors), errors

    # Even dropping the label field entirely (so the missing-field rule fires too) rejects.
    del record["fixtures_only"]
    errors = fb.validate_benchmark_report(record)
    assert errors


def test_validator_accepts_a_complete_fixtures_labelled_report():
    """A complete, fixtures-labelled mapping passes (empty error list)."""
    record = fb.run_bounded_benchmark(seed=4).to_dict()
    assert fb.validate_benchmark_report(record) == []
