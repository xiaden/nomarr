"""P1-S4 spec-first: maintenance ``verify [--strict]`` + ``reindex`` over the P1-S1/S2 fixture.

Plan ``TASK-frozen-observation-semantic-runtime-corrective-pass-D-deterministic-fixture-
verification`` step P1-S4.  These tests exercise the ACTUAL maintenance entry points the CLI
uses against the real :class:`FixtureCliRunner` deterministic output tree:

* ``verify.verify_current_artifacts`` — the body ``run._cmd_verify`` invokes (and
  ``run._cmd_verify`` itself for the exit-code mapping);
* ``streams.reindex.reconcile_current_manifests`` / ``streams.reindex.reindex`` — the body
  ``run._cmd_reindex`` invokes (and ``run._cmd_reindex`` itself for the exit-code mapping).

The pristine 8-phase run (module-scoped) is the source of every fixture state; ANY
tamper/corruption/supersession mutation happens on a ``shutil.copytree`` **copy** of the
output root so the pristine tree (and the shared module ``con``) stays intact and every test
is hermetic.  Reindex/verify tests that rebuild registries write into a FRESH in-memory
DuckDB ``con`` (the intended post-deletion rebuild semantics), never the shared module con.

Covered clauses (all literal/synthetic — no empirical claim):

1. non-strict AND ``--strict`` verify PASS the intact fixture (refusals == [], issues == [])
   with the documented report; with the SentinelRegistry armed, verify makes ZERO
   audio/model/ONNX/CUDA/segmentation calls.
2. tamper (flip a byte in a committed stream payload; same-size committed uint8-mask tamper)
   is refused ONLY under strict (digest mismatch naming the artifact); non-strict behaves
   exactly as documented (never rehashes, never mutates); restore -> strict passes again.
3. deliberately INCOMPLETE artifacts are refused: a current-format payload with no sibling
   manifest (verify) and committed groups missing their committed mask payload / commit
   marker (reindex — never silently all-searchable); restore -> recovery.
4. reindex rebuilds ONLY the retained registry index/cache rows from the filesystem, byte-
   preserves every committed stream/mask/head payload + CURRENT marker + catalog, honours
   ``heads/CURRENT``, and (sentinels armed) makes ZERO audio/model/ONNX/CUDA/segmentation
   calls.
5. head supersession follows ``heads/CURRENT``: a marker-selected CURRENT suite is resolved
   over an older non-selected payload regardless of mtime (no lexical/mtime fallback), and
   ``resolve_current_head_suite`` fails CLOSED on missing/malformed/stale markers.
6. exit codes: verify/reindex success return cleanly (0); tamper/refusal exits 1; retired/
   unknown command names are ordinary unknown-command errors (exit 2).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from types import SimpleNamespace
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research import verify
from scripts.embedding_research.db._schema import StaleSchemaError, ensure_schema
from scripts.embedding_research.streams import HeadStreamStore
from scripts.embedding_research.streams.heads_current import current_marker_path, resolve_current_head_suite
from scripts.embedding_research.streams.records import HeadSuiteCurrentError
from scripts.embedding_research.streams.reindex import reconcile_current_manifests
from scripts.embedding_research.tests.fixture_cli_harness import BACKBONE, SONGS
from scripts.embedding_research.tests.fixture_runtime_harness import FixtureCliRunner, SentinelRegistry, _Patch

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

THRESHOLDS = (0.9, 1.0, 0.2)
#: One committed payload per song in each family: streams(8) + heads(8) + masks(8) + catalog(1).
EXPECTED_INTACT_VERIFIED = 8 + 8 + 8 + 1
#: Expected reindex rebuild: 8 committed stream identities + 8 marker-selected head identities.
EXPECTED_REINDEX_REBUILT = 8 + 8


def _fresh_con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    return con


def _payload(out: Path, sub: str, song: str, suffix: str) -> Path:
    """The single committed payload for *song* under ``out/<sub>`` (deterministic fixture)."""
    hits = sorted(p for p in (out / sub).glob(f"{song}.{BACKBONE}.*{suffix}") if p.is_file())
    assert len(hits) == 1, f"expected exactly one {sub} payload for {song}; got {hits}"
    return hits[0]


def _s1_stream(out: Path) -> Path:
    return _payload(out, "streams", "s1", ".npy")


def _s1_mask(out: Path) -> Path:
    return _payload(out, "audio_masks", "s1", ".npy")


def _s1_commit(out: Path) -> Path:
    return _payload(out, "observation_commits", "s1", ".json")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_map(root: Path) -> dict[str, str]:
    """Map every file under *root* (relpath -> sha256) for a byte-identity proof."""
    return {str(p.relative_to(root)): _sha(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Drive the REAL eight-phase CLI dispatch ONCE over a deterministic corpus (module scope).

    Every test mutates only ``shutil.copytree`` copies of ``out``; ``out``/``con`` stay
    pristine as the canonical fixture source.
    """
    con = _fresh_con()
    out = tmp_path_factory.mktemp("det-maintenance")
    runner = FixtureCliRunner(con, out, thresholds=THRESHOLDS)
    runner.run_all()
    return SimpleNamespace(out=out, con=con, runner=runner)


