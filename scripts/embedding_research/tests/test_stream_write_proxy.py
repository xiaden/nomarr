"""Phase 4 (P4-S1) — always-on write-proxy ordering + labeled SIGKILL/bookkeeping.

The durable-create contract (DD lifecycle L114-122, CONTRACTS.md L34) is exactly::

    fsync(file) -> close(file) -> atomic rename -> fsync(destination directory)

Two obligations are pinned here for BOTH observation writers (backbone ``.npy`` via
``StreamStore.publish`` and the head-suite ``.npz`` via ``HeadStreamStore.publish``):

1. **Ordering (structural, not a monkeypatch).** Every fsync/close/rename routes through
   the :class:`RecordingFileOps` write-proxy seam (the production default is the real
   ``os`` calls); tests assert the exact call order through that seam.  We never monkeypatch
   ``os`` module-wide for an ordering assertion.

2. **SIGKILL / bookkeeping — SEPARATELY LABELED from durability.**  A SIGKILL (modelled
   here by an injected fault at each stage of the write-proxy seam, which reproduces the
   observable bookkeeping of a killed durable write) is used ONLY for ordering and
   registry/bookkeeping assertions:

   * a leftover ``.staging/*.tmp`` may remain (a *file-level* condition);
   * NO ``pending``/``ready`` registry row is committed for the interrupted artifact
     (the registry row is written only AFTER the durable file write completes);
   * prior ready artifacts for OTHER identities are unaffected (no silent song loss);
   * ``run_provenance`` records the interrupted/partial run as ``partial`` and the
     singleton ``corpus_state`` never claims a complete corpus.

   A kill/injected fault is NOT treated as proof that fsync reached stable storage —
   power-loss durability is the separate OPT-IN ``blocklayer_durability`` placeholder at
   the bottom (no block-layer replay infrastructure exists), and it is required to be
   skipped/meaningful-without-SIGKILL.  Each test in this module is labelled
   ``sigkill_bookkeeping`` to make that boundary unambiguous.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common import embed as embed_mod
from scripts.embedding_research.db import read_corpus_state, read_run_provenance
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.publication import RecordingFileOps
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _arr(rows=2, cols=3, fill=None):
    if fill is None:
        return np.arange(rows * cols, dtype=np.float32).reshape(rows, cols)
    return np.full((rows, cols), fill, dtype=np.float32)


def _head_arrays(patch_count: int = 2):
    return {
        "gender": np.arange(patch_count * 2, dtype=np.float32).reshape(patch_count, 2),
        "timbre": np.ones((patch_count, 2), dtype=np.float32),
    }


# ── always-on write-proxy ORDERING (structural seam) ──────────────────────────


@pytest.mark.unit
def test_backbone_npy_publish_exact_durable_order(con, tmp_path):
    """StreamStore.publish records fsync(file)->close(file)->rename->fsync(dir)."""
    store = StreamStore(con, output_root=tmp_path / "out")
    recorder = RecordingFileOps()
    store.publish("song1", "effnet", _arr(), run_id="r1", file_ops=recorder)
    assert recorder.order == [
        ("fsync", "file"),
        ("close", "file"),
        ("rename", "file"),
        ("fsync", "dir"),
    ]


@pytest.mark.unit
def test_head_npz_publish_exact_durable_order(con, tmp_path):
    """HeadStreamStore.publish applies the SAME durable order to the head-suite .npz."""
    store = HeadStreamStore(con, output_root=tmp_path / "out")
    recorder = RecordingFileOps()
    store.publish(
        "song1",
        "effnet",
        _head_arrays(2),
        run_id="r1",
        patch_count=2,
        alignment_version="1",
        expected_head_ids=["gender", "timbre"],
        file_ops=recorder,
    )
    assert recorder.order == [
        ("fsync", "file"),
        ("close", "file"),
        ("rename", "file"),
        ("fsync", "dir"),
    ]


# ── SIGKILL / bookkeeping — SEPARATELY LABELED (never durability proof) ────────


class _FailingFileOps(RecordingFileOps):
    """A recording proxy that raises ONCE at a chosen durable-write stage.

    Models the observable bookkeeping of a killed durable write (the process stops
    between fsync/close/rename/fsync-dir and the registry-commit transaction that
    follows).  It still records each syscall so tests can reason about how far the
    sequence got before the interruption.
    """

    def __init__(self, fail_op: str):
        super().__init__()
        self.fail_op = fail_op
        self.failed = False

    def _fail(self, op: str) -> None:
        if op == self.fail_op and not self.failed:
            self.failed = True
            raise OSError(f"injected {op} interruption (SIGKILL/bookkeeping model)")

    def fsync_file(self, fd: int) -> None:
        self._record("fsync", "file")
        self._fail("fsync_file")
        self._inner.fsync_file(fd)

    def close_fd(self, fd: int) -> None:
        self._record("close", "file")
        if self.fail_op == "close_fd" and not self.failed:
            self.failed = True
            # Tidy the real fd before raising so a short test cannot leak descriptors.
            self._inner.close_fd(fd)
            raise OSError("injected close interruption (SIGKILL/bookkeeping model)")
        self._inner.close_fd(fd)

    def rename(self, src: str, dst: str) -> None:
        self._record("rename", (src, dst))
        self._fail("rename")
        self._inner.rename(src, dst)

    def fsync_dir(self, fd: int) -> None:
        self._record("fsync", "dir")
        self._fail("fsync_dir")
        self._inner.fsync_dir(fd)


@pytest.mark.unit
@pytest.mark.sigkill_bookkeeping
@pytest.mark.parametrize("stage", ["fsync_file", "close_fd", "rename"])
def test_sigkill_before_rename_leaves_tmp_no_row_prior_ready_unaffected(con, tmp_path, stage):
    """Interruption before the rename leaves a staging .tmp and commits NO registry row.

    A prior ready artifact for a DIFFERENT identity is unaffected (no silent song loss),
    reconcile ignores the leftover .tmp (file-level only), and the interrupted run is
    recorded partial with a non-complete corpus.
    """
    store = StreamStore(con, output_root=tmp_path / "out")
    # A prior READY artifact for another identity (must survive the interruption).
    store.publish("songA", "effnet", _arr(rows=2, cols=3, fill=1.0), run_id="run-good")
    store.reconcile()
    assert store.lookup("songA", "effnet").status == "ready"

    # Interrupt a NEW identity's publication at the chosen pre-rename stage.
    ops = _FailingFileOps(stage)
    with pytest.raises(OSError, match="interruption"):
        store.publish("songB", "effnet", _arr(rows=2, cols=3, fill=2.0), run_id="run-killed", file_ops=ops)

    # Registry: NO row committed for the interrupted artifact (pending or ready).
    rows = con.execute("SELECT status FROM stream_registry WHERE song_id = 'songB' AND backbone = 'effnet'").fetchall()
    assert rows == []
    # Prior ready artifact for the other identity is unaffected.
    assert store.lookup("songA", "effnet").status == "ready"

    # File-level: the staging .tmp may remain; reconcile ignores it (never a registry state).
    staging = tmp_path / "out" / "patches" / ".staging"
    tmps = list(staging.glob("*.tmp")) if staging.exists() else []
    assert len(tmps) == 1 and tmps[0].name == "songB.effnet.npy.tmp"
    report = store.reconcile()
    assert report.ready == 1  # only the prior ready artifact
    assert report.orphan == 0
    assert report.clean is True

    # Provenance: the interrupted run is recorded partial; corpus is NOT complete.
    embed_mod._record_embed_run(
        con, store, run_id="run-killed", started_at=1, done=0, skipped=0, errors=1, eligible_count=2
    )
    run = read_run_provenance(con, run_id="run-killed")
    assert run[0]["status"] == "partial"
    state = read_corpus_state(con)
    assert state["complete_flag"] is False
    assert state["registered_song_count"] == 1  # only the surviving ready song is registered


@pytest.mark.unit
@pytest.mark.sigkill_bookkeeping
def test_sigkill_after_rename_before_fsync_dir_leaves_unregistered_final_file(con, tmp_path):
    """Interruption after rename but before the directory fsync yields a final file with NO row.

    Because the registry row is committed only after the whole durable file sequence,
    the registry never sees the artifact: reconcile reports the bare final file as an
    unregistered legacy orphan (never a ready/pending row) and it is never silently
    promoted to provenance-complete.
    """
    store = StreamStore(con, output_root=tmp_path / "out")
    ops = _FailingFileOps("fsync_dir")
    with pytest.raises(OSError, match="interruption"):
        store.publish("songB", "effnet", _arr(rows=2, cols=3, fill=3.0), run_id="run-killed", file_ops=ops)

    # The final bytes DID reach the final location (rename completed)...
    final = tmp_path / "out" / "patches" / "songB.effnet.npy"
    assert final.is_file()
    # ...but NO registry row was committed.
    assert con.execute("SELECT count(*) FROM stream_registry").fetchone()[0] == 0
    # Reconcile never promotes it: it is reported as an unregistered legacy orphan.
    report = store.reconcile()
    assert report.scanned == 0
    assert report.ready == 0
    assert report.legacy == 1
    assert report.orphan == 1
    assert report.clean is False
    assert store.has_ready("songB", "effnet") is False


# ── OPT-IN block-layer durability placeholder (separate, skipped) ──────────────


@pytest.mark.blocklayer_durability
def test_opt_in_block_layer_power_loss_durability_placeholder():
    """OPT-IN power-loss/block-layer replay durability test.

    NOT part of the default suite: no block-layer replay infrastructure exists in this
    research tree, so a real power-loss test cannot run.  It is intentionally skipped
    and separately labeled from the ``sigkill_bookkeeping`` tests above, which are the
    meaningful suite (ordering + registry bookkeeping only — never a durability proof).
    """
    pytest.skip(
        "OPT-IN block-layer durability test requires a block-layer replay harness that does "
        "not exist here; SIGKILL ordering/bookkeeping tests are meaningful without it."
    )
