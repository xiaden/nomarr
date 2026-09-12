"""Shared pytest fixtures for embedding research tests."""

from __future__ import annotations

import duckdb
import pytest

from scripts.embedding_research.db._schema import ensure_schema


@pytest.fixture
def con():
    """In-memory DuckDB connection with full schema applied."""
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    yield connection
    connection.close()


def pytest_configure(config: pytest.Config) -> None:
    """Register the pytest markers used by the retained research suite.

    ``sigkill_bookkeeping`` marks tests that simulate an interrupted durable
    publication and assert only the registry/bookkeeping consequences; the
    separately marked opt-in ``blocklayer_durability`` test owns true power-loss
    durability.  The corrective-pass hard cut removed the old two-track scale
    marker along with the ``std_scaled``/calibration/CTP semantics it gated, so
    no scaled-threshold marker is registered anymore.

    ``scale`` / ``local_filesystem`` tag the DD verification-matrix synthetic
    10,000 x 100 x 10 (~10M-row DuckDB durability/shape guard and other
    local-filesystem-only fixtures: they run in the default suite (no ``-m``
    exclusion) but are explicitly labelled so a downstream scale/local-only gate
    can select or deselect them without inference, audio, or CUDA.
    """
    config.addinivalue_line(
        "markers",
        "sigkill_bookkeeping: simulates an interrupted durable publication (an injected "
        "fault / subprocess kill at a stage of the write-proxy seam) and asserts ONLY the "
        "registry/bookkeeping consequences (leftover staging .tmp, no pending/ready row for "
        "the interrupted artifact, prior ready artifacts unaffected, partial run_provenance). "
        "These are NOT power-loss durability proof (a kill cannot prove fsync reached stable "
        "storage); the separately-marked opt-in blocklayer_durability test owns durability.",
    )
    config.addinivalue_line(
        "markers",
        "blocklayer_durability: OPT-IN power-loss / block-layer replay durability test. NOT "
        "part of the default suite (no block-layer replay infrastructure exists); a skipped "
        "placeholder asserts the label and skip reason. SIGKILL tests are meaningful without it.",
    )
    config.addinivalue_line(
        "markers",
        "scale: synthetic large-scale (~10M-row) DuckDB durability/shape fixture. "
        "Runs in the default suite; local-filesystem only (no inference/audio/CUDA).",
    )
    config.addinivalue_line(
        "markers",
        "local_filesystem: exercises a durable filesystem DuckDB snapshot under a tmp_path "
        "output root; never the disposable research DB. Runs in the default suite.",
    )