def _copy_of(out: Path, dest_root: Path) -> Path:
    """A hermetic byte-copy of the pristine output tree to mutate freely."""
    work = dest_root / "work"
    return shutil.copytree(out, work)


@pytest.fixture
def work(tmp_path) -> Path:
    """A scratch directory to hold per-test copytree fixtures."""
    return tmp_path / "scratch"


# --------------------------------------------------------------------------- #
# 1. verify (non-strict AND --strict) PASSES the intact fixture; ZERO sentinels#
# --------------------------------------------------------------------------- #
def test_verify_intact_passes_both_modes_and_makes_zero_forbidden_calls(run):
    """Non-strict AND strict verify pass a clean fixture (refusals==[], issues==[])."""
    for strict in (False, True):
        report = verify.verify_current_artifacts(run.out, strict=strict)
        assert report.verified == EXPECTED_INTACT_VERIFIED, report.verified
        assert report.refusals == [], report.refusals
        assert report.issues == [], report.issues
        assert report.recovered == [], report.recovered

    # With the forbidden sentinels armed, verify still completes AND records ZERO calls.
    reg = SentinelRegistry()
    with _Patch() as p:
        run.runner._install_forbidden_sentinels(p, reg)
        run.runner._install_segmentation_sentinel(p, reg)
        report = verify.verify_current_artifacts(run.out, strict=True)
    assert reg.counts == {}, f"verify fired a forbidden seam: {reg.counts}"
    assert report.refusals == [], report.refusals


# --------------------------------------------------------------------------- #
# 2. tamper (stream byte-flip + same-size committed-mask) is strict-only       #
# --------------------------------------------------------------------------- #
def test_verify_refuses_stream_payload_tamper_only_under_strict_and_recovers(run, work):
    """A same-size stream payload tamper is refused by strict (naming the artifact)."""
    dest = _copy_of(run.out, work)
    stream = _s1_stream(dest)
    pristine_bytes = _s1_stream(run.out).read_bytes()

    # Same-size tamper in place (digest-name + sibling manifest kept).
    data = bytearray(stream.read_bytes())
    data[-1] ^= 0xFF
    assert len(data) == stream.stat().st_size
    stream.write_bytes(bytes(data))

    # Non-strict never rehashes and never mutates -> passes, artifact unchanged.
    non_strict = verify.verify_current_artifacts(dest, strict=False)
    assert non_strict.refusals == [], non_strict.refusals
    assert non_strict.verified == EXPECTED_INTACT_VERIFIED
    assert stream.read_bytes() != pristine_bytes, "non-strict verify must never rewrite payloads"

    # Strict rehashes and refuses, NAMING the tampered artifact.
    strict = verify.verify_current_artifacts(dest, strict=True)
    assert any("does not match its name digest" in r for r in strict.refusals), strict.refusals
    assert any("streams/" in r and f"s1.{BACKBONE}." in r for r in strict.refusals), strict.refusals

    # Recovery: restore the harness-published bytes -> strict passes again.
    _s1_stream(dest).write_bytes(pristine_bytes)
    recovered = verify.verify_current_artifacts(dest, strict=True)
    assert recovered.refusals == [], recovered.refusals


