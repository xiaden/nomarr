"""Plan D Phase 1 — disposable keyset-addressed search-view identity + materialization.

Proves the P1-S1..P1-S4 contracts implemented by ``scripts/embedding_research/search_views.py``
against the shared ledger ``SearchViewRecord`` (Plan A P2-S4, Plan D implementer):

* keyset composition determinism (corpus search_view_hash, run id, config ids, sorted song
  ids, query keys, scoring software triple, matrix shape/dtype, scoring semantics version);
* view materialization gathers EXACT observed-medoid rows through ``StreamStore.batch_gather``
  (medoid indices verified against catalog ``seg_meta`` membership);
* content-hash stability + a root-relative, keyset-derived disposable view ref (never a
  threshold-cache path);
* regeneration — the mere existence of a view file never authorizes reuse;
* ``run_provenance.view_refs`` recording (extending the existing table, preserving retained-run
  references);
* exact logical-identity (stale corpus/config/stream/scoring-version) rejection;
* absence of ``view_manifest`` / second registry tables and of any DuckDB indexes.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.embedding_research import search_views as sv
from scripts.embedding_research.db import provenance as prov
from scripts.embedding_research.streams.store import StreamStore


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
    *,
    seed: int = 7,
    song_ids=("s1", "s2"),
    n: int = 10,
    d: int = 6,
    threshold: float = 0.7,
) -> StreamStore:
    """Publish one ready effnet stream per song and build a catalog; return the store."""
    from scripts.embedding_research import catalog

    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(seed)
    for song in song_ids:
        store.publish(song, "effnet", _unit(rng, n, d), run_id="run-embed")
    store.reconcile()
    rep = catalog.build_segmentation_catalog(
        con,
        store,
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=threshold,
                threshold_effective=threshold,
            )
        ],
        list(song_ids),
        "run-cat-1",
        verify=True,
    )
    assert rep.verify_ok is True
    return store


def _corpus(song_ids=("s1", "s2")) -> sv.AnalysisCorpus:
    return sv.AnalysisCorpus(backbone="effnet", song_ids=song_ids)


def _view_dir(store: StreamStore, record: sv.SearchViewRecord):
    return store.output_root / record.view_ref


def _load_vectors(store: StreamStore, record: sv.SearchViewRecord) -> np.ndarray:
    return np.load(_view_dir(store, record) / "vectors.npy", allow_pickle=False)


def _load_keys(store: StreamStore, record: sv.SearchViewRecord) -> dict:
    return json.loads((_view_dir(store, record) / "keys.json").read_bytes())


def _table_names(con) -> set[str]:
    rows = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    return {r[0] for r in rows}


# --------------------------------------------------------------------------- #
# P1-S1 keyset composition determinism + canonical finite identity              #
# --------------------------------------------------------------------------- #


def test_keyset_is_deterministic_and_canonical_across_rematerialize(con, tmp_path):
    """Re-materializing the same corpus/run twice yields byte-identical keyset + content hash."""
    out = tmp_path / "out"
    store = _build(con, out)
    corpus = _corpus()
    first = sv.materialize_search_view(
        store, con, corpus, "run-an-1", query_keyset=sv.QueryKeyset(query_song_ids=("s1",)), working_memory=2**20
    )
    second = sv.materialize_search_view(
        store, con, corpus, "run-an-1", query_keyset=sv.QueryKeyset(query_song_ids=("s1",)), working_memory=2**20
    )
    assert first.keyset_hash == second.keyset_hash
    assert first.content_hash == second.content_hash
    assert first.view_ref == second.view_ref
    assert len(first.keyset_hash) == 64 and len(first.content_hash) == 64
    # Keyset encodes the full scoring-software triple (application, numpy, sklearn-or-null).
    assert len(first.key.scoring_software_versions) == 3
    assert first.key.scoring_semantics_version == 1
    assert first.key.dtype == "float32"
    assert len(first.key.matrix_shape) == 2 and first.key.matrix_shape[1] == first.matrix_shape[1]


def test_keyset_differentiates_run_id_query_split_and_software_versions(con, tmp_path):
    """run_id, query role, and software version each change the keyset identity."""
    out = tmp_path / "out"
    store = _build(con, out)
    corpus = _corpus()
    q1 = sv.QueryKeyset(query_song_ids=("s1",))
    q2 = sv.QueryKeyset(query_song_ids=("s2",))
    fixed = ("1", "1.0.0", None)

    a = sv.materialize_search_view(
        store, con, corpus, "run-a", query_keyset=q1, working_memory=1, software_versions=fixed
    )
    b_run = sv.materialize_search_view(
        store, con, corpus, "run-b", query_keyset=q1, working_memory=1, software_versions=fixed
    )
    c_query = sv.materialize_search_view(
        store, con, corpus, "run-a", query_keyset=q2, working_memory=1, software_versions=fixed
    )
    d_ver = sv.materialize_search_view(
        store, con, corpus, "run-a", query_keyset=q1, working_memory=1, software_versions=("2", "1.0.0", None)
    )

    assert a.keyset_hash != b_run.keyset_hash  # run id
    assert a.keyset_hash != c_query.keyset_hash  # query split
    assert a.keyset_hash != d_ver.keyset_hash  # scoring software version
    # View ref is derived from the keyset (never a threshold-cache path).
    assert a.view_ref == f"{sv.VIEW_DIR_NAME}/{a.keyset_hash}"
    assert _view_dir(store, a).is_dir()


def test_keyset_requires_single_backbone_and_canonical_song_order(con, tmp_path):
    """A corpus pinned to a config of another backbone is rejected (no cross-backbone mixing)."""
    out = tmp_path / "out"
    store = _build(con, out)
    config_id = int(con.execute("SELECT config_id FROM seg_config LIMIT 1").fetchone()[0])
    wrong = sv.AnalysisCorpus(backbone="musicnn", song_ids=("s1",), config_ids=(config_id,))
    with pytest.raises(sv.SearchViewValidationError):
        sv.materialize_search_view(store, con, wrong, "run-an-1", working_memory=2**20)
    # Unsorted song ids are canonicalized to sorted order.
    corpus = sv.AnalysisCorpus(backbone="effnet", song_ids=("s2", "s1"))
    assert corpus.song_ids == ("s1", "s2")


# --------------------------------------------------------------------------- #
# P1-S2 exact medoid gathering + disposable keyset-addressed storage            #
# --------------------------------------------------------------------------- #


def test_materialize_gathers_exact_observed_medoid_rows(con, tmp_path):
    """Every gathered row equals the stream's observed medoid at the catalog-selected index."""
    out = tmp_path / "out"
    store = _build(con, out)
    record = sv.materialize_search_view(
        store, con, _corpus(), "run-an-1", query_keyset=sv.QueryKeyset(query_song_ids=("s1",)), working_memory=2**20
    )
    vectors = _load_vectors(store, record)

    assert vectors.shape == record.key.matrix_shape
    assert vectors.dtype == np.float32
    assert len(record.row_addresses) == vectors.shape[0]
    # Row order is canonical (config, song, seg) ascending.
    assert record.row_addresses == tuple(sorted(record.row_addresses))

    # Each address came from a real seg_meta.medoid_source_patch_idx and its vector is exact.
    from scripts.embedding_research.catalog import segments_by_config_song

    for i, (config_id, song, seg_id, medoid_idx) in enumerate(record.row_addresses):
        metas = {m.seg_id: m for m in segments_by_config_song(con, config_id, song)}
        assert metas[seg_id].medoid_source_patch_idx == medoid_idx  # index verified vs membership
        expected = store.batch_gather(song, "effnet", [medoid_idx])[0]
        assert np.array_equal(vectors[i], expected)  # exact float32 equality, not approx


