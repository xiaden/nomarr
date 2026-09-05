"""Plan D P1-S2 — disposable catalog-first search views: provenance + payload.

Covers the run-scoped disposable surface that the P1-S1 spec file
(``test_disposable_search_views.py``) does not: view payload structure, keyset/content
determinism across regeneration, and ``run_provenance.view_refs`` recording on the RESEARCH
connection (``sv.record_search_view`` — dedup by keyset identity, anchored per run, and
preserving ``retained`` runs' refs).  There is deliberately NO ``search_view_hash`` surface
here: whole-catalog search-view identity is removed (DD L266) and the view is disposable and
regenerated for every run.

Two-connection fixture contract (``compact_catalog_factory``): compact catalog reads go through
``harness.con`` (one live snapshot handle); research ``run_provenance`` writes go through the
research ``con`` fixture.
"""

from __future__ import annotations

import json

import numpy as np

from scripts.embedding_research import catalog
from scripts.embedding_research import search_views as sv
from scripts.embedding_research.db import provenance as prov


def _unit(rng, n: int, d: int, spread: float = 1.5) -> np.ndarray:
    """Deterministic float32 L2-unit rows (a normalized frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * spread
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _build(
    con,
    out,
    factory,
    *,
    seed: int = 7,
    song_ids=("s1", "s2"),
    n: int = 10,
    d: int = 6,
    threshold: float = 0.7,
    run_id: str = "run-cat-1",
):
    """Publish ready effnet streams and build ONE compact snapshot; return the harness."""
    rng = np.random.default_rng(seed)
    streams = {}
    for song in song_ids:
        streams[(song, "effnet")] = _unit(rng, n, d)
    return factory(
        con,
        out,
        streams=streams,
        configs=[
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=threshold,
                threshold_effective=threshold,
            )
        ],
        song_ids=list(song_ids),
        run_id=run_id,
    )


def _view_dir(harness, record: sv.SearchViewRecord):
    return harness.stream_store.output_root / record.view_ref


def _load_vectors(harness, record: sv.SearchViewRecord) -> np.ndarray:
    return np.load(_view_dir(harness, record) / "vectors.npy", allow_pickle=False)


def _load_keys(harness, record: sv.SearchViewRecord) -> dict:
    return json.loads((_view_dir(harness, record) / "keys.json").read_bytes())


def _materialize(harness, run_id, *, song_ids=("s1", "s2"), working_memory=2**20) -> sv.SearchViewRecord:
    """Materialize a disposable view against the compact snapshot (no provenance recording)."""
    return sv.materialize_search_view(
        harness.con,
        harness.stream_store,
        song_ids=song_ids,
        backbone="effnet",
        run_id=run_id,
        working_memory=working_memory,
    )


def _table_names(con) -> set[str]:
    rows = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    return {r[0] for r in rows}


# --------------------------------------------------------------------------- #
# Keyset/content determinism + disposable payload                                #
# --------------------------------------------------------------------------- #


def test_keyset_is_deterministic_and_canonical_across_rematerialize(con, tmp_path, compact_catalog_factory):
    """Re-materializing the same corpus/run twice yields byte-identical keyset + content hash."""
    harness = _build(con, tmp_path / "out", compact_catalog_factory)
    try:
        first = _materialize(harness, "run-an-1")
        second = _materialize(harness, "run-an-1")
        assert first.keyset_hash == second.keyset_hash
        assert first.content_hash == second.content_hash
        assert first.view_ref == second.view_ref
        assert len(first.keyset_hash) == 64 and len(first.content_hash) == 64
        assert first.matrix_shape == second.matrix_shape
        assert first.weights.shape == (len(first.row_addresses),)
    finally:
        harness.close()


def test_disposable_payload_matches_record_and_has_no_search_view_hash(con, tmp_path, compact_catalog_factory):
    """The on-disk payload carries keyset/rows/weights aligned to the record; no search_view_hash."""
    harness = _build(con, tmp_path / "out", compact_catalog_factory)
    try:
        record = _materialize(harness, "run-an-1")
        vec_file = _view_dir(harness, record) / "vectors.npy"
        key_file = _view_dir(harness, record) / "keys.json"
        assert vec_file.exists() and key_file.exists()
        keys = _load_keys(harness, record)
        assert keys["keyset_hash"] == record.keyset_hash
        assert keys["content_hash"] == record.content_hash
        assert [tuple(r) for r in keys["rows"]] == list(record.row_addresses)
        assert len(keys["weights"]) == len(record.weights)
        np.testing.assert_allclose(keys["weights"], record.weights)
        # The disposable payload is regenerated content with no whole-catalog identity key.
        assert "search_view_hash" not in keys
        assert "search_view_hash" not in keys["keyset"]
        # Disk vectors are the exact gathered float32 rows (row i == row_addresses[i]).
        on_disk = _load_vectors(harness, record)
        assert on_disk.dtype == np.float32
        assert on_disk.shape == (len(record.row_addresses), record.vectors.shape[1])
        np.testing.assert_array_equal(on_disk, record.vectors)
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# run_provenance.view_refs recording (record_search_view)                        #
# --------------------------------------------------------------------------- #


def test_view_refs_recorded_and_deduplicated_per_run(con, tmp_path, compact_catalog_factory):
    """Recording two same-run materializations appends one deduped analyze view-ref line."""
    harness = _build(con, tmp_path / "out", compact_catalog_factory)
    try:
        rec = _materialize(harness, "run-an-1")
        sv.record_search_view(con, rec, run_id="run-an-1")
        sv.record_search_view(con, rec, run_id="run-an-1")  # same keyset -> dedup
        rows = prov.read_run_provenance(con, run_id="run-an-1")
        analyze = [r for r in rows if r["phase"] == sv.VIEW_PHASE]
        assert len(analyze) == 1
        refs = str(analyze[0]["view_refs"] or "").splitlines()
        assert len(refs) == 1
        keyset, content, ref = refs[0].split("|")
        assert keyset == rec.keyset_hash and content == rec.content_hash
        assert ref == rec.view_ref and ref.startswith(f"{sv.VIEW_DIR_NAME}/")
        assert analyze[0]["retained"] is False
    finally:
        harness.close()


def test_view_refs_are_anchored_per_run_and_preserve_retained_run(con, tmp_path, compact_catalog_factory):
    """A retained run's refs survive; a fresh analyze run gets its own anchored ref line."""
    harness = _build(con, tmp_path / "out", compact_catalog_factory)
    try:
        prov.write_run_provenance(
            con,
            run_id="retained-run",
            phase=sv.VIEW_PHASE,
            status="complete",
            started_at=0,
            finished_at=0,
            retained=True,
            view_refs="retained-a|retained-b|views/retained",
        )
        rec = _materialize(harness, "run-an-2")
        sv.record_search_view(con, rec, run_id="run-an-2")
        retained_rows = prov.read_run_provenance(con, run_id="retained-run")
        assert [r["view_refs"] for r in retained_rows] == ["retained-a|retained-b|views/retained"]
        an_rows = [r for r in prov.read_run_provenance(con, run_id="run-an-2") if r["phase"] == sv.VIEW_PHASE]
        assert len(an_rows) == 1
        refs = str(an_rows[0]["view_refs"] or "").splitlines()
        assert len(refs) == 1 and "|views/" in refs[0]
    finally:
        harness.close()


def test_no_view_manifest_no_second_registry_no_indexes(con, tmp_path, compact_catalog_factory):
    """Materializing adds no view_manifest/classification table and no DuckDB index."""
    harness = _build(con, tmp_path / "out", compact_catalog_factory)
    try:
        _materialize(harness, "run-an-1")
        names = _table_names(harness.con)
        assert "view_manifest" not in names
        assert "classification" not in names
        indexes = harness.con.execute("SELECT count(*) FROM duckdb_indexes() WHERE table_name IS NOT NULL").fetchone()[
            0
        ]
        assert indexes == 0
    finally:
        harness.close()