def test_verify_refuses_committed_uint8_mask_tamper_only_under_strict_and_recovers(run, work):
    """A same-size committed uint8-mask tamper (digest mismatch) is refused by strict."""
    dest = _copy_of(run.out, work)
    mask = _s1_mask(dest)
    pristine_bytes = _s1_mask(run.out).read_bytes()
    assert _sha(mask.read_bytes()) == _sha(pristine_bytes)

    data = bytearray(mask.read_bytes())
    data[-1] ^= 0xFF
    assert len(data) == mask.stat().st_size
    mask.write_bytes(bytes(data))

    non_strict = verify.verify_current_artifacts(dest, strict=False)
    assert non_strict.refusals == [], non_strict.refusals

    strict = verify.verify_current_artifacts(dest, strict=True)
    assert any("does not match its name digest" in r for r in strict.refusals), strict.refusals
    assert any("audio_masks/" in r and f"s1.{BACKBONE}." in r for r in strict.refusals), strict.refusals

    # Recovery: restore the committed mask bytes -> strict passes again.
    _s1_mask(dest).write_bytes(pristine_bytes)
    recovered = verify.verify_current_artifacts(dest, strict=True)
    assert recovered.refusals == [], recovered.refusals


# --------------------------------------------------------------------------- #
# 3. incomplete artifacts are refused (verify: no sibling manifest; reindex:   #
#    committed group missing mask payload / commit marker)                      #
# --------------------------------------------------------------------------- #
def test_verify_refuses_current_payload_without_sibling_manifest_and_recovers(run, work):
    """A current-format payload whose sibling manifest is missing is refused (incomplete)."""
    dest = _copy_of(run.out, work)
    stream = _s1_stream(dest)
    manifest = stream.with_suffix(".json")
    assert manifest.is_file()
    manifest_bytes = manifest.read_bytes()
    manifest.unlink()

    report = verify.verify_current_artifacts(dest, strict=True)
    assert any("has no sibling manifest" in r for r in report.refusals), report.refusals
    assert any("streams/" in r and f"s1.{BACKBONE}." in r for r in report.refusals), report.refusals

    manifest.write_bytes(manifest_bytes)  # restore
    assert verify.verify_current_artifacts(dest, strict=True).refusals == []


def test_reindex_refuses_committed_group_with_missing_mask_payload_never_all_searchable(run, work):
    """A committed group whose committed mask payload is missing is refused, never all-searchable."""
    dest = _copy_of(run.out, work)
    mask = _s1_mask(dest)
    pristine_bytes = mask.read_bytes()
    mask.unlink()

    con = _fresh_con()
    report = reconcile_current_manifests(dest, con)
    # The s1 stream group must be refused (mask missing) and never rebuilt ready.
    assert any("s1" in i and "effnet" in i for i in report.issues), report.issues
    # No stream registry row is rebuilt for s1 — the group is NOT silently treated as
    # all-searchable (ready requires the committed aligned mask).
    rows = con.execute(
        "SELECT count(*) FROM stream_registry WHERE song_id=? AND backbone=?", ("s1", BACKBONE)
    ).fetchone()[0]
    assert rows == 0
    # Removing s1's committed mask makes its group incomplete, so BOTH its stream row and its
    # marker-selected head row are refused (resolve_current_head_suite finds no current group).
    assert report.ready == EXPECTED_REINDEX_REBUILT - 2, (report.ready, report.issues)

    # Recovery: restore the committed mask -> reindex passes again.
    mask.write_bytes(pristine_bytes)
    con2 = _fresh_con()
    recovered = reconcile_current_manifests(dest, con2)
    assert recovered.issues == (), recovered.issues
    assert recovered.ready == EXPECTED_REINDEX_REBUILT


