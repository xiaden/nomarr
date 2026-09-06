"""P1-S4 proofs (c) catalog isolation and (f) disposability/reindex/reuse equality.

These proofs run against the AUTHORITATIVE published-catalog layout (``catalogs/<id>/`` +
``catalogs/current.json``) that ``run.py`` derived phases now select via
``catalog_storage.open_current_catalog`` (P1-S4 reopen).  They pin:

* (c) catalog isolation — an EXISTING-but-unclean current catalog (WAL-bearing) is refused
      by ``analyze``/``head-analysis`` with a directive to ``verify`` (DD L272-273), never
      silently read via a newest-candidate fallback; a valid non-current published catalog
      remains intact/reportable; ``verify`` owns WAL recovery (reporting + remediation).
* (f) disposability/reuse — closing all research connections, deleting ``research.duckdb``,
      running ``reindex`` with CPU sentinels raising (no segmentation/inference recompute),
      then re-running ``analyze`` (+ ``head-analysis``) against the surviving catalog +
      filesystem reproduces the pre-deletion results (bounded-exact equality) while no
      payload bytes change.

All fixtures are synthetic (numpy/duckdb only); no audio/model/ONNX/CUDA is touched and a
raised sentinel is never treated as success.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.masks import MaskPayload


def _unit(rng, n: int, d: int) -> np.ndarray:
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _cfg(out, *, run_id="fx", verify=False, strict=False) -> dict:
    return {
        "verify": verify,
        "strict": strict,
        "retained": False,
        "force": False,
        "k": 10,
        "backbones": ["effnet"],
        "heads": None,
        "output_root": str(out),
        "report_dir": str(out / "report"),
        "run_id": run_id,
        "config_hash": "testcfg",
    }


def _seg_config(threshold=0.7):
    from scripts.embedding_research.catalog import SegConfigInput

    return SegConfigInput(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _seed_songs(con, songs=("s1", "s2"), artists=None):
    artists = artists or {s: s.upper() for s in songs}
    for song in songs:
        con.execute(
            "INSERT INTO songs (song_id, path, artist) VALUES (?, ?, ?)",
            (song, f"/audio/{song}.mp3", artists.get(song, song.upper())),
        )


_FOUR = ("s1", "s2", "s3", "s4")
_A_ARTISTS = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}


def _four_streams():
    rng = np.random.default_rng(3)
    return {(s, "effnet"): _unit(rng, 10, 6) for s in _FOUR}


def _streams(songs=("s1", "s2")):
    rng = np.random.default_rng(3)
    return {(s, "effnet"): _unit(rng, 10, 6) for s in songs}


def _prov_status(con, phase):
    row = con.execute(
        "SELECT status FROM run_provenance WHERE phase = ? ORDER BY started_at DESC LIMIT 1",
        (phase,),
    ).fetchone()
    return None if row is None else row[0]


# --------------------------------------------------------------------------- #
# (c) catalog isolation: WAL-bearing current refused w/ verify directive      #
# --------------------------------------------------------------------------- #


def test_c_wal_bearing_current_refused_by_derived_phases_with_verify_directive(con, tmp_path, compact_catalog_factory):
    out = tmp_path / "out"
    _seed_songs(con)
    harness_a = compact_catalog_factory(
        con, str(out), streams=_streams(), configs=[_seg_config(0.7)], song_ids=["s1", "s2"], run_id="run-A"
    )
    # Second distinct published catalog (different threshold -> different canonical identity)
    # becomes CURRENT because it is published last.
    harness_b = compact_catalog_factory(
        con, str(out), streams=_streams(), configs=[_seg_config(0.6)], song_ids=["s1", "s2"], run_id="run-B"
    )
    a_cid = harness_a.snapshot_path.parent.name
    b_cid = harness_b.snapshot_path.parent.name
    assert a_cid != b_cid  # two distinct published catalog dirs
    harness_a.close()
    harness_b.close()

    from scripts.embedding_research import catalog_storage as _cs

    current_id = _cs._parse_current_catalog(out)
    assert current_id == b_cid  # current.json selects the last-published (run-B)
    assert a_cid != current_id

    # Make the CURRENT (run-B) catalog WAL-bearing -> typed refusal.
    wal = out / "catalogs" / current_id / f"{_cs.CATALOG_DB_FILE}.wal"
    wal.write_bytes(b"not-a-real-wal-but-nonempty")

    # analyze refuses: the _CatalogRefusalError message directs the operator to verify.
    with pytest.raises(run_mod._CatalogRefusalError) as exc_a:
        run_mod._run_single_phase(con, "analyze", _cfg(out))
    assert "verify" in str(exc_a.value)
    assert _prov_status(con, "analyze") == "failed"

    # head-analysis refuses the same way.
    with pytest.raises(run_mod._CatalogRefusalError) as exc_h:
        run_mod._run_single_phase(con, "head-analysis", _cfg(out))
    assert "verify" in str(exc_h.value)

    # The valid NON-current published catalog is unaffected (isolation of the refusal):
    # it still opens cleanly through the authoritative reader and remains queryable.
    ha_reopen = _cs.open_snapshot_file(harness_a.snapshot_path, read_only=True)
    try:
        n_configs = ha_reopen.con.execute("SELECT count(*) FROM seg_config").fetchone()[0]
    finally:
        ha_reopen.close()
    assert n_configs >= 1  # the refused current catalog did not take down the valid sibling

    # verify owns remediation: it reports the WAL refusal (never crashes) ...
    from scripts.embedding_research.verify import verify_current_artifacts

    rep = verify_current_artifacts(out)
    assert any("WAL" in r or "wal" in r or "recover" in r or "checkpoint" in r for r in rep.refusals + rep.recovered)

    # ... and once the operator removes/remediates the WAL the same catalog re-opens verified.
    wal.unlink()
    handle = _cs.open_current_catalog(out, verify=True)
    assert handle.catalog_id == current_id
    handle.close()
    rep2 = verify_current_artifacts(out)
    assert rep2.verified >= 1 and not rep2.refusals


# --------------------------------------------------------------------------- #
# (f) research.duckdb deletion -> reindex -> analyze/head-analysis reuse       #
# --------------------------------------------------------------------------- #


def _gather_analyze_metrics(con):
    return con.execute(
        "SELECT * FROM analyze_metrics WHERE run_id = 'fx' ORDER BY strategy_key, strategy_type"
    ).fetchall()


def test_f_research_db_delete_reindex_rerun_reuse_equality(tmp_path, monkeypatch):
    out = tmp_path / "out"
    db_path = tmp_path / "research.duckdb"

    # 1) seed on-disk research DB + published catalog (current.json authoritative).
    con = __import__("duckdb").connect(str(db_path))
    ensure_schema(con)
    _seed_songs(con, songs=_FOUR, artists=_A_ARTISTS)
    from scripts.embedding_research import catalog_storage as _cs
    from scripts.embedding_research.catalog import build_segmentation_catalog
    from scripts.embedding_research.streams import make_current_mask_resolver, make_current_stream_resolver
    from scripts.embedding_research.streams.store import StreamStore

    store = StreamStore(con, output_root=str(out))
    for (song, bb), mat in _four_streams().items():
        rec = store.publish(song, bb, mat, run_id="run-embed")
        mask = MaskPayload(
            song_id=song,
            backbone=bb,
            patch_count=int(mat.shape[0]),
            mask=np.ones(mat.shape[0], dtype=np.uint8),
            run_id="run-embed",
            params_id="mask-params-1",
            audio_content_sha256="0" * 64,  # valid 64-hex: group-resolver readiness requires it
        )
        store.publish_observation_group(rec, mask)
    store.reconcile()  # promote committed groups to ready so the catalog build sees them
    rep = build_segmentation_catalog(
        make_current_stream_resolver(store),
        make_current_mask_resolver(store),
        [_seg_config(0.7)],
        list(_FOUR),
        output_root=str(out),
        run_id="run-cat",
        verify=True,
    )
    assert rep.verify_ok is True
    staging = out / "catalogs" / ".staging-run-cat"
    dcon = __import__("duckdb").connect(str(staging / _cs.CATALOG_DB_FILE), read_only=True)
    try:
        manifest = _cs.derive_catalog_manifest(dcon)
    finally:
        dcon.close()
    ph = _cs.publish_catalog_snapshot(staging, manifest=manifest)
    catalog_id = ph.catalog_id
    ph.close()

    # 2) CPU sentinels: any audio/model/ONNX/CUDA/session/segmentation recompute must raise.
    fired: list[str] = []

    def _boom(tag: str):
        def _f(*_a, **_k):
            fired.append(tag)
            raise AssertionError(f"{tag} recompute attempted during maintenance/reuse")

        return _f

    import scripts.embedding_research.common.embed as _embed_mod
    import scripts.embedding_research.common.infer_heads as _infer_heads_mod
    from scripts.embedding_research import catalog as _catalog_mod
    from scripts.embedding_research import config as _config_mod

    monkeypatch.setattr(_config_mod, "discover_audio", _boom("discover_audio"))
    monkeypatch.setattr(_embed_mod, "embed", _boom("embed"))
    monkeypatch.setattr(_infer_heads_mod, "infer_heads", _boom("infer_heads"))
    monkeypatch.setattr(_catalog_mod, "build_segmentation_catalog", _boom("segment_catalog"))

    # 3) pre-deletion run of analyze + head-analysis against the published catalog.
    run_mod._run_single_phase(con, "analyze", _cfg(out, run_id="fx"))
    run_mod._run_single_phase(con, "head-analysis", _cfg(out, run_id="fx"))
    assert _prov_status(con, "analyze") == "complete"  # analyze is self-recorded
    before_metrics = _gather_analyze_metrics(con)
    assert before_metrics, "analyze must produce run-scoped metrics over the published catalog"
    before_fs = {
        str(p.relative_to(out)): p.read_bytes()
        for p in sorted(out.rglob("*"))
        if p.is_file() and ".staging" not in str(p)
    }

    # 4) close ALL research connections, delete the disposable DB (+ WAL) and views.
    con.close()
    for suffix in ("", ".wal"):
        p = tmp_path / f"research.duckdb{suffix}"
        if p.is_file():
            p.unlink()
    view_dir = out / "views"
    if view_dir.is_dir():
        import shutil

        shutil.rmtree(view_dir)

    # 5) reindex from the surviving filesystem + published catalog with sentinels active.
    con2 = __import__("duckdb").connect(str(db_path))
    ensure_schema(con2)
    from scripts.embedding_research.streams.reindex import reindex

    ri = reindex(out, con2)
    # Corpus/song metadata is Tier-1 corpus metadata (persists on disk as corpus/ and is
    # restored by the real pipeline); re-establish it in the fresh research DB.  This is NOT
    # segmentation/inference recompute — those seams are sentinel-guarded below and stay silent.
    _seed_songs(con2, songs=_FOUR, artists=_A_ARTISTS)
    assert not ri.issues, ri.issues
    assert ri.rows_rebuilt >= 1

    # 6) re-run analyze + head-analysis against the surviving catalog + fs.
    run_mod._run_single_phase(con2, "analyze", _cfg(out, run_id="fx"))
    run_mod._run_single_phase(con2, "head-analysis", _cfg(out, run_id="fx"))
    after_metrics = _gather_analyze_metrics(con2)
    assert after_metrics == before_metrics, "analyze metrics must reproduce bitwise after DB deletion + reindex"
    assert _prov_status(con2, "analyze") == "complete"

    # 7) no segmentation/inference recompute fired; no payload bytes changed.
    assert fired == [], f"sentinels fired during maintenance/reuse: {fired}"
    after_fs = {
        str(p.relative_to(out)): p.read_bytes()
        for p in sorted(out.rglob("*"))
        if p.is_file() and ".staging" not in str(p)
    }
    assert set(after_fs) == set(before_fs)
    for key in before_fs:
        assert after_fs[key] == before_fs[key], f"payload bytes changed for {key}"
    con2.close()
    assert catalog_id  # keep reference to published catalog alive for lint clarity


# ── P1-S1/P1-S7: reindex rebuilds ONLY committed groups (never a stream-only artifact) ──


def test_reindex_rebuilds_only_committed_groups_never_stream_only(tmp_path):
    """The category-(f) disposability proof extends to readiness: after the research DB is
    thrown away, FS reindex restores ready status ONLY for songs whose stream has a valid
    committed observation group.  A stream published without a committed group is refused
    and never reported ready (missing mask must fail closed, never read as no-silence).
    """
    import duckdb

    from scripts.embedding_research.streams import StreamStore
    from scripts.embedding_research.streams.reindex import reindex

    out = tmp_path
    con = duckdb.connect()
    ensure_schema(con)
    store = StreamStore(con, output_root=str(out))
    rng = np.random.RandomState(0)

    def _emb(n):
        return rng.rand(n, 4).astype(np.float32)

    # s1: fully committed observation group (stream + aligned mask + commit marker).
    rec1 = store.publish("s1", "effnet", _emb(5), run_id="run-embed")
    store.publish_observation_group(
        rec1,
        MaskPayload(
            song_id="s1",
            backbone="effnet",
            patch_count=5,
            mask=np.ones(5, dtype=np.uint8),
            run_id="run-embed",
            params_id="mask-params-1",
            audio_content_sha256="0" * 64,  # valid 64-hex identity: shared group-readiness requires it
        ),
    )
    # s2: stream-only artifact (published, NO committed group) — must never become ready.
    store.publish("s2", "effnet", _emb(5), run_id="run-embed")
    con.close()

    con2 = duckdb.connect()
    ensure_schema(con2)
    ri = reindex(out, con2)
    status_by_song = {
        r[0]: r[1] for r in con2.execute("SELECT song_id, status FROM stream_registry ORDER BY song_id").fetchall()
    }
    assert status_by_song.get("s1") == "ready", "committed group must rebuild ready"
    assert status_by_song.get("s2") != "ready", "stream-only artifact must not rebuild ready"
    assert any("commit" in i.lower() or "marker" in i.lower() for i in ri.issues), ri.issues


def test_reindex_head_path_is_cpu_only_and_marker_authoritative(con, tmp_path, monkeypatch):
    """Reindex rebuilds the head suite ONLY from the CURRENT marker, with CPU-only sentinels."""
    import builtins

    import duckdb
    import numpy as np

    from scripts.embedding_research.streams.masks import MaskPayload
    from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

    out = tmp_path / "root"
    seed_con = duckdb.connect(":memory:")
    ensure_schema(seed_con)
    try:
        store = StreamStore(seed_con, output_root=out)
        emb = np.random.default_rng(0).random((3, 4), dtype=np.float32)
        rec = store.publish("s1", "effnet", emb, run_id="run-1")
        store.publish_observation_group(
            rec,
            MaskPayload(
                song_id="s1",
                backbone="effnet",
                patch_count=3,
                mask=np.ones(3, dtype=np.uint8),
                run_id="run-1",
                params_id="p",
                audio_content_sha256="0" * 64,
            ),
        )
        HeadStreamStore(seed_con, output_root=out).publish(
            "s1",
            "effnet",
            {"head_logit": np.arange(6, dtype=np.float32).reshape(3, 2)},
            run_id="run-1",
            patch_count=3,
            alignment_version="1",
            expected_head_ids={"head_logit"},
            stream_ref=rec.artifact_ref,
        )
    finally:
        seed_con.close()

    # Behavioral CPU sentinel: any banned-runtime import or inference/audio call during
    # reindex must raise (reindex + the CURRENT-head resolution are filesystem-only).
    real_import = builtins.__import__
    banned_runtime = {"onnxruntime", "torch", "essentia", "tensorflow", "librosa"}

    def _guarded_import(name, *a, **k):
        if name.split(".")[0] in banned_runtime:
            raise AssertionError(f"reindex reached a banned runtime import: {name}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    import scripts.embedding_research.common.infer_heads as _infer_heads_mod

    def _forbidden(*_a, **_k):
        raise AssertionError("reindex must never run inference")

    monkeypatch.setattr(_infer_heads_mod, "infer_heads", _forbidden)

    from scripts.embedding_research.streams.reindex import reindex

    report = reindex(out, con)
    assert report.clean
    head = HeadStreamStore(con, output_root=out).lookup("s1", "effnet")
    assert head.status == "ready"
    assert head.artifact_ref.startswith("heads/")
