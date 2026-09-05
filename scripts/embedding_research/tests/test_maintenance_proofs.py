"""P1-S3/P1-S4 maintenance proof spec tests (DD frozen-observation corrective pass).

Synthetic-current-format fixtures only.  These assert the executable proof
items that the current-format wiring fully owns:

(a) ``verify --strict`` freshly hashes every payload, so an mtime-preserving
    same-size tamper (payload rewritten, digest-name kept) is caught ONLY under
    strict verification.
(b) ``cleanup`` is current-format-only: staging / stray / views candidates are
    derived from the current grammar + manifest relationships alone; legacy /
    bare / ``.vN`` names are never classified or removed; ``--dry-run`` is the
    default for staging/stray.
(d) the exclusive run lock exits 2 on contention with a diagnostic and is
    released on both the success and the failure path (lockfile appears and
    disappears around a guarded block).
(e) ``reset --scope analysis`` removes only the disposable research DB (+WAL)
    and views, preserving corpus/streams/heads/audio_masks/observation_commits/
    catalogs byte-for-byte.
(g) the maintenance bodies (verify/cleanup) are CPU-only — importing them never
    pulls onnxruntime / torch / CUDA / nomarr production.

Catalog-integration proofs that depend on the published ``catalogs/<id>`` +
``current.json`` authoritative layout (which ``run.py`` analyze/head-analysis do
not yet consume — that wiring is a P1-S5 residual) are intentionally deferred
and named in the P1-S4 step annotation, not half-implemented here.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import cleanup, verify
from scripts.embedding_research import run as run_mod

# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_payload(root: pathlib.Path, sub: str, song: str, backbone: str, data: bytes, suffix: str) -> pathlib.Path:
    """Write *data* under ``root/sub/<song>.<backbone>.<sha256(data)><suffix>``.

    The digest-named file is internally consistent (its content hash equals the
    digest that names it), so strict verify passes until the content is rewritten.
    """
    subdir = root / sub
    subdir.mkdir(parents=True, exist_ok=True)
    name = f"{song}.{backbone}.{_sha256(data)}{suffix}"
    payload = subdir / name
    payload.write_bytes(data)
    return payload


def _write_manifest(payload: pathlib.Path) -> None:
    payload.with_suffix(".json").write_text(json.dumps({"kind": "stream", "schema_version": "1"}), encoding="utf-8")


def _tree_digests(root: pathlib.Path) -> dict[str, str]:
    """Recursively map every file under *root* to its sha256 (byte-identity proof)."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = _sha256(p.read_bytes())
    return out


# --------------------------------------------------------------------------- #
# (a) verify --strict fresh-hash tamper detection                             #
# --------------------------------------------------------------------------- #


def test_strict_verify_flags_samesize_tamper_only_under_strict(tmp_path):
    """Tampering with a payload (content rewritten, digest-name kept, same size)
    is detected ONLY by ``verify_current_artifacts(..., strict=True)``."""
    import io

    buf = io.BytesIO()
    np.save(buf, np.arange(24, dtype=np.float32))
    data = buf.getvalue()  # a valid loadable .npy document
    payload = _digest_payload(tmp_path, "streams", "s1", "effnet", data, ".npy")
    _write_manifest(payload)

    # Baseline: clean tree passes in both modes.
    assert verify.verify_current_artifacts(tmp_path, strict=False).refusals == []
    assert verify.verify_current_artifacts(tmp_path, strict=True).refusals == []

    # Same-size tamper (rewrite in place, name/manifest unchanged).
    tampered = bytearray(data)
    tampered[-1] ^= 0xFF
    assert len(tampered) == len(data)
    payload.write_bytes(bytes(tampered))

    non_strict = verify.verify_current_artifacts(tmp_path, strict=False)
    strict = verify.verify_current_artifacts(tmp_path, strict=True)
    assert non_strict.refusals == [], "non-strict must not rehash and must not catch a same-size tamper"
    assert any("does not match its name digest" in r for r in strict.refusals), strict.refusals


# --------------------------------------------------------------------------- #
# (b) cleanup is current-format-only                                          #
# --------------------------------------------------------------------------- #