def test_reindex_refuses_committed_group_with_missing_commit_marker(run, work):
    """A committed stream whose observation-commit marker is absent is refused as uncommitted."""
    dest = _copy_of(run.out, work)
    commit = _s1_commit(dest)
    pristine_bytes = commit.read_bytes()
    commit.unlink()

    con = _fresh_con()
    report = reconcile_current_manifests(dest, con)
    assert any("without a valid observation-commit marker" in i for i in report.issues), report.issues
    rows = con.execute(
        "SELECT count(*) FROM stream_registry WHERE song_id=? AND backbone=?", ("s1", BACKBONE)
    ).fetchone()[0]
    assert rows == 0, "a group missing its commit marker must never be rebuilt ready"

    commit.write_bytes(pristine_bytes)  # restore
    con2 = _fresh_con()
    assert reconcile_current_manifests(dest, con2).issues == ()


# --------------------------------------------------------------------------- #
# 4. reindex rebuilds ONLY registry rows from filesystem; byte-preserves;      #
#    honours heads/CURRENT; ZERO forbidden calls                               #
# --------------------------------------------------------------------------- #
def test_reindex_rebuilds_registries_from_filesystem_and_byte_preserves_committed_artifacts(run):
    """reindex touches only the registry index/cache; committed bytes are identical after."""
    before = _tree_map(run.out)

    con = _fresh_con()  # empty registry -> reindex must rebuild purely from the filesystem
    reg = SentinelRegistry()
    with _Patch() as p:
        run.runner._install_forbidden_sentinels(p, reg)
        run.runner._install_segmentation_sentinel(p, reg)
        report = reconcile_current_manifests(run.out, con)
    assert reg.counts == {}, f"reindex fired a forbidden seam: {reg.counts}"

    # Every committed stream identity + marker-selected head identity rebuilt, no refusals.
    assert report.issues == (), report.issues
    assert report.scanned == EXPECTED_REINDEX_REBUILT == report.ready == report.rows_rebuilt, report
    assert report.orphan_payloads == 0, report.orphan_payloads

    # Byte-identity of every committed stream/mask/head payload + marker + catalog is preserved.
    assert _tree_map(run.out) == before, "reindex must never rewrite committed Tier-1/Tier-2 bytes"

    # Registries are repopulated from the filesystem manifests (8 + 8 ready).
    n_stream = con.execute("SELECT count(*) FROM stream_registry WHERE status='ready'").fetchone()[0]
    n_head = con.execute("SELECT count(*) FROM head_stream_registry WHERE status='ready'").fetchone()[0]
    assert n_stream == 8 and n_head == 8, (n_stream, n_head)

    # The head registry honours heads/CURRENT: each row matches the marker-selected suite.
    for song in SONGS:
        selected = resolve_current_head_suite(run.out, song, BACKBONE)
        (artifact_ref,) = con.execute(
            "SELECT artifact_ref FROM head_stream_registry WHERE song_id=? AND backbone=?", (song, BACKBONE)
        ).fetchone()
        assert artifact_ref == selected.record.artifact_ref, song


# --------------------------------------------------------------------------- #
# 5. head supersession follows heads/CURRENT (no mtime/lexical fallback) +      #
#    resolve_current_head_suite is fail-closed                                  #
# --------------------------------------------------------------------------- #
def _dim_by_head(dim_text: str) -> dict[str, int]:
    return {part.split("=")[0]: int(part.split("=")[1]) for part in dim_text.split(";")}


def _publish_superseding_suite(out: Path, con, song: str, backbone: str) -> str:
    """Publish a second, marker-selecting head generation for (song, backbone); return its ref."""
    selection = resolve_current_head_suite(out, song, backbone)
    head_ids = selection.record.head_ids.split(",")
    dims = _dim_by_head(selection.record.dim_by_head)
    arrays = {head: np.full((selection.record.patch_count, dims[head]), 0.5, dtype=np.float32) for head in head_ids}
    store = HeadStreamStore(con, output_root=out)
    record = store.publish(
        song,
        backbone,
        arrays,
        run_id=f"{song}-supersede",
        patch_count=selection.record.patch_count,
        alignment_version=selection.record.alignment_version,
        expected_head_ids=head_ids,
        stream_ref=selection.marker.stream_ref,
        head_set_semantics_version="1",
    )
    # The marker must now select the newly published suite (generation superseded).
    doc = json.loads(current_marker_path(out, song, backbone).read_text())
    assert doc["head_payload_ref"] == record.artifact_ref
    assert doc["generation"] >= 2
    return record.artifact_ref


