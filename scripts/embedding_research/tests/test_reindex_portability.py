"""Spec-first proofs for portability, recreation and no-recompute (Plan B P1-S6).

Builds on the S1-S5 landed immutable filesystem core (``streams/publication.py``,
``streams/records.py``, ``streams/store.py``, ``streams/masks.py``,
``streams/reindex.py``) and proves the P1-S6 mandates:

* **Root relocation** — copy an ``OUTPUT_ROOT`` tree to a new root; every
  payload/manifest/commit-marker byte is preserved, ``lookup`` /
  ``batch_gather`` / ``reconcile`` still resolve to byte-identical payloads, the
  immutable digest identity is unchanged, and NO absolute path is ever persisted
  in any manifest/commit marker or rebuilt registry row (refs stay root-relative).
* **Export / import** (portability as the DD defines it) — move the artifact tree
  to a new root (export), then registry-deletion/recreation via ``reindex`` at the
  new root (import) reproduces byte-equal payloads, identical digests and
  identical deterministic registry cache metadata.
* **Registry deletion / recreation + no-recompute** — delete the registry (modelled
  here as a fresh empty-schema DB; ``reindex`` also clears registries) and reindex
  from the current manifests only, with audio/model/session/ONNX/CUDA sentinels
  raising; verify byte equality vs pre-deletion and prove no recompute /
  regeneration occurs (no inference, no segmentation, no mask re-derivation).
* **Byte equality / immutability** — payload + manifest bytes unchanged across
  relocation / reindex; the digest IS the payload byte sha256 (content addressed);
  no-byte-replacement honoured (identical re-publication reuses the existing
  artifact).
* **Strict / current-format negatives + CPU sentinels** — bare/``.vN`` names are
  never parsed at a relocated root; corrupt current payloads / absolute-path
  ``artifact_ref`` manifests are refused and readers fail closed; reindex, derived
  readers and mask regeneration never reach audio/models/ONNX/CUDA/segmentation.
* **Preservation invariants** — integer-millisecond timestamps, root-relative refs,
  the full retained registry status vocabulary (``pending``/``ready``/``missing``/
  ``corrupt``) and row contract are preserved after recreation.

Synthetic fixtures only; no real corpus/model/audio.
"""

from __future__ import annotations

import builtins
import hashlib
import inspect
import json
import shutil

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.masks import MaskPayload
from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    STREAM_REGISTRY_COLUMNS,
    STREAM_STATUSES,
    STREAM_TABLE,
    StreamNotFoundError,
)
from scripts.embedding_research.streams.reindex import reconcile_current_manifests, reindex
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

PATCH = 3
DIM = 4

# Registry columns that are NOT publish-time bookkeeping; reindex regenerates
# created_at/updated_at via now_ms(), so only the deterministic subset is compared.
_STREAM_DET = tuple(c for c in STREAM_REGISTRY_COLUMNS if c not in ("created_at", "updated_at"))
_HEAD_DET = tuple(c for c in HEAD_STREAM_REGISTRY_COLUMNS if c not in ("created_at", "updated_at"))

# Runtime libraries whose import/use would mean audio/model/session/ONNX/CUDA work.
_BANNED_RUNTIME = {"onnxruntime", "torch", "essentia", "tensorflow", "librosa"}


@pytest.fixture
def con():
    """A fresh in-memory DuckDB with the full research schema (post-deletion empty registries)."""
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    yield connection
    connection.close()


def _fresh_con():
    """A separate in-memory DB whose registries are empty (post-``research.duckdb``-deletion)."""
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    return connection