def _seed_mixed_artifact_tree(root: pathlib.Path) -> None:
    # A current-format payload WITH a sibling manifest (referenced -> NOT stray).
    ref_data = np.arange(6, dtype=np.float32).tobytes()
    referenced = _digest_payload(root, "streams", "s1", "effnet", ref_data, ".npy")
    _write_manifest(referenced)
    # A current-format orphan payload (no manifest -> stray).
    _digest_payload(root, "streams", "s2", "effnet", np.zeros(6, np.float32).tobytes(), ".npy")
    # Legacy / bare / .vN names that MUST never be classified.
    (root / "streams" / "s3.bare.npy").write_bytes(b"x" * 8)
    (root / "streams" / "s3.v1.npy").write_bytes(b"y" * 8)
    (root / "streams" / "s4.legacy.float32.bin").write_bytes(b"z" * 8)
    # Staging: abandoned catalog build dir + a leftover staged-write .tmp.
    staged_build = root / "catalogs" / ".staging-run-x"
    staged_build.mkdir(parents=True, exist_ok=True)
    (staged_build / "catalog.duckdb").write_bytes(b"\x00" * 4)
    staging = root / "streams" / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "s1.effnet.abcdef.tmp").write_bytes(b"staged")
    # Published current + an unselected stray catalog dir.
    (root / "catalogs" / "current.json").write_text(json.dumps({"catalog_id": "pub"}), encoding="utf-8")
    (root / "catalogs" / "pub").mkdir(parents=True, exist_ok=True)
    (root / "catalogs" / "pub" / "catalog.manifest.json").write_text("{}", encoding="utf-8")
    (root / "catalogs" / "pub" / "catalog.duckdb").write_bytes(b"\x01" * 4)
    (root / "catalogs" / "unselected").mkdir(parents=True, exist_ok=True)
    (root / "catalogs" / "unselected" / "catalog.manifest.json").write_text("{}", encoding="utf-8")
    (root / "catalogs" / "unselected" / "catalog.duckdb").write_bytes(b"\x02" * 4)
    # Disposable view.
    view = root / "disposable_views" / "v"
    view.mkdir(parents=True, exist_ok=True)
    (view / "part.parquet").write_bytes(b"pv")


def test_cleanup_stray_current_format_only_dry_run_default(tmp_path):
    root = tmp_path / "root"
    _seed_mixed_artifact_tree(root)

    # dry_run is the default for stray: candidates reported, nothing removed.
    report = cleanup.cleanup_current(root, None, scope="stray")
    assert report.dry_run is True
    orphan = next(iter(root.glob("streams/s2.effnet.*.npy")))
    assert len(report.removed) == 2  # orphan payload + unselected catalog dir
    assert orphan.is_file(), "dry-run must report but not remove"
    assert (root / "catalogs" / "unselected").is_dir()

    # Legacy / bare / .vN payloads are never classified or removed.
    assert (root / "streams" / "s3.bare.npy").is_file()
    assert (root / "streams" / "s3.v1.npy").is_file()
    assert (root / "streams" / "s4.legacy.float32.bin").is_file()

    # Real removal removes only the current-format strays.
    report = cleanup.cleanup_current(root, None, scope="stray", dry_run=False)
    assert not orphan.exists()
    assert not (root / "catalogs" / "unselected").exists()
    referenced = list(root.glob("streams/s1.effnet.*.npy"))
    assert len(referenced) == 1 and referenced[0].with_suffix(".json").is_file(), (
        "manifest-referenced payload must never be a stray"
    )
    assert (root / "catalogs" / "pub").is_dir(), "the selected catalog is never a stray"
    assert (root / "streams" / "s3.bare.npy").is_file()
    assert (root / "streams" / "s3.v1.npy").is_file()


def test_cleanup_staging_and_views_current_format_only(tmp_path):
    root = tmp_path / "root"
    _seed_mixed_artifact_tree(root)

    staging = cleanup.cleanup_current(root, None, scope="staging")
    assert staging.dry_run is True
    staging = cleanup.cleanup_current(root, None, scope="staging", dry_run=False)
    assert not (root / "catalogs" / ".staging-run-x").exists()
    leftover = list((root / "streams" / ".staging").glob("*.tmp")) if (root / "streams" / ".staging").is_dir() else []
    assert leftover == [], "all staged-write .tmp leftovers must be removed"
    assert (root / "catalogs" / "pub").is_dir(), "staging cleanup must not touch a published catalog"

    views = cleanup.cleanup_current(root, None, scope="views", dry_run=False)
    assert views.removed, "disposable_views must be reported"
    assert not (root / "disposable_views").exists()


# --------------------------------------------------------------------------- #
# (d) exclusive run lock: contention exits 2; released on success AND failure  #
# --------------------------------------------------------------------------- #


def test_run_lock_contention_exits_2_and_releases_on_success(tmp_path):
    db = tmp_path / "research.duckdb"
    with run_mod._RunLock(tmp_path, db):
        # A second, concurrent exclusive acquisition must refuse with exit code 2.
        with pytest.raises(SystemExit) as exc:
            run_mod._RunLock(tmp_path, db).__enter__()
        assert exc.value.code == 2
    # Released on the success path: a fresh acquisition succeeds.
    with run_mod._RunLock(tmp_path, db):
        pass


def test_run_lock_releases_on_failure_and_lockfile_appears_disappears(tmp_path):
    db = tmp_path / "research.duckdb"
    lock_path = run_mod._run_lock_path(tmp_path, db)
    assert not lock_path.exists()
    with pytest.raises(RuntimeError), run_mod._RunLock(tmp_path, db):
        assert lock_path.exists(), "lockfile must exist during the guarded run"
        raise RuntimeError("boom")
    # The flock was released on the failure path: a fresh acquisition succeeds.
    with run_mod._RunLock(tmp_path, db):
        pass
    with run_mod._RunLock(tmp_path, db):
        pass