def test_head_supersession_reindex_resolves_marker_selected_suite_not_mtime(run, work):
    """reindex/verify resolve the CURRENT marker-selected suite over an older payload, by marker."""
    dest = _copy_of(run.out, work)
    con = _fresh_con()

    gen1 = resolve_current_head_suite(dest, "s1", BACKBONE)
    gen1_ref = gen1.record.artifact_ref
    gen2_ref = _publish_superseding_suite(dest, con, "s1", BACKBONE)
    assert gen2_ref != gen1_ref
    # Both immutable head generations coexist on disk.
    assert len(list((dest / "heads").glob("s1.*.npz"))) == 2

    # Make the OLD (non-selected) suite look newest by mtime; reindex must NOT care.
    newest = 2_000_000_000_000
    for path in (dest / gen1_ref, dest / f"{gen1_ref[:-4]}.json"):
        os.utime(path, (newest, newest))

    report = reconcile_current_manifests(dest, con)
    # 8 stream identities + 8 head identities; supersession adds NO new identity.
    assert report.issues == (), report.issues
    assert report.rows_rebuilt == EXPECTED_REINDEX_REBUILT, report.rows_rebuilt

    (artifact_ref,) = con.execute(
        "SELECT artifact_ref FROM head_stream_registry WHERE song_id='s1' AND backbone=?", (BACKBONE,)
    ).fetchone()
    # Marker-authoritative: the CURRENT-selected (gen2) suite is indexed, NOT the newer-mtime gen1.
    assert artifact_ref == gen2_ref, artifact_ref

    # And the resolver returns the marker-selected suite, ignoring the older (newer-mtime) payload.
    resolved = resolve_current_head_suite(dest, "s1", BACKBONE)
    assert resolved.record.artifact_ref == gen2_ref

    # verify still passes: both generations are valid current-format head payloads.
    report = verify.verify_current_artifacts(dest, strict=True)
    assert report.refusals == [], report.refusals
    assert report.verified == EXPECTED_INTACT_VERIFIED + 1  # +1 superseded head payload


def test_resolve_current_head_suite_fails_closed_on_missing_marker(run, work):
    dest = _copy_of(run.out, work)
    marker = current_marker_path(dest, "s1", BACKBONE)
    pristine = marker.read_bytes()
    marker.unlink()
    with pytest.raises(HeadSuiteCurrentError, match="no CURRENT head-suite marker"):
        resolve_current_head_suite(dest, "s1", BACKBONE)
    marker.write_bytes(pristine)  # restore
    assert resolve_current_head_suite(dest, "s1", BACKBONE).record.artifact_ref


def test_resolve_current_head_suite_fails_closed_on_malformed_marker(run, work):
    dest = _copy_of(run.out, work)
    marker = current_marker_path(dest, "s1", BACKBONE)
    pristine = marker.read_bytes()
    marker.write_text("{ not json", encoding="utf-8")
    with pytest.raises(HeadSuiteCurrentError, match="malformed"):
        resolve_current_head_suite(dest, "s1", BACKBONE)
    marker.write_bytes(pristine)
    assert resolve_current_head_suite(dest, "s1", BACKBONE).record.artifact_ref


def test_resolve_current_head_suite_fails_closed_on_stale_marker_bound_to_old_stream(run, work):
    """A marker bound to a non-current committed stream is refused (no mtime/lexical fallback)."""
    dest = _copy_of(run.out, work)
    marker_path = current_marker_path(dest, "s1", BACKBONE)
    pristine = marker_path.read_bytes()
    doc = json.loads(pristine)
    # Fabricate an OLDER committed-stream binding (marker no longer selects the CURRENT stream).
    fake_digest = "a" * 64
    doc["stream_ref"] = f"streams/s1.{BACKBONE}.{fake_digest}.npy"
    doc["stream_digest"] = fake_digest
    doc["alignment_token"] = f"{doc['stream_ref']}:{doc['head_payload_ref']}"
    marker_path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(HeadSuiteCurrentError, match="no longer the current committed stream"):
        resolve_current_head_suite(dest, "s1", BACKBONE)

    marker_path.write_bytes(pristine)  # restore
    assert resolve_current_head_suite(dest, "s1", BACKBONE).record.artifact_ref