def _embeddings(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random((PATCH, DIM), dtype=np.float32)


def _mask(song_id: str = "s1", backbone: str = "effnet", run_id: str = "run-1") -> MaskPayload:
    return MaskPayload(
        song_id=song_id,
        backbone=backbone,
        patch_count=PATCH,
        mask=np.ones(PATCH, dtype=np.uint8),
        run_id=run_id,
        params_id="mask-params-1",
    )


def _seed(out, *, with_heads: bool = True) -> np.ndarray:
    """Publish a fully committed stream+mask observation group (+ optional head suite) to *out*.

    Uses a throwaway in-memory DB purely to drive the durable filesystem publication;
    registry rows there are irrelevant (``reindex`` rebuilds from the FS alone).
    Returns the committed stream embeddings for equality assertions.
    """
    out.mkdir(parents=True, exist_ok=True)
    seed_con = _fresh_con()
    try:
        store = StreamStore(seed_con, output_root=out)
        emb = _embeddings()
        rec = store.publish("s1", "effnet", emb, run_id="run-1")
        store.publish_observation_group(rec, _mask())
        if with_heads:
            head_arrays = {"head_logit": np.arange(PATCH * 2, dtype=np.float32).reshape(PATCH, 2)}
            HeadStreamStore(seed_con, output_root=out).publish(
                "s1",
                "effnet",
                head_arrays,
                run_id="run-1",
                patch_count=PATCH,
                alignment_version="1",
                expected_head_ids={"head_logit"},
                stream_ref=rec.artifact_ref,
            )
        return emb
    finally:
        seed_con.close()


def _snapshot_bytes(root) -> dict[str, str]:
    """Map every relative path under *root* to the sha256 of its current bytes."""
    root = root.resolve()
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root))
            snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _payload_ref(song_id: str, backbone: str, digest: str, subdir: str, suffix: str) -> str:
    return f"{subdir}/{song_id}.{backbone}.{digest}{suffix}"


