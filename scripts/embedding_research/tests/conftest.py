"""Shared pytest fixtures for embedding research tests."""

from __future__ import annotations

from pathlib import Path

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


@pytest.fixture
def tmp_flat_head_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect flat_heads cache to a temp directory so tests don't pollute OUTPUT_ROOT."""
    from scripts.embedding_research.cache import flat_heads

    cache_root = tmp_path / "cache"
    monkeypatch.setattr(flat_heads, "_CACHE_ROOT", cache_root)
    return cache_root
