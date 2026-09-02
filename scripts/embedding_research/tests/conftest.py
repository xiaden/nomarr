"""Shared pytest fixtures for embedding research tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest

from scripts.embedding_research.db._schema import ensure_schema

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def con():
    """In-memory DuckDB connection with full schema applied."""
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    yield connection
    connection.close()


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``legacy_scaled`` marker used by the two-track threshold tests.

    Two-track convention (Phase 3): tests that pin the NEW-DEFAULT ``direct_l2``
    threshold semantics (``effective == configured``) carry no marker and are the
    unmarked default track. Tests that pin LEGACY SCALED semantics — the explicit
    ``std_scaled`` PTC opt-in (configured x recorded calibration basis) and the
    archival CTP per-song score_std multiplier path — are marked ``legacy_scaled``
    so a run can select either golden track (``-m legacy_scaled`` /
    ``-m 'not legacy_scaled'``) and so it is never ambiguous which semantics an
    assertion encodes.
    """
    config.addinivalue_line(
        "markers",
        "legacy_scaled: pins LEGACY SCALED threshold semantics (explicit std_scaled "
        "PTC / archival CTP score_std multiplier), never the direct_l2 default. "
        "New-default direct_l2 tests are unmarked.",
    )
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


@pytest.fixture
def tmp_flat_head_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect flat_heads cache to a temp directory so tests don't pollute OUTPUT_ROOT."""
    from scripts.embedding_research.cache import flat_heads

    cache_root = tmp_path / "cache"
    monkeypatch.setattr(flat_heads, "_CACHE_ROOT", cache_root)
    return cache_root