# --------------------------------------------------------------------------- #
# (e) reset --scope analysis byte-preserves Tier 1/2                          #
# --------------------------------------------------------------------------- #


def test_reset_analysis_removes_only_disposable_db_and_views(tmp_path):
    root = tmp_path / "root"
    (root / "corpus").mkdir(parents=True)
    (root / "corpus" / "manifest.json").write_text("{}", encoding="utf-8")
    stream = _digest_payload(root, "streams", "s1", "effnet", np.ones(8, np.float32).tobytes(), ".npy")
    _write_manifest(stream)
    commit = root / "observation_commits"
    commit.mkdir()
    (commit / "s1.effnet.abcdef.json").write_text("{}", encoding="utf-8")
    (root / "catalogs" / "pub").mkdir(parents=True, exist_ok=True)
    (root / "catalogs" / "current.json").write_text(json.dumps({"catalog_id": "pub"}), encoding="utf-8")
    db_path = tmp_path / "research.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE t (i INTEGER)")
    con.close()
    (pathlib.Path(f"{db_path}.wal")).write_bytes(b"wal")
    (root / "disposable_views" / "v").mkdir(parents=True)
    (root / "disposable_views" / "v" / "x").write_bytes(b"view")

    preserved_dirs = ("corpus", "streams", "heads", "audio_masks", "observation_commits", "catalogs")
    before = {d: _tree_digests(root / d) for d in preserved_dirs if (root / d).exists()}

    report = cleanup.reset_analysis(root, db_path, dry_run=False)
    assert any("research.duckdb" in r for r in report.removed)
    assert not db_path.exists() and not pathlib.Path(f"{db_path}.wal").exists()
    assert not (root / "disposable_views").exists()

    # Tier 1/2 payloads are byte-identical after reset.
    after = {d: _tree_digests(root / d) for d in preserved_dirs if (root / d).exists()}
    assert after == before


def test_reset_analysis_dry_run_removes_nothing(tmp_path):
    root = tmp_path / "root"
    db_path = tmp_path / "research.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE t (i INTEGER)")
    con.close()
    report = cleanup.reset_analysis(root, db_path, dry_run=True)
    assert report.removed and db_path.exists(), "dry-run reports the DB but must not remove it"


# --------------------------------------------------------------------------- #
# (g) maintenance bodies are CPU-only (no audio/model/ONNX/CUDA/session)      #
# --------------------------------------------------------------------------- #


def test_maintenance_imports_pull_no_inference_or_production_runtime():
    code = (
        "import sys; "
        "import scripts.embedding_research.cleanup; "
        "import scripts.embedding_research.verify; "
        "names=[m for m in sys.modules if m=='onnxruntime' or m=='torch' "
        "or m.startswith('nomarr') or m.startswith('torch.') "
        "or m.startswith('onnxruntime.')]; "
        "print('BAD='+','.join(sorted(names)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(pathlib.Path(__file__).parents[3]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert "BAD=" not in result.stdout or result.stdout.strip().endswith("BAD="), (
        f"maintenance bodies imported inference/production runtime: {result.stdout.strip()}"
    )


# --------------------------------------------------------------------------- #
# CLI smoke: --help lists exactly the 12 commands; every legacy alias exits 2  #
# --------------------------------------------------------------------------- #


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """Point run.py's OUTPUT_ROOT/DB_PATH at tmp and exercise main() in-process."""
    out = tmp_path / "out"
    db = tmp_path / "research.duckdb"
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", out)
    monkeypatch.setattr(run_mod, "DB_PATH", db)
    return out, db


def test_cli_help_lists_all_twelve_commands(cli, capsys):
    _out_root, _db_path = cli
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sys, "argv", ["run.py"])
    try:
        with pytest.raises(SystemExit) as exc:
            run_mod.main()
        assert exc.value.code == 2
    finally:
        monkeypatch.undo()
    text = capsys.readouterr().out
    for cmd in [
        "ingest",
        "embed",
        "infer-heads",
        "catalog",
        "catalog-report",
        "analyze",
        "head-analysis",
        "report",
        "verify",
        "reindex",
        "cleanup",
        "reset",
    ]:
        assert cmd in text, f"--help output must name the {cmd!r} command"


@pytest.mark.parametrize("alias", ["stratify", "segment", "classify", "head"])
def test_cli_legacy_alias_exits_2(cli, alias):
    _out_root, _db_path = cli
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sys, "argv", ["run.py", alias])
    try:
        with pytest.raises(SystemExit) as exc:
            run_mod.main()
        assert exc.value.code == 2
    finally:
        monkeypatch.undo()


def test_cli_unknown_command_exits_2(cli):
    _out_root, _db_path = cli
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sys, "argv", ["run.py", "frobnicate"])
    try:
        with pytest.raises(SystemExit) as exc:
            run_mod.main()
        assert exc.value.code == 2
    finally:
        monkeypatch.undo()
