"""R14 — traceability matrix completeness and fail-closed validator coverage.

Every named DD R1-R14 matrix node must exist as a deterministic synthetic test with a
declared evidence path.  The replay validator (Plan T) now ships with a ``--traceability``
entry point; this test asserts the full declared matrix and emits the R14 completeness
artifact, while :func:`test_traceability_validator_rejects_missing_duplicate_bad_hash_and_nonzero`
exercises the validator's fail-closed refusals.
"""

from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path

from scripts.embedding_research.tests._gram_evidence import EVIDENCE_ROOT, emit_evidence

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_TEST_DIR = Path(__file__).resolve().parent
_DD = Path("artifacts/designs/pending/DD-threshold-independent-per-song-gram-geometry-migration.md")

_MATRIX: dict[str, tuple[str, ...]] = {
    "R1": (
        "test_gram_geometry_ledger.py::test_song_patch_geometry_schema_fingerprint_and_one_row_round_trip",
        "test_gram_geometry_ledger.py::test_no_filesystem_gram_artifact",
    ),
    "R2": (
        "test_gram_geometry_binding.py::test_binding_tamper_refusal",
        "test_gram_geometry_binding.py::test_missing_mask_refusal",
        "test_gram_geometry_binding.py::test_duplicate_row_refusal",
        "test_gram_geometry_binding.py::test_nonfinite_blob_refusal",
    ),
    "R3": (
        "test_gram_segmentation.py::test_all_171_thresholds_branch_equivalent",
        "test_gram_segmentation.py::test_strict_boundary_and_ulp",
        "test_gram_segmentation.py::test_outlier_window_and_hard_split",
        "test_gram_segmentation.py::test_zero_norm_and_source_order",
    ),
    "R4": (
        "test_gram_medoids.py::test_segment_medoid_from_gram",
        "test_gram_medoids.py::test_global_baseline_tie_and_zero_rows",
        "test_gram_medoids.py::test_nonfinite_medoid_refusal",
    ),
    "R5": (
        "test_gram_membership.py::test_silence_independent_structure",
        "test_gram_membership.py::test_membership_subtraction_and_mask_validation",
        "test_gram_membership.py::test_searchable_weight_partition",
    ),
    "R6": (
        "test_gram_batch_analysis.py::test_one_geometry_load_and_no_stream_reload",
        "test_gram_batch_analysis.py::test_no_segmentation_in_scorer",
        "test_gram_batch_analysis.py::test_representation_collapse_and_unique_scorer_count",
    ),
    "R7": (
        "test_gram_thresholds.py::test_exact_171_threshold_grid",
        "test_gram_thresholds.py::test_default_report_identity",
        "test_gram_thresholds.py::test_chebyshev_does_not_collapse_global",
    ),
    "R8": (
        "test_gram_hard_cut.py::test_exact_deleted_surface_and_unknown_commands",
        "test_gram_hard_cut.py::test_no_retired_dynamic_vocabulary",
    ),
    "R9": (
        "test_gram_phase_boundaries.py::test_exact_cli_phase_tuple_and_runner_map",
        "test_gram_phase_boundaries.py::test_preflight_and_allowlist_contract",
        "test_gram_phase_boundaries.py::test_fixture_sentinels_and_timings",
        "test_derived_phase_negative_boundaries.py::test_report_phase_dispatch_completes_with_zero_forbidden_calls",
        "test_derived_phase_negative_boundaries.py::test_geometry_phase_dispatch_is_cpu_only_on_empty_store",
        "test_phase4_dispatch_boundaries.py::test_derived_runner_imports_only_cpu_roots",
        "test_phase4_dispatch_boundaries.py::test_derived_runner_never_references_forbidden_tokens",
    ),
    "R10": (
        "test_gram_staleness.py::test_stale_refusal_at_geometry_open_and_write",
        "test_gram_staleness.py::test_stale_refusal_at_verify_and_cleanup",
        "test_gram_staleness.py::test_stale_refusal_at_reindex_seam",
        "test_gram_staleness.py::test_stale_refusal_at_analyze_head_analysis_and_report",
        "test_gram_staleness.py::test_preflight_stale_refusal",
        "test_maintenance_proofs.py::test_geometry_preflight_after_supersession_refuses",
        "test_maintenance_proofs.py::test_analyze_refuses_supersession_after_computation",
    ),
    "R11": (
        "test_gram_report_identity.py::test_report_schema_and_provenance_golden",
        "test_gram_report_identity.py::test_report_has_no_retired_vocabulary",
    ),
    "R12": (
        "test_gram_reset.py::test_analysis_reset_preserves_geometry_bytes",
        "test_gram_reset.py::test_geometry_scope_refuses",
    ),
    "R13": (
        "test_gram_scope.py::test_excluded_scope_and_static_dependencies",
        "test_gram_scope.py::test_synthetic_fixture_only",
    ),
    "R14": (
        "test_gram_traceability.py::test_traceability_validator_complete_matrix",
        "test_gram_traceability.py::test_traceability_validator_rejects_missing_duplicate_bad_hash_and_nonzero",
        "test_gram_traceability.py::test_committed_traceability_artifact_validates_with_informational_commit",
    ),
}