def _digest_of(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deterministic_row(con, table: str, columns: tuple[str, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(con.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall())


def _manifest_texts(root) -> list[tuple[str, str]]:
    """Every JSON manifest/commit-marker relative path + raw text under *root*."""
    root = root.resolve()
    return [(str(path.relative_to(root)), path.read_text(encoding="utf-8")) for path in sorted(root.rglob("*.json"))]


def _assert_no_absolute_path(root, root_abs: str) -> None:
    """Every persisted manifest/commit marker is free of the absolute root, refs stay relative."""
    root_abs = str(root_abs)
    for rel, text in _manifest_texts(root):
        assert root_abs not in text, f"absolute path leaked into {rel}: {root_abs!r} in manifest"
        doc = json.loads(text)
        assert isinstance(doc, dict)
        # A manifest must never persist an absolute artifact ref.
        for key in ("artifact_ref", "stream_ref", "mask_ref"):
            value = doc.get(key)
            if isinstance(value, str) and value:
                assert not value.startswith("/"), f"{key} is absolute in {rel}: {value!r}"
                assert ".." not in value, f"{key} traverses in {rel}: {value!r}"


def _stream_payload_file(out) -> tuple:
    """Return (payload_path, manifest_path) for the single committed stream under *out*."""
    payload = next((out / "streams").glob("*.npy"))
    return payload, payload.with_suffix(".json")


def _head_npz_file(out):
    return next((out / "heads").glob("*.npz"))


def _mask_npy_file(out):
    return next((out / "audio_masks").glob("*.npy"))


# ── root relocation: byte preservation + digest identity ──────────────────────


def test_relocation_preserves_payload_bytes_and_digest_identity(tmp_path, con):
    out1 = tmp_path / "root1"
    emb = _seed(out1)
    before = _snapshot_bytes(out1)
    assert reindex(out1, con).clean

    rec_before = StreamStore(con, output_root=out1).lookup("s1", "effnet")
    assert rec_before.status == "ready"

    out2 = tmp_path / "root2"  # relocate: whole tree copied to a new root
    shutil.copytree(out1, out2)
    assert _snapshot_bytes(out2) == before  # byte-equal export

    con2 = _fresh_con()
    assert reindex(out2, con2).clean
    rec_after = StreamStore(con2, output_root=out2).lookup("s1", "effnet")

    # Immutable digest identity unchanged by relocation.
    assert rec_after.artifact_ref == rec_before.artifact_ref
    assert rec_after.fingerprint_sha256 == rec_before.fingerprint_sha256

    # Derived readers resolve byte-identical payloads at the relocated root.
    gathered = StreamStore(con2, output_root=out2).batch_gather("s1", "effnet", [0, 1, 2])
    assert gathered.dtype == np.float32 and gathered.shape == (PATCH, DIM)
    assert np.array_equal(gathered, emb, equal_nan=False)
    head = HeadStreamStore(con2, output_root=out2).lookup("s1", "effnet")
    assert head.status == "ready" and head.artifact_ref.startswith("heads/")


def test_export_import_reproduces_bytes_digests_and_registry_metadata(tmp_path, con):
    out = tmp_path / "export_src"
    emb = _seed(out)
    pre_bytes = _snapshot_bytes(out)
    assert reindex(out, con).clean
    pre_stream_rows = _deterministic_row(con, STREAM_TABLE, _STREAM_DET)
    pre_head_rows = _deterministic_row(con, "head_stream_registry", _HEAD_DET)

    export_root = tmp_path / "import_dst"  # export = copy to a new root
    shutil.copytree(out, export_root)

    con2 = _fresh_con()  # registry deleted/recreated at the imported root
    report = reindex(export_root, con2)
    assert report.clean, report

    assert _snapshot_bytes(export_root) == pre_bytes  # payload + manifest bytes byte-equal

    # Deterministic registry cache metadata (digest identity, provenance, layout) is identical.
    assert _deterministic_row(con2, STREAM_TABLE, _STREAM_DET) == pre_stream_rows
    assert _deterministic_row(con2, "head_stream_registry", _HEAD_DET) == pre_head_rows

    gathered = StreamStore(con2, output_root=export_root).batch_gather("s1", "effnet", [1, 2])
    assert np.array_equal(gathered, emb[[1, 2]], equal_nan=False)


# ── registry deletion / recreation: byte equality + no recompute ──────────────


def test_registry_deletion_recreation_reproduces_byte_equal_state(tmp_path):
    out = tmp_path / "root"
    emb = _seed(out)
    pre_bytes = _snapshot_bytes(out)

    con1 = _fresh_con()  # first population (registry present)
    assert reindex(out, con1).clean
    pre_ref = StreamStore(con1, output_root=out).lookup("s1", "effnet").artifact_ref

    con2 = _fresh_con()  # research.duckdb deleted -> empty registries
    assert reindex(out, con2).clean

    # Reindex writes registry rows ONLY — the filesystem bytes are untouched.
    assert _snapshot_bytes(out) == pre_bytes
    post_ref = StreamStore(con2, output_root=out).lookup("s1", "effnet").artifact_ref
    assert post_ref == pre_ref  # identical immutable digest identity

    gathered = StreamStore(con2, output_root=out).batch_gather("s1", "effnet", [0, 2])
    assert np.array_equal(gathered, emb[[0, 2]], equal_nan=False)


def test_manifest_and_commit_bytes_stay_byte_identical_after_reindex(tmp_path):
    out = tmp_path / "root"
    _seed(out)
    pre_files = _snapshot_bytes(out)

    # Identify the specific stream/mask/head manifests + commit markers + payloads.
    stream_payload, stream_manifest = _stream_payload_file(out)
    mask_payload = _mask_npy_file(out)
    head_payload = _head_npz_file(out)
    commit = next((out / "observation_commits").glob("*.json"))
    targeted = {
        "stream_payload": stream_payload,
        "stream_manifest": stream_manifest,
        "mask_payload": mask_payload,
        "head_payload": head_payload,
        "commit": commit,
    }
    pre_digests = {name: _digest_of(path) for name, path in targeted.items()}

    con = _fresh_con()
    assert reindex(out, con).clean

    assert _snapshot_bytes(out) == pre_files
    for name, path in targeted.items():
        assert _digest_of(path) == pre_digests[name], f"{name} bytes changed across reindex"


def test_recreation_does_not_regenerate_masks_or_touch_artifacts(tmp_path):
    out = tmp_path / "root"
    _seed(out)
    mask_npy = _mask_npy_file(out)
    mask_pre = mask_npy.read_bytes()
    commit_marker = next((out / "observation_commits").glob("*.json"))
    commit_pre = commit_marker.read_bytes()

    con = _fresh_con()
    assert reindex(out, con).clean

    # Reindex never re-derives / regenerates: mask payload + commit marker byte-identical,
    # and no new artifact was created (file set unchanged).
    assert mask_npy.read_bytes() == mask_pre
    assert commit_marker.read_bytes() == commit_pre

    # Structural: the reindex code path can never reach the recompute machinery.
    raw = inspect.getsource(reconcile_current_manifests) + "\n" + inspect.getsource(reindex)
    for token in (
        "derive_audio_mask",
        "regenerate_masks",
        "create_session",
        "session.run",
        "compute_log_mel",
        "extract_patches",
        "onnx",
        "cuda",
    ):
        assert token not in raw, f"reindex source must not reference {token!r}"


# ── byte equality / immutability / content addressing ─────────────────────────


def test_digest_identity_is_payload_byte_sha256_content_addressed(tmp_path):
    out = tmp_path / "root"
    _seed(out)

    from scripts.embedding_research.streams.publication import parse_artifact_name

    for payload, suffix, subdir in (
        (_stream_payload_file(out)[0], ".npy", "streams"),
        (_mask_npy_file(out), ".npy", "audio_masks"),
        (_head_npz_file(out), ".npz", "heads"),
    ):
        parsed = parse_artifact_name(payload.name, suffix)
        assert parsed is not None, payload.name
        assert parsed.digest == _digest_of(payload), "filename digest != payload byte sha256"
        assert payload.parent.name == subdir


def test_no_byte_replacement_and_idempotent_reuse(tmp_path):
    out = tmp_path / "root"
    seed_con = _fresh_con()
    try:
        store = StreamStore(seed_con, output_root=out)
        emb = _embeddings()
        rec1 = store.publish("s1", "effnet", emb, run_id="run-1")
        before = _snapshot_bytes(out)
        rec1_b = rec1.artifact_ref

        # Identical re-publication (same run_id -> identical payload AND manifest bytes) reuses.
        rec2 = store.publish("s1", "effnet", emb, run_id="run-1")
        assert rec2.artifact_ref == rec1_b
        assert _snapshot_bytes(out) == before  # no new file, no byte replacement
        assert len(list((out / "streams").glob("*.npy"))) == 1
    finally:
        seed_con.close()


# ── CPU sentinels: reindex + derived readers never touch audio/model/ONNX/CUDA ─


def test_recreation_and_derived_reads_are_cpu_only(tmp_path, monkeypatch):
    out = tmp_path / "root"
    emb = _seed(out)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in _BANNED_RUNTIME:
            raise AssertionError(f"derived path reached a banned runtime import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    con = _fresh_con()
    assert reindex(out, con).clean  # reindex never opens audio/models/sessions/ONNX/CUDA

    # Derived readers (lookup / batch_gather / head gather) stay CPU-only and return data.
    store = StreamStore(con, output_root=out)
    assert store.lookup("s1", "effnet").status == "ready"
    gathered = store.batch_gather("s1", "effnet", [0, 1, 2])
    assert gathered.dtype == np.float32 and np.array_equal(gathered, emb, equal_nan=False)
    head = HeadStreamStore(con, output_root=out)
    assert head.lookup("s1", "effnet").status == "ready"
    head_gathered = head.batch_gather("s1", "effnet", [0, 2])
    assert head_gathered.dtype == np.float32 and head_gathered.shape == (2, 2)
    assert bool(np.isfinite(head_gathered).all())


# ── strict / current-format negatives at a relocated root ─────────────────────


def test_relocated_root_refuses_absolute_path_artifact_ref(tmp_path, con):
    out = tmp_path / "root"
    _seed(out, with_heads=False)

    # Tamper the committed stream manifest's artifact_ref to an absolute path.
    _, stream_manifest = _stream_payload_file(out)
    data = json.loads(stream_manifest.read_text())
    data["artifact_ref"] = f"/abs/elsewhere/s1.effnet.{'0' * 64}.npy"
    stream_manifest.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))

    report = reconcile_current_manifests(out, con)
    assert not report.clean
    assert report.ready == 0
    assert any("manifest" in issue and ("invalid" in issue or "refused" in issue) for issue in report.issues)
    with pytest.raises(StreamNotFoundError):
        StreamStore(con, output_root=out).lookup("s1", "effnet")


def test_relocated_root_ignores_legacy_bare_versioned_names(tmp_path, con):
    out = tmp_path / "root"
    _seed(out)
    assert reindex(out, con).clean

    relocated = tmp_path / "relocated"
    shutil.copytree(out, relocated)
    # Legacy/bare/.vN payloads + manifests MUST be invisible, never parsed/adopted.
    for name in ("s1.effnet.v3.npy", "s1.effnet.npy", "s1.effnet.v2.json"):
        (relocated / "streams" / name).write_text("ignored-legacy", encoding="utf-8")

    report = reconcile_current_manifests(relocated, con)
    assert report.clean, report
    assert report.ready == 2
    rows = con.execute(f"SELECT song_id, backbone FROM {STREAM_TABLE}").fetchall()
    assert rows == [("s1", "effnet")]


def test_relocated_root_refuses_corrupt_current_payload_fail_closed(tmp_path, con):
    out = tmp_path / "root"
    _seed(out, with_heads=False)

    payload, _ = _stream_payload_file(out)
    payload.write_bytes(b"corrupt-bytes-not-a-valid-npy")

    report = reconcile_current_manifests(out, con)
    assert not report.clean
    assert report.ready == 0
    assert any("payload" in issue and "refused" in issue for issue in report.issues)
    with pytest.raises(StreamNotFoundError):
        StreamStore(con, output_root=out).lookup("s1", "effnet")


# ── preservation invariants: integer-ms, root-relative, status vocabulary ─────


def test_recreated_registry_rows_are_integer_ms_and_root_relative(tmp_path):
    out = tmp_path / "root"
    _seed(out)
    con = _fresh_con()
    assert reindex(out, con).clean

    for table, cols in (
        (STREAM_TABLE, STREAM_REGISTRY_COLUMNS),
        ("head_stream_registry", HEAD_STREAM_REGISTRY_COLUMNS),
    ):
        row = con.execute(f"SELECT * FROM {table}").fetchone()
        assert row is not None
        d = dict(zip(cols, row, strict=False))
        # Integer-millisecond timestamps (project convention), not seconds.
        for ts_col in ("created_at", "updated_at"):
            assert isinstance(d[ts_col], int)
            assert d[ts_col] > 1_000_000_000_00, f"{table}.{ts_col} must be integer ms, got {d[ts_col]}"
        # Root-relative artifact ref (never an absolute path).
        ref = d["artifact_ref"]
        assert isinstance(ref, str) and ref.startswith(("streams/", "heads/")) and not ref.startswith("/")

    # The observation-commit marker's own created_at is integer ms too.
    commit = json.loads(next((out / "observation_commits").glob("*.json")).read_text())
    assert isinstance(commit["created_at"], int) and commit["created_at"] > 1_000_000_000_00


def test_status_vocabulary_and_row_contract_preserved_ready_only_current(tmp_path, con):
    assert frozenset({"pending", "ready", "missing", "corrupt"}) == STREAM_STATUSES

    out = tmp_path / "root"
    _seed(out, with_heads=False)
    assert reindex(out, con).clean

    # Fully valid committed group -> a retained 'ready' cache/index row (C/E contract).
    (song_id, backbone, artifact_ref, patch_count, *_) = con.execute(f"SELECT * FROM {STREAM_TABLE}").fetchone()
    assert song_id == "s1" and backbone == "effnet"
    assert artifact_ref.startswith("streams/s1.effnet.") and patch_count == PATCH
    (status,) = con.execute("SELECT status FROM stream_registry").fetchone()
    assert status == "ready"

    # Deleting the commit marker un-commits the group -> refused, reader fails closed.
    commit = next((out / "observation_commits").glob("*.json"))
    commit.unlink()
    con_b = _fresh_con()
    report = reconcile_current_manifests(out, con_b)
    assert not report.clean
    assert any("commit marker" in issue for issue in report.issues)
    assert report.ready == 0
    with pytest.raises(StreamNotFoundError):
        StreamStore(con_b, output_root=out).lookup("s1", "effnet")


def test_relocated_root_leaves_no_absolute_path_in_persisted_manifests(tmp_path, con):
    out = tmp_path / "root1"
    _seed(out)
    assert reindex(out, con).clean

    relocated = tmp_path / "root2"
    shutil.copytree(out, relocated)
    con2 = _fresh_con()
    assert reindex(relocated, con2).clean

    # Neither the original nor the relocated root's absolute path is persisted anywhere,
    # and every artifact ref in every manifest/commit is root-relative.
    _assert_no_absolute_path(out, out)
    _assert_no_absolute_path(relocated, out)
    _assert_no_absolute_path(relocated, relocated)

    # Rebuilt registry rows carry only root-relative refs (no absolute path).
    for table in (STREAM_TABLE, "head_stream_registry"):
        for (ref,) in con2.execute(f"SELECT artifact_ref FROM {table}").fetchall():
            assert not ref.startswith("/") and ".." not in ref
