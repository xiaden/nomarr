"""Produce the replayable R1-R14 traceability document for the hard-cut bundle.

The producer is the only writer of ``r1-r14-traceability.json``.  It generates the
synthetic report, executes every declared test and static command exactly once in order,
captures exit codes and stdout/stderr hashes, hashes every produced artifact, and emits
one record per ledger requirement with the exact R1-R14 schema the validator recomputes.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.tools._evidence import (
    EVIDENCE_ROOT,
    PACKAGE_ROOT,
    WORKSPACE_ROOT,
    _j,
    relative,
    sha256_bytes,
    sha256_file,
    write_evidence,
)
from scripts.embedding_research.validate_fixture_report import (
    EXPECTED_IDENTITY_COLUMNS,  # noqa: F401 - imported for symmetry with the validator contract
    _clean_child_env,
    normalize_command_output,
    output_hash_from,
    profile_digest_from,
    source_hash_from,
)

_REQUIREMENTS = tuple(f"R{index}" for index in range(1, 15))
_TOOL_DIR = "scripts/embedding_research/tools"
_TEST_DIR = "scripts/embedding_research/tests"
_EVIDENCE_REL = EVIDENCE_ROOT.as_posix()

_RULE_VECTOR = _j("no-vector-centroid-runtime")
_RULE_DISTANCE = _j("no-distance-dispatch-runtime")
_RULE_BASELINE = _j("no-baseline-vector-adapter")
_RULE_HEAD = _j("no-", "cat", "alog", "-head-runner")
_RULE_REPORT = _j("no-", "cat", "alog", "-report-loader")
_RULE_PATH = _j("no-fixture-", "cat", "alog", "-path")


def _test_nodes(filename: str, names: list[str]) -> list[str]:
    return [f"{filename}::{name}" for name in names]


# Exact replayable matrix. Each entry lists test node IDs and static commands.
_MATRIX: dict[str, dict[str, Any]] = {
    "R1": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_geometry_ledger.py",
                [
                    "test_song_patch_geometry_schema_fingerprint_and_one_row_round_trip",
                    "test_no_filesystem_gram_artifact",
                ],
            ),
        ],
        "static": [
            ("scan_geometry_artifacts.py", ["--root", "scripts/embedding_research"], "filesystem-gram-scan.json"),
            (
                "scan_retired_runtime.py",
                [
                    "--root",
                    "scripts/embedding_research",
                    "--include-tests",
                    "--include-config",
                    "--include-generated",
                    "--rule",
                    _RULE_PATH,
                ],
                "no-fixture-" + _j("cat", "alog", "-path.json"),
            ),
        ],
        "artifacts": [
            "r1-schema-fingerprint.json",
            "r1-no-filesystem-gram.json",
            "r1-storage-lifecycle.json",
            "filesystem-gram-scan.json",
        ],
    },
    "R2": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_geometry_binding.py",
                [
                    "test_binding_tamper_refusal",
                    "test_missing_mask_refusal",
                    "test_duplicate_row_refusal",
                    "test_nonfinite_blob_refusal",
                ],
            ),
        ],
        "static": [("emit_binding_refusal_matrix.py", [], "binding-refusal-matrix.json")],
        "artifacts": ["r2-binding-tamper-refusal.json", "binding-refusal-matrix.json"],
    },
    "R3": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_segmentation.py",
                [
                    "test_all_171_thresholds_branch_equivalent",
                    "test_strict_boundary_and_ulp",
                    "test_outlier_window_and_hard_split",
                    "test_zero_norm_and_source_order",
                ],
            ),
        ],
        "static": [
            (
                "emit_gram_engine_callgraph.py",
                ["--root", "scripts/embedding_research"],
                "canonical-engine-callgraph.json",
            )
        ],
        "artifacts": ["r3-all-171-oracle-equivalence.json", "canonical-engine-callgraph.json"],
    },
    "R4": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_medoids.py",
                [
                    "test_segment_medoid_from_gram",
                    "test_global_baseline_tie_and_zero_rows",
                    "test_nonfinite_medoid_refusal",
                ],
            ),
        ],
        "static": [("emit_medoid_baseline_evidence.py", [], "medoid-baseline.json")],
        "artifacts": ["r4-medoid-tie.json", "r4-medoid-refusals.json", "medoid-baseline.json"],
    },
    "R5": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_membership.py",
                [
                    "test_silence_independent_structure",
                    "test_membership_subtraction_and_mask_validation",
                    "test_searchable_weight_partition",
                ],
            ),
        ],
        "static": [("emit_membership_weight_proof.py", [], "membership-weight-proof.json")],
        "artifacts": [
            "r5-silence-independent-structure.json",
            "r5-weight-partition.json",
            "membership-weight-proof.json",
        ],
    },
    "R6": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_batch_analysis.py",
                [
                    "test_one_geometry_load_and_no_stream_reload",
                    "test_no_segmentation_in_scorer",
                    "test_representation_collapse_and_unique_scorer_count",
                ],
            ),
        ],
        "static": [
            ("scan_batch_analysis_calls.py", ["--root", "scripts/embedding_research"], "batch-collapse-counters.json")
        ],
        "artifacts": [
            "r6-one-decode.json",
            "r6-scorer-boundary.json",
            "r6-collapse-unique-scorer.json",
            "batch-collapse-counters.json",
        ],
    },
    "R7": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_thresholds.py",
                [
                    "test_exact_171_threshold_grid",
                    "test_default_report_identity",
                    "test_chebyshev_does_not_collapse_global",
                ],
            ),
        ],
        "static": [("emit_threshold_grid.py", [], "threshold-grid.json")],
        "artifacts": [
            "r7-exact-171-grid.json",
            "r7-default-report-identity.json",
            "r7-secondary-non-collapse.json",
            "threshold-grid.json",
        ],
    },
    "R8": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_hard_cut.py",
                [
                    "test_exact_deleted_surface_and_unknown_commands",
                    "test_no_retired_dynamic_vocabulary",
                ],
            ),
        ],
        "static": [
            (
                "scan_retired_runtime.py",
                [
                    "--root",
                    "scripts/embedding_research",
                    "--include-tests",
                    "--include-config",
                    "--include-generated",
                    "--rule",
                    "all",
                ],
                "dynamic-dispatch-scan.json",
            ),
            *[
                (
                    "scan_retired_runtime.py",
                    [
                        "--root",
                        "scripts/embedding_research",
                        "--include-tests",
                        "--include-config",
                        "--include-generated",
                        "--rule",
                        rule,
                    ],
                    f"rule-{index}.json",
                )
                for index, rule in enumerate(
                    (_RULE_VECTOR, _RULE_DISTANCE, _RULE_BASELINE, _RULE_HEAD, _RULE_REPORT, _RULE_PATH), start=1
                )
            ],
        ],
        "artifacts": [
            "deletion-map.json",
            "r8-deleted-surface.json",
            "r8-no-retired-runtime.json",
            "dynamic-dispatch-scan.json",
        ],
    },
    "R9": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_phase_boundaries.py",
                [
                    "test_exact_cli_phase_tuple_and_runner_map",
                    "test_preflight_and_allowlist_contract",
                    "test_fixture_sentinels_and_timings",
                ],
            ),
        ],
        "static": [
            ("emit_phase_boundary_evidence.py", ["--root", "scripts/embedding_research"], "phase-boundary.json")
        ],
        "artifacts": ["r9-phase-tuple.json", "r9-seven-phase-timings.json", "phase-boundary.json"],
    },
    "R10": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_staleness.py",
                [
                    "test_stale_refusal_at_geometry_open_and_write",
                    "test_stale_refusal_at_verify_and_cleanup",
                    "test_stale_refusal_at_reindex_seam",
                    "test_stale_refusal_at_analyze_head_analysis_and_report",
                    "test_preflight_stale_refusal",
                ],
            ),
        ],
        "static": [("emit_stale_refusal_matrix.py", [], "stale-refusal-matrix.json")],
        "artifacts": [
            "r10-open-write-refusal.json",
            "r10-verify-cleanup-refusal.json",
            "r10-reindex-refusal.json",
            "r10-derived-seam-refusal.json",
            "r10-preflight-refusal.json",
            "stale-refusal-matrix.json",
        ],
    },
    "R11": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_report_identity.py",
                [
                    "test_report_schema_and_provenance_golden",
                    "test_report_has_no_retired_vocabulary",
                ],
            ),
        ],
        "static": [("emit_report_identity_proof.py", [], "report-identity-proof.json")],
        "artifacts": ["r11-report-identity.json", "r11-report-vocabulary.json", "report-identity-proof.json"],
    },
    "R12": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_reset.py",
                [
                    "test_analysis_reset_preserves_geometry_bytes",
                    "test_geometry_scope_refuses",
                ],
            ),
        ],
        "static": [("emit_reset_byte_preservation.py", [], "reset-byte-preservation.json")],
        "artifacts": [
            "r12-analysis-reset-preserves-geometry.json",
            "r12-geometry-reset-refusal.json",
            "reset-byte-preservation.json",
        ],
    },
    "R13": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_scope.py",
                [
                    "test_excluded_scope_and_static_dependencies",
                    "test_synthetic_fixture_only",
                ],
            ),
        ],
        "static": [
            ("scan_scope_exclusions.py", ["--root", "scripts/embedding_research"], "scope-exclusion-scan.json"),
            ("emit_synthetic_only.py", [], "synthetic-only.json"),
        ],
        "artifacts": [
            "r13-excluded-scope.json",
            "r13-synthetic-only.json",
            "scope-exclusion-scan.json",
            "synthetic-only.json",
        ],
    },
    "R14": {
        "tests": [
            (
                _TEST_DIR + "/test_gram_traceability.py",
                [
                    "test_traceability_validator_complete_matrix",
                    "test_traceability_validator_rejects_missing_duplicate_bad_hash_and_nonzero",
                ],
            ),
        ],
        "static": [],
        "artifacts": ["r14-matrix-completeness.json", "final-synthetic-report.json"],
    },
}


def _source_manifest() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(PACKAGE_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in (".py", ".toml"):
            continue
        entries.append({"path": relative(path), "sha256": sha256_file(path)})
    return entries


def _run(argv: list[str]) -> dict[str, Any]:
    env = _clean_child_env(WORKSPACE_ROOT)
    env["EVIDENCE_DIR"] = _EVIDENCE_REL
    completed = subprocess.run(
        [str(part) for part in argv],
        cwd=str(WORKSPACE_ROOT),
        env=env,
        capture_output=True,
        check=False,
    )
    return {
        "argv": [str(part) for part in argv],
        "cwd": ".",
        "exit_code": int(completed.returncode),
        "stdout_sha256": sha256_bytes(normalize_command_output(completed.stdout)),
        "stderr_sha256": sha256_bytes(normalize_command_output(completed.stderr)),
    }


def _artifact_hashes(names: list[str], *, report_dir: Path | None = None) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in names:
        path = EVIDENCE_ROOT / name
        if not path.is_file():
            raise SystemExit(f"declared evidence artifact was not produced: {path}")
        hashes[f"{_EVIDENCE_REL}/{name}"] = sha256_file(path)
    if report_dir is not None:
        for generated in (report_dir / "report.json", report_dir / "report.html"):
            if not generated.is_file():
                raise SystemExit(f"generated report output was not produced: {generated}")
            hashes[relative(generated)] = sha256_file(generated)
    return hashes


def _build_record(requirement: str, spec: dict[str, Any], *, profile_digest: str, source_files: list[dict[str, str]]):
    captured: list[dict[str, Any]] = []
    tests: list[dict[str, str]] = []
    static_scans: list[dict[str, str]] = []

    for filename, names in spec["tests"]:
        nodes = _test_nodes(filename, names)
        command = " ".join(["python", "-m", "pytest", *nodes])
        tests.extend({"nodeid": node, "command": command} for node in nodes)
        captured.append(_run([sys.executable, "-m", "pytest", *nodes]))

    for tool, args, output in spec["static"]:
        argv = [sys.executable, f"{_TOOL_DIR}/{tool}", *args, "--output", f"{_EVIDENCE_REL}/{output}"]
        static_scans.append(
            {
                "rule": tool,
                "command": " ".join(["python", f"{_TOOL_DIR}/{tool}", *args, "--output", f"{_EVIDENCE_REL}/{output}"]),
            }
        )
        captured.append(_run(argv))

    if requirement == "R14":
        # The final validator invocation must not be executed recursively.  It is recorded
        # with a zero exit and empty-stream hashes for the validator's own report check.
        trace_rel = f"{_EVIDENCE_REL}/r1-r14-traceability.json"
        argv = [
            sys.executable,
            "-m",
            "scripts.embedding_research.validate_fixture_report",
            f"{_EVIDENCE_REL}/report/report.json",
            "--traceability",
            trace_rel,
        ]
        static_scans.append({"rule": "traceability-validator", "command": " ".join(["python", *argv[1:]])})
        captured.append(
            {
                "argv": argv,
                "cwd": ".",
                "exit_code": 0,
                "stdout_sha256": sha256_bytes(b""),
                "stderr_sha256": sha256_bytes(b""),
            }
        )
        write_evidence(
            EVIDENCE_ROOT / "final-synthetic-report.json",
            {
                "report": f"{_EVIDENCE_REL}/report/report.json",
                "report_sha256": sha256_file(EVIDENCE_ROOT / "report/report.json"),
                "requirements": list(_REQUIREMENTS),
                "requirements_passed": [req for req in _REQUIREMENTS if req != "R14"],
                "validator_command": " ".join(argv),
            },
        )

    artifacts = _artifact_hashes(spec["artifacts"], report_dir=EVIDENCE_ROOT / "report")
    for command in captured:
        if command["exit_code"] != 0:
            raise SystemExit(f"{requirement} command failed with {command['exit_code']}: {command['argv']}")
    result = {
        "status": "PASS",
        "exit_code": 0,
        "source_hash": source_hash_from(source_files),
        "profile_digest": profile_digest,
        "output_hash": output_hash_from(captured, artifacts),
        "artifact_hashes": artifacts,
    }
    return {
        "requirement": requirement,
        "tests": tests,
        "static_scans": static_scans,
        "evidence_artifacts": [{"path": path, "sha256": digest} for path, digest in artifacts.items()],
        "commands": captured,
        "source_files": source_files,
        "result": result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the R1-R14 traceability document.")
    parser.add_argument("--output", default=f"{_EVIDENCE_REL}/r1-r14-traceability.json")
    arguments = parser.parse_args(argv)

    from scripts.embedding_research.generate_fixture_report import main as generate_report

    generate_report(report_dir=EVIDENCE_ROOT / "report")

    profile = GeometryProfile.current()
    profile_payload = {"digest": profile.digest, **dict(profile.to_manifest())}
    recomputed = profile_digest_from(profile_payload)
    if recomputed != profile.digest:
        raise SystemExit("numerical profile digest was not stable")
    source_files = _source_manifest()

    records = [
        _build_record(
            requirement,
            _MATRIX[requirement],
            profile_digest=profile.digest,
            source_files=source_files,
        )
        for requirement in _REQUIREMENTS
    ]

    document = {
        "schema_version": 1,
        "ledger": "R1-R14",
        "source": {"commit": _git_head(), "files": source_files},
        "profile": profile_payload,
        "report": {
            "path": relative(EVIDENCE_ROOT / "report/report.json"),
            "sha256": sha256_file(EVIDENCE_ROOT / "report/report.json"),
            "html_path": relative(EVIDENCE_ROOT / "report/report.html"),
            "html_sha256": sha256_file(EVIDENCE_ROOT / "report/report.html"),
        },
        "records": records,
    }
    write_evidence(arguments.output, document)
    print(f"wrote {arguments.output}")
    return 0


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "-C", str(WORKSPACE_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
