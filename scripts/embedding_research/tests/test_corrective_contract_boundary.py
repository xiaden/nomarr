"""Spec-first contract tests for the corrective Gram-geometry repair boundary.

These tests encode the binding corrective contract produced by
``TASK-gram-geometry-corrective-repair-A-contract-boundary``. The corpus-identity,
comparability, observation-identity, and traceability-absence cases are intentionally
failing until later corrective plans implement the corrected contract; the preservation
cases guard Plan A's own scope and pass immediately.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PARTS_DIR = REPO_ROOT / "artifacts" / "designs" / "parts" / "threshold-independent-per-song-gram-geometry-migration"
MANIFEST_PATH = PARTS_DIR / "PRESERVATION-MANIFEST.json"
PARTS_CONTRACTS_PATH = PARTS_DIR / "CONTRACTS.md"
DD_PATH = (
    REPO_ROOT / "artifacts" / "designs" / "pending" / "DD-threshold-independent-per-song-gram-geometry-migration.md"
)
RUNTIME_CONTRACTS_PATH = PACKAGE_ROOT / "CONTRACTS.md"
RUNTIME_README_PATH = PACKAGE_ROOT / "README.md"

IDENTITY_OWNER = "scripts.embedding_research.helpers.corpus_identity"

PROTECTED_FILES = (
    "scripts/embedding_research/FINDINGS.md",
    "scripts/embedding_research/validate_fixture_report.py",
    "scripts/embedding_research/tests/test_validate_fixture_report.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _identity_module():
    try:
        return importlib.import_module(IDENTITY_OWNER)
    except ModuleNotFoundError:
        pytest.fail(
            "canonical corrective identity owner helpers/corpus_identity.py is not "
            "implemented yet (implemented by corrective Plans B/C)",
            pytrace=False,
        )


def _representation_id(**overrides):
    module = _identity_module()
    kwargs = {
        "experiment": "temporal_global",
        "scoring_semantics_version": 1,
        "geometry_semantics_version": "gram-v1",
        "numerical_profile_digest": "a" * 64,
        "observation_group_sha256": "b" * 64,
        "mask_identity": "c" * 64,
        "ordered_corpus_song_ids": ("s1", "s2", "s3"),
        "medoid_source_indices": (0, 2, 5),
        "normalized_searchable_weights": (0.5, 0.25, 0.25),
        "searchable_count": 3,
    }
    kwargs.update(overrides)
    return module.search_representation_id(**kwargs)


# ---------------------------------------------------------------------------
# Preservation (Plan A scope guard) — expected PASS
# ---------------------------------------------------------------------------


def test_preservation_manifest_asserts_no_production_targets() -> None:
    manifest = _manifest()
    assert manifest["no_production_targets"] is True
    assert manifest["scope_assertion"]
    assert set(manifest["forbidden_target_prefixes"]) == {
        "nomarr/",
        "frontend/",
        "tests/unit/",
    }
    assert set(manifest["implementation_target_roots"]) == {
        "scripts/embedding_research",
        "artifacts",
    }
    for entry in manifest["out_of_scope_modified_files"]:
        assert not entry["path"].startswith("scripts/embedding_research")
    assert not any(
        entry["path"].startswith(("nomarr/", "frontend/")) for entry in manifest["implementation_target_files"]
    )


def test_preservation_manifest_protected_hashes_match_working_tree() -> None:
    """Assert the protected concurrent hunks survive surgical Plan E deletion.

    The two validator files necessarily change because traceability-only code is removed.
    Their Plan A concurrent additions are therefore checked by exact retained snippets;
    FINDINGS remains byte-identical and is checked by its manifest SHA-256.
    """
    manifest = _manifest()
    protected = {entry["path"]: entry for entry in manifest["protected_concurrent_files"]}
    assert set(protected) == set(PROTECTED_FILES)
    assert (
        _sha256(REPO_ROOT / "scripts/embedding_research/FINDINGS.md")
        == protected["scripts/embedding_research/FINDINGS.md"]["sha256"]
    )

    validator_source = (REPO_ROOT / "scripts/embedding_research/validate_fixture_report.py").read_text(encoding="utf-8")
    assert "scientific artifact-hash helpers" in validator_source
    assert "def sha256_file(path: Path) -> str:" in validator_source
    assert "def validate_fixture_report(path: str | Path) -> None:" in validator_source

    tests_source = (REPO_ROOT / "scripts/embedding_research/tests/test_validate_fixture_report.py").read_text(
        encoding="utf-8"
    )
    assert "def test_report_has_no_retired_identity_columns" in tests_source
    assert '_PREVIEW = _j("cat", "alog", "_id")' in tests_source

    # Out-of-scope nomarr/tests files are recorded but may legitimately drift under
    # unrelated concurrent work, so only their listing and scope are asserted here.
    for entry in manifest["out_of_scope_modified_files"]:
        assert entry["sha256"]
        assert entry["path"].startswith(("nomarr/", "tests/unit/"))
        assert not entry["path"].startswith("scripts/embedding_research")


def test_corrective_contract_is_active_in_documents() -> None:
    runtime_contracts = RUNTIME_CONTRACTS_PATH.read_text(encoding="utf-8").lower()
    for phrase in (
        "corrective repair contract (binding)",
        "leave-one-out",
        "observation_group_sha256",
        "numpy",
        "segmentation-independent",
        "non-comparable",
        "structural_identity",
    ):
        assert phrase in runtime_contracts, phrase
    runtime_readme = RUNTIME_README_PATH.read_text(encoding="utf-8").lower()
    for phrase in ("leave-one-out", "numpy", "observation_group_sha256"):
        assert phrase in runtime_readme, phrase
    dd = DD_PATH.read_text(encoding="utf-8")
    assert "Corrective repair authority (binding" in dd
    assert "Traceability deletion inventory" in dd
    parts = PARTS_CONTRACTS_PATH.read_text(encoding="utf-8")
    for phrase in ("search_representation_id", "observation_group_sha256", "classify_representation"):
        assert phrase in parts, phrase


# ---------------------------------------------------------------------------
# Corpus identity hashing (implemented by Plan C) — expected FAIL until then
# ---------------------------------------------------------------------------


def test_search_representation_id_is_deterministic_lowercase_sha256() -> None:
    first = _representation_id()
    second = _representation_id()
    assert first == second
    assert first == first.lower()
    assert len(first) == 64
    int(first, 16)


def test_search_representation_id_signature_excludes_structural_inputs() -> None:
    module = _identity_module()
    parameters = set(inspect.signature(module.search_representation_id).parameters)
    forbidden = {
        "threshold_id",
        "threshold_index",
        "threshold_value",
        "structural_identity",
        "boundaries",
        "absorbed_locations",
        "geometry_id",
    }
    assert forbidden.isdisjoint(parameters)


def test_search_representation_id_is_order_sensitive_to_corpus_population() -> None:
    forward = _representation_id(ordered_corpus_song_ids=("s1", "s2", "s3"))
    reversed_population = _representation_id(ordered_corpus_song_ids=("s3", "s2", "s1"))
    assert forward != reversed_population


def test_search_representation_id_tracks_medoid_and_weight_inputs() -> None:
    base = _representation_id()
    assert base != _representation_id(medoid_source_indices=(2, 0, 5))
    assert base != _representation_id(normalized_searchable_weights=(0.5, 0.5, 0.0))
    assert base != _representation_id(searchable_count=2)
    assert base != _representation_id(mask_identity="d" * 64)
    assert base != _representation_id(observation_group_sha256="e" * 64)


def test_structural_identity_is_separate_from_search_identity() -> None:
    module = _identity_module()
    threshold_only = module.structural_identity(
        threshold_id="t0", boundaries=((0, 3), (3, 7)), absorbed_locations=((1,),)
    )
    other_threshold = module.structural_identity(
        threshold_id="t1", boundaries=((0, 3), (3, 7)), absorbed_locations=((1,),)
    )
    other_boundaries = module.structural_identity(
        threshold_id="t0", boundaries=((0, 4), (4, 7)), absorbed_locations=((1,),)
    )
    assert len({threshold_only, other_threshold, other_boundaries}) == 3
    assert all(len(value) == 64 for value in (threshold_only, other_threshold, other_boundaries))
    assert threshold_only != _representation_id()


# ---------------------------------------------------------------------------
# Comparability (implemented by Plan C) — expected FAIL until then
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "alignment_ok": False,
            "searchable_count": 3,
            "medoid_defined": True,
            "candidate_count": 2,
            "label_defined": True,
        },
        {
            "alignment_ok": True,
            "searchable_count": 0,
            "medoid_defined": True,
            "candidate_count": 2,
            "label_defined": True,
        },
        {
            "alignment_ok": True,
            "searchable_count": 3,
            "medoid_defined": False,
            "candidate_count": 2,
            "label_defined": True,
        },
        {
            "alignment_ok": True,
            "searchable_count": 3,
            "medoid_defined": True,
            "candidate_count": 0,
            "label_defined": True,
        },
    ],
)
def test_incomplete_representation_is_non_comparable(kwargs: dict) -> None:
    module = _identity_module()
    state = module.classify_representation(**kwargs)
    assert state.comparable is False
    assert state.defined is False
    assert state.eligible is False
    assert state.reasons


def test_defined_representation_without_label_is_ineligible() -> None:
    module = _identity_module()
    state = module.classify_representation(
        alignment_ok=True,
        searchable_count=3,
        medoid_defined=True,
        candidate_count=2,
        label_defined=False,
    )
    assert state.comparable is True
    assert state.defined is True
    assert state.eligible is False


# ---------------------------------------------------------------------------
# Observation identity and traceability absence (Plans D/E) — expected FAIL until then
# ---------------------------------------------------------------------------


def test_observation_identity_symbol_is_hard_cut() -> None:
    violations = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "tests" in path.relative_to(PACKAGE_ROOT).parts:
            continue
        if "observation_commit_sha256" in path.read_text(encoding="utf-8"):
            violations.append(str(path.relative_to(PACKAGE_ROOT)))
    assert violations == [], violations
    module = _identity_module()
    assert "observation_group_sha256" in inspect.signature(module.search_representation_id).parameters


def test_current_head_repair_chain_and_boundaries_are_frozen() -> None:
    parts = PARTS_CONTRACTS_PATH.read_text(encoding="utf-8")
    readme = (PARTS_DIR / "README.md").read_text(encoding="utf-8")
    runtime = RUNTIME_README_PATH.read_text(encoding="utf-8")
    chain = (
        "H-contract-and-boundary",
        "I-numpy-kernel",
        "J-corpus-retrieval",
        "K-persistence-and-report",
        "L-traceability-and-evidence",
        "M-final-current-head-verification",
    )
    for name in chain:
        assert name in parts and name in readme
    assert "3efecd9cf726c1b1a4ae4f7f9d69dd9c6e2b75d4" in parts
    assert "read_geometry_corpus_evidence" in parts
    assert "same-population" in runtime


def test_canonical_non_comparable_reason_vocabulary_is_exact() -> None:
    module = _identity_module()
    state = module.classify_representation(
        alignment_ok=False,
        searchable_count=0,
        medoid_defined=False,
        candidate_count=0,
        label_defined=False,
    )
    assert state.reasons == (
        "alignment_failed",
        "no_searchable",
        "no_medoid",
        "no_candidates",
    )
    labelled = module.classify_representation(
        alignment_ok=True,
        searchable_count=1,
        medoid_defined=True,
        candidate_count=1,
        label_defined=False,
    )
    assert labelled.reasons == ("label_missing",)


def test_no_compatibility_or_dual_write_surface_is_declared() -> None:
    runtime = RUNTIME_CONTRACTS_PATH.read_text(encoding="utf-8").lower()
    assert "no compatibility apis" in runtime
    assert "dual writes" in runtime
    assert "observation_group_sha256" in runtime


def test_traceability_replay_machinery_is_absent() -> None:
    assert not (PACKAGE_ROOT / "tests" / "test_gram_traceability.py").exists()
    assert not (PACKAGE_ROOT / "tools" / "emit_traceability.py").exists()
    validator = (PACKAGE_ROOT / "validate_fixture_report.py").read_text(encoding="utf-8")
    for retired in ("validate_traceability", "--traceability"):
        assert retired not in validator, retired
    assert "validate_report" in validator
    assert "sha256_bytes" in validator
