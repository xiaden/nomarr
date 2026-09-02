"""Phase 2 (P2-S3) tests for validated batch-gather duplicate handling.

Uniqueness-required contracts (e.g. seg-membership medoid gathers) select each source
row at most once; other gathers may legitimately repeat a row.  ``batch_gather`` therefore
permits duplicates by default and rejects them only when ``forbid_duplicates=True``.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.streams.store import StreamStore


def _store(con, tmp_path) -> StreamStore:
    return StreamStore(con, output_root=tmp_path / "out")


@pytest.mark.unit
def test_gather_duplicates_allowed_by_default(con, tmp_path):
    """Repeated source indices are legal unless the caller forbids them."""
    store = _store(con, tmp_path)
    arr = np.arange(12, dtype=np.float32).reshape(4, 3)
    store.publish("song1", "effnet", arr, run_id="r1")
    store.reconcile()

    out = store.batch_gather("song1", "effnet", [0, 0, 2])
    assert out.shape == (3, 3)
    np.testing.assert_array_equal(out, arr[[0, 0, 2]])


@pytest.mark.unit
def test_gather_forbid_duplicates_rejects_repeats(con, tmp_path):
    """forbid_duplicates=True rejects any repeated source index (uniqueness contract)."""
    store = _store(con, tmp_path)
    arr = np.arange(12, dtype=np.float32).reshape(4, 3)
    store.publish("song1", "effnet", arr, run_id="r1")
    store.reconcile()

    with pytest.raises(ValueError, match="duplicate source patch indices"):
        store.batch_gather("song1", "effnet", [0, 1, 1], forbid_duplicates=True)
    # Distinct and empty selections are always legal under the uniqueness contract.
    np.testing.assert_array_equal(
        store.batch_gather("song1", "effnet", [3, 0, 2], forbid_duplicates=True), arr[[3, 0, 2]]
    )
    empty = store.batch_gather("song1", "effnet", [], forbid_duplicates=True)
    assert empty.shape == (0, 3)


@pytest.mark.unit
def test_gather_forbid_duplicates_still_validates_range(con, tmp_path):
    """Out-of-range indices are rejected regardless of the duplicate policy."""
    store = _store(con, tmp_path)
    arr = np.arange(12, dtype=np.float32).reshape(4, 3)
    store.publish("song1", "effnet", arr, run_id="r1")
    store.reconcile()
    with pytest.raises(ValueError):
        store.batch_gather("song1", "effnet", [0, 9], forbid_duplicates=True)