# --------------------------------------------------------------------------- #
# 6. exit codes: clean 0; refusal 1; retired/unknown command 2                 #
# --------------------------------------------------------------------------- #
def test_cli_verify_exit_codes_clean_zero_tamper_one(run, work, tmp_path, monkeypatch):
    """run._cmd_verify returns cleanly (0) on an intact root and exits 1 on refusal."""
    out = _copy_of(run.out, work)
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", out)
    monkeypatch.setattr(run_mod, "DB_PATH", tmp_path / "unused.duckdb")

    # Clean root -> _cmd_verify returns (exit 0), non-strict and strict.
    run_mod._cmd_verify(SimpleNamespace(strict=False))
    run_mod._cmd_verify(SimpleNamespace(strict=True))

    # Tamper a committed stream -> strict verify exits 1 naming the refusal.
    stream = _s1_stream(out)
    pristine = _s1_stream(run.out).read_bytes()
    data = bytearray(stream.read_bytes())
    data[-1] ^= 0xFF
    stream.write_bytes(bytes(data))
    with pytest.raises(SystemExit) as exc:
        run_mod._cmd_verify(SimpleNamespace(strict=True))
    assert exc.value.code == 1

    # Restore -> clean exit again.
    stream.write_bytes(pristine)
    run_mod._cmd_verify(SimpleNamespace(strict=True))


def test_cli_reindex_exit_codes_clean_zero_refusal_one(run, work, tmp_path, monkeypatch):
    """run._cmd_reindex returns cleanly (0) on an intact root and exits 1 on a refusal."""
    out = _copy_of(run.out, work)
    db = tmp_path / "research.duckdb"
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", out)
    monkeypatch.setattr(run_mod, "DB_PATH", db)

    # Intact root -> _cmd_reindex returns cleanly (rebuilds into the file DB).
    run_mod._cmd_reindex(SimpleNamespace())

    # Corrupt a committed group (remove its commit marker) -> reindex refuses, exit 1.
    commit = _s1_commit(out)
    pristine = commit.read_bytes()
    commit.unlink()
    with pytest.raises(SystemExit) as exc:
        run_mod._cmd_reindex(SimpleNamespace())
    assert exc.value.code == 1

    commit.write_bytes(pristine)  # restore
    run_mod._cmd_reindex(SimpleNamespace())


@pytest.mark.parametrize("alias", ["stratify", "segment", "classify", "head", "frobnicate"])
def test_retired_and_unknown_command_names_are_ordinary_unknown_commands(alias):
    """Retired legacy names + unknown commands are ordinary unknown-command errors (exit 2)."""
    with pytest.raises(SystemExit) as exc:
        run_mod._resolve_command(alias)
    assert exc.value.code == 2


# --------------------------------------------------------------------------- #
# Plan D P3-S1: CLI-level exit-code refusal paths not yet asserted at the real #
# maintenance-command seam (verify --strict committed-uint8-mask tamper;       #
# reindex with a missing committed-mask payload).                              #
# --------------------------------------------------------------------------- #
def test_cli_verify_strict_committed_mask_tamper_exit_one_naming_payload(run, work, tmp_path, monkeypatch):
    """P3-S1: verify --strict exits 1 on a tampered committed uint8 mask, naming the payload.

    ``test_cli_verify_exit_codes_clean_zero_tamper_one`` pins the CLI exit-1 mapping for a
    committed STREAM tamper; this extends the same real ``run._cmd_verify`` seam to the
    committed uint8-MASK tamper the strict structural check also refuses (uint8[P] by
    contract) — the exact "verify --strict exit 1 naming payload digest-mismatch" path.
    """
    out = _copy_of(run.out, work)
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", out)
    monkeypatch.setattr(run_mod, "DB_PATH", tmp_path / "unused.duckdb")

    # Clean root -> _cmd_verify returns (exit 0).
    run_mod._cmd_verify(SimpleNamespace(strict=True))

    # Tamper the committed uint8 mask (same size, digest-name + sibling manifest kept).
    mask = _s1_mask(out)
    pristine = _s1_mask(run.out).read_bytes()
    data = bytearray(mask.read_bytes())
    data[-1] ^= 0xFF
    assert len(data) == mask.stat().st_size
    mask.write_bytes(bytes(data))

    # The strict refusal NAMES the payload (digest mismatch), and the CLI maps it to exit 1.
    strict = verify.verify_current_artifacts(out, strict=True)
    assert any("does not match its name digest" in r for r in strict.refusals), strict.refusals
    assert any("audio_masks/" in r and f"s1.{BACKBONE}." in r for r in strict.refusals), strict.refusals
    with pytest.raises(SystemExit) as exc:
        run_mod._cmd_verify(SimpleNamespace(strict=True))
    assert exc.value.code == 1

    # Restore -> clean exit again.
    mask.write_bytes(pristine)
    run_mod._cmd_verify(SimpleNamespace(strict=True))