_EVIDENCE_BY_REQ: dict[str, tuple[str, ...]] = {
    "R1": ("r1-schema-fingerprint.json", "r1-no-filesystem-gram.json", "r1-storage-lifecycle.json"),
    "R2": ("r2-binding-tamper-refusal.json",),
    "R3": ("r3-all-171-oracle-equivalence.json",),
    "R4": ("r4-medoid-tie.json", "r4-medoid-refusals.json"),
    "R5": ("r5-silence-independent-structure.json", "r5-weight-partition.json"),
    "R6": ("r6-one-decode.json", "r6-scorer-boundary.json", "r6-collapse-unique-scorer.json"),
    "R7": ("r7-exact-171-grid.json", "r7-default-report-identity.json", "r7-secondary-non-collapse.json"),
    "R8": ("r8-deleted-surface.json", "r8-no-retired-runtime.json"),
    "R9": ("r9-phase-tuple.json", "r9-seven-phase-timings.json"),
    "R10": (
        "r10-open-write-refusal.json",
        "r10-verify-cleanup-refusal.json",
        "r10-reindex-refusal.json",
        "r10-derived-seam-refusal.json",
        "r10-preflight-refusal.json",
    ),
    "R11": ("r11-report-identity.json", "r11-report-vocabulary.json"),
    "R12": ("r12-analysis-reset-preserves-geometry.json", "r12-geometry-reset-refusal.json"),
    "R13": ("r13-excluded-scope.json", "r13-synthetic-only.json"),
}
#: R14 is the traceability record itself; this test emits its completeness artifact last,
#: so it is not part of the pre-existing evidence check.


def _declared_functions() -> dict[str, set[str]]:
    functions: dict[str, set[str]] = {}
    for path in sorted(_TEST_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions[path.name] = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        }
    return functions


def test_traceability_validator_complete_matrix() -> None:
    assert _DD.is_file(), f"approved DD missing: {_DD}"
    dd_text = _DD.read_text(encoding="utf-8")
    functions = _declared_functions()
    missing: list[str] = []
    for requirement, nodes in _MATRIX.items():
        assert nodes, f"{requirement} has no declared matrix node"
        for node in nodes:
            file_name, _, function = node.partition("::")
            if function not in functions.get(file_name, set()):
                missing.append(node)
            assert function in dd_text, f"{function} is not declared in the approved DD"
    assert missing == [], f"matrix nodes missing from the tree: {missing}"
    assert len(_MATRIX) == 14, "the matrix must declare exactly R1..R14"

    absent = [
        f"{requirement}:{name}"
        for requirement, names in _EVIDENCE_BY_REQ.items()
        for name in names
        if not (EVIDENCE_ROOT / name).is_file()
    ]
    assert absent == [], f"declared evidence artifacts absent: {absent}"
    emit_evidence(
        "r14-matrix-completeness.json",
        {
            "requirement_count": len(_MATRIX),
            "record_count": sum(len(nodes) for nodes in _MATRIX.values()),
            "missing": missing,
            "evidence_absent": absent,
        },
    )


def test_committed_traceability_artifact_validates_with_informational_commit() -> None:
    """Guard the committed R1-R14 bundle: zero problems, commit treated as informational.

    The delivered tree may carry uncommitted work, so the frozen-base commit is provenance
    only (``check_commit="informational"``); every per-file SHA-256, profile digest, report
    hash, and replayed command output hash is still checked strictly.  This makes
    committed-evidence drift fail CI instead of recurring silently between regenerations.
    """
    from scripts.embedding_research.validate_fixture_report import validate_traceability

    committed = EVIDENCE_ROOT / "r1-r14-traceability.json"
    assert committed.is_file(), f"committed traceability artifact missing: {committed}"
    problems = validate_traceability(committed, check_commit="informational", check_report=True)
    assert problems == [], "committed traceability drift detected:\n  - " + "\n  - ".join(problems)


def test_traceability_validator_rejects_missing_duplicate_bad_hash_and_nonzero() -> None:
    validator = _PACKAGE_ROOT / "validate_fixture_report.py"
    text = validator.read_text(encoding="utf-8")
    assert "--traceability" in text, "validator must expose the --traceability entrypoint"
    assert "R1" in text and "R14" in text

    from scripts.embedding_research.validate_fixture_report import validate_traceability

    with tempfile.TemporaryDirectory() as directory:
        bad = Path(directory) / "bad.json"
        bad.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "ledger": "R1-R14",
                    "source": {"commit": "c", "files": []},
                    "profile": {"digest": "not-a-digest"},
                    "report": {"path": "missing.json", "sha256": "nope"},
                    "records": [
                        {"requirement": "R1"},
                        {"requirement": "R1"},
                        {"requirement": "R99"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        problems = validate_traceability(bad, check_report=False, check_commit=False, replay=False)
    assert problems, "malformed traceability document must be rejected"
    assert any("missing required record" in problem for problem in problems)
    assert any("duplicates" in problem for problem in problems)
    assert any("unknown requirement" in problem for problem in problems)

    with tempfile.TemporaryDirectory() as directory:
        bad_mode = Path(directory) / "bad-mode.json"
        bad_mode.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "ledger": "R1-R14",
                    "source": {"commit": "c", "files": []},
                    "profile": {"digest": "not-a-digest"},
                    "report": {"path": "missing.json", "sha256": "nope"},
                    "records": [{"requirement": f"R{index}"} for index in range(1, 15)],
                }
            ),
            encoding="utf-8",
        )
        mode_problems = validate_traceability(bad_mode, check_report=False, check_commit="weaken", replay=False)
    assert any("commit-check mode is invalid" in problem for problem in mode_problems)