def test_disposable_payload_has_content_hash_and_root_relative_ref(con, tmp_path):
    """Payload (keys + float32 vectors) is stored with a sha256 content hash + root-relative ref."""
    out = tmp_path / "out"
    store = _build(con, out)
    record = sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)
    vec_file = _view_dir(store, record) / "vectors.npy"
    key_file = _view_dir(store, record) / "keys.json"
    assert vec_file.is_file() and key_file.is_file()
    keys = _load_keys(store, record)
    assert keys["keyset_hash"] == record.keyset_hash
    assert keys["keyset"]["matrix_shape"] == list(record.key.matrix_shape)
    # The on-disk keyset round-trips the recorded keyset exactly.
    assert keys["keyset"]["search_view_hash"] == record.key.search_view_hash
    # Content hash is a sha256 over the canonical payload.
    assert len(record.content_hash) == 64


# --------------------------------------------------------------------------- #
# P1-S2 regeneration — existence never authorizes reuse                         #
# --------------------------------------------------------------------------- #


def test_materialize_regenerates_even_when_view_file_exists(con, tmp_path, monkeypatch):
    """A prior view file does NOT short-circuit gathering — every call re-gathers + rewrites."""
    out = tmp_path / "out"
    store = _build(con, out)
    first = sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)
    assert _view_dir(store, first).is_dir()  # view file already on disk before the second pass

    # Re-materialize the SAME run after the file exists; gathering must happen again.
    original = store.batch_gather
    calls: dict[tuple[str, str], int] = {}

    def counting(song, backbone, indices):
        calls[(song, backbone)] = calls.get((song, backbone), 0) + 1
        return original(song, backbone, indices)

    monkeypatch.setattr(store, "batch_gather", counting)
    again = sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)
    assert calls, "view file existed yet batch_gather was not invoked — reuse was authorized"
    assert again.view_ref  # rewritten (file exists from the first pass)
    assert _view_dir(store, again).is_dir()


# --------------------------------------------------------------------------- #
# P1-S3 run_provenance.view_refs recording                                      #
# --------------------------------------------------------------------------- #