def test_cli_reindex_missing_committed_mask_payload_exit_one(run, work, tmp_path, monkeypatch):
    """P3-S1: reindex exits 1 on a committed group whose committed mask payload is missing.

    ``test_cli_reindex_exit_codes_clean_zero_refusal_one`` pins the CLI exit-1 mapping for a
    removed observation-commit marker; this extends the same real ``run._cmd_reindex`` seam to
    the missing committed-MASK-payload refusal (the group is never silently treated as
    all-searchable — reindex refuses and exits 1).
    """
    out = _copy_of(run.out, work)
    db = tmp_path / "research.duckdb"
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", out)
    monkeypatch.setattr(run_mod, "DB_PATH", db)

    # Intact root -> _cmd_reindex returns cleanly (rebuilds into the file DB).
    run_mod._cmd_reindex(SimpleNamespace())

    # Remove s1's committed uint8 mask payload (stream + sibling manifest + commit marker kept)
    # -> reindex refuses (incomplete committed group), exit 1.
    mask = _s1_mask(out)
    pristine = mask.read_bytes()
    mask.unlink()
    with pytest.raises(SystemExit) as exc:
        run_mod._cmd_reindex(SimpleNamespace())
    assert exc.value.code == 1

    mask.write_bytes(pristine)  # restore
    run_mod._cmd_reindex(SimpleNamespace())


def test_reindex_refuses_stale_schema_no_legacy_fallback(run, work, tmp_path, monkeypatch):
    """P3-S3: reindex on a stale pre-cut research DB REFUSES via StaleSchemaError — never a
    legacy/old-schema fallback.

    The hard cut makes ``analyze_metrics`` ONE current run-scoped schema.  A research DB whose
    ``analyze_metrics`` predates the ``run_id`` column must make the reindex command refuse
    (:class:`StaleSchemaError` from the ``ensure_schema`` guard) rather than silently downgrade,
    relabel, or re-seed stale rows into a current schema.  The refusal leaves the stale table
    byte-untouched.
    """
    out = _copy_of(run.out, work)
    stale_db = tmp_path / "stale.duckdb"
    # Build a pre-cut research DB: analyze_metrics WITHOUT the current run_id column.
    with duckdb.connect(str(stale_db)) as c:
        c.execute("CREATE TABLE analyze_metrics (strategy_key VARCHAR, metric VARCHAR, value DOUBLE)")
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", out)
    monkeypatch.setattr(run_mod, "DB_PATH", stale_db)

    # The reindex command refuses (StaleSchemaError propagates from the ensure_schema guard) —
    # it never proceeds to scan manifests or fall back to a legacy schema.
    with pytest.raises(StaleSchemaError):
        run_mod._cmd_reindex(SimpleNamespace())

    # No legacy/old-schema fallback was consulted: the stale table is left untouched (still
    # lacks run_id, zero rows) — nothing was relabeled or migrated into a current schema.
    with duckdb.connect(str(stale_db)) as c:
        cols = [r[0] for r in c.execute("DESCRIBE analyze_metrics").fetchall()]
        assert "run_id" not in cols, "the stale analyze_metrics table must not gain a run_id column"
        assert c.execute("SELECT count(*) FROM analyze_metrics").fetchone()[0] == 0
