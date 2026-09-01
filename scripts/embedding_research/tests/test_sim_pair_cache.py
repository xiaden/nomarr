"""Removal contract for the write-only ``sim_pairs`` cache and dead ``cache/sim.py``.

Plan C removed the mis-keyed/write-only ``sim_pairs`` path and the zero-caller
``cache/sim.py`` module.  The caller audit proved no active consumer (no read
path, no report/ or db/ usage) before removal.  These tests pin the removal so
the dead path cannot be resurrected.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _research_root() -> Path:
    # tests/test_sim_pair_cache.py -> embedding_research/
    return Path(__file__).resolve().parents[1]


def test_sim_cache_module_removed() -> None:
    """cache/sim.py (load_sim/save_sim/sim_cache_path) no longer exists."""
    with pytest.raises(ImportError):
        import scripts.embedding_research.cache.sim  # noqa: F401  # type: ignore[import-not-found]


def test_sim_pairs_cache_module_removed() -> None:
    """cache/sim_pairs.py (store_sim_pair/load_sim_pair/sim_pair_exists) no longer exists."""
    with pytest.raises(ImportError):
        import scripts.embedding_research.cache.sim_pairs  # noqa: F401  # type: ignore[import-not-found]


def test_no_sim_pairs_reference_remains_in_analyze() -> None:
    """The write-only sim_pairs call sites are gone from the analyze orchestrator."""
    analyze_path = _research_root() / "common" / "analyze.py"
    tree = ast.parse(analyze_path.read_text(encoding="utf-8"))
    dead_names = {"sim_pair_exists", "store_sim_pair", "load_sim_pair", "sim_pairs"}
    refs = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in dead_names}
    assert refs == set()