def test_view_refs_recorded_and_deduplicated_per_run(con, tmp_path):
    """view_refs gains one canonical keyset|content|ref line per view, deduped by keyset."""
    out = tmp_path / "out"
    store = _build(con, out)
    sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)
    sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)  # same keyset again
    rows = prov.read_run_provenance(con, run_id="run-an-1")
    assert len(rows) == 1
    assert rows[0]["phase"] == sv.VIEW_PHASE
    lines = rows[0]["view_refs"].splitlines()
    assert len(lines) == 1  # deduped by keyset
    keyset, content, ref = lines[0].split("|")
    assert len(keyset) == 64 and len(content) == 64
    assert ref.startswith(f"{sv.VIEW_DIR_NAME}/")


def test_view_refs_are_anchored_per_run_and_preserve_retained_run(con, tmp_path):
    """Each run records its own view; a retained run's references are left untouched."""
    out = tmp_path / "out"
    store = _build(con, out)
    prov.write_run_provenance(
        con,
        run_id="run-retained",
        phase=sv.VIEW_PHASE,
        status="complete",
        started_at=1,
        finished_at=2,
        retained=True,
        view_refs="retained-a|retained-b|views/retained",
    )
    sv.materialize_search_view(store, con, _corpus(), "run-an-2", working_memory=2**20)

    retained = prov.read_run_provenance(con, run_id="run-retained")[0]
    assert retained["view_refs"] == "retained-a|retained-b|views/retained"  # preserved, not touched
    an = prov.read_run_provenance(con, run_id="run-an-2")
    assert len(an) == 1
    assert "|views/" in an[0]["view_refs"]  # keyset|content|root-relative-ref line


# --------------------------------------------------------------------------- #
# P1-S4 exact logical-identity validation (stale rejection, no reuse)           #
# --------------------------------------------------------------------------- #


def test_validate_accepts_fresh_and_rejects_stale_corpus(con, tmp_path):
    """A fresh view validates; a changed corpus search_view_hash is rejected as stale."""
    from scripts.embedding_research import catalog_identity as ci

    out = tmp_path / "out"
    store = _build(con, out)
    record = sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)
    sv.validate_search_view_keyset(con, record)  # fresh → no error

    # Stale corpus: mutate membership (a real corpus change), so search_view_hash differs.
    row = con.execute("SELECT song_id, seg_id, member_patch_idx FROM seg_membership ORDER BY 1,2,3 LIMIT 1").fetchone()
    con.execute(
        "DELETE FROM seg_membership WHERE song_id = ? AND seg_id = ? AND member_patch_idx = ?",
        [row[0], row[1], row[2]],
    )
    assert ci.search_view_hash(con) != record.key.search_view_hash  # real drift confirmed
    with pytest.raises(sv.StaleSearchViewError):
        sv.validate_search_view_keyset(con, record)


def test_validate_rejects_stale_scoring_software_version(con, tmp_path, monkeypatch):
    """If the scoring software versions change, the recorded view is stale and rejected."""
    out = tmp_path / "out"
    store = _build(con, out)
    monkeypatch.setattr(sv, "scoring_software_versions", lambda: ("1", "2.5.2", "1.9.0"))
    record = sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)
    sv.validate_search_view_keyset(con, record)  # versions unchanged → fresh

    monkeypatch.setattr(sv, "scoring_software_versions", lambda: ("1", "9.9.9", None))
    with pytest.raises(sv.StaleSearchViewError):
        sv.validate_search_view_keyset(con, record)


def test_validate_rejects_stale_config_surface(con, tmp_path):
    """A config-surface change (adding a canonical config) makes the recorded view stale."""
    from scripts.embedding_research import catalog

    out = tmp_path / "out"
    store = _build(con, out)
    record = sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)
    # Add a second canonical config for the same backbone → config set / corpus hash change.
    catalog.build_segmentation_catalog(
        con,
        store,
        [
            catalog.SegConfigInput(
                backbone="effnet", bin_mode="temporal_global", threshold_configured=0.9, threshold_effective=0.9
            )
        ],
        list(record.song_ids),
        "run-cat-2",
        verify=True,
    )
    with pytest.raises(sv.StaleSearchViewError):
        sv.validate_search_view_keyset(con, record)


# --------------------------------------------------------------------------- #
# P1-S4 deliberate absences (no second registry, no indexes)                    #
# --------------------------------------------------------------------------- #


def test_no_view_manifest_no_second_registry_no_indexes(con, tmp_path):
    """Materializing adds no view_manifest/registry table, no PK/UNIQUE, no DuckDB index."""
    out = tmp_path / "out"
    store = _build(con, out)
    sv.materialize_search_view(store, con, _corpus(), "run-an-1", working_memory=2**20)
    names = _table_names(con)
    assert "view_manifest" not in names
    assert not {t for t in names if "manifest" in t or "classification" in t}
    # No new table was created to record the view — run_provenance holds the anchor.
    assert "run_provenance" in names
    assert int(con.execute("SELECT count(*) FROM duckdb_indexes()").fetchone()[0]) == 0
