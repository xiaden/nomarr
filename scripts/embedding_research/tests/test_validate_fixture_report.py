"""R1-R14 traceability validator tests (research-only, synthetic).

These tests exercise :mod:`scripts.embedding_research.validate_fixture_report` against a
minimal, fully replayable R1-R14 document built in a temporary workspace, plus every
fail-closed rejection the design demands: missing/duplicate/unknown records, nonzero
commands, missing artifacts, source/profile/output hash mismatches, malformed commands,
path escapes, retired vocabulary, and recursive self-invocation.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.tools._evidence import _j
from scripts.embedding_research.validate_fixture_report import (
    REQUIREMENTS,
    normalize_command_output,
    output_hash_from,
    profile_digest_from,
    sha256_bytes,
    sha256_file,
    source_hash_from,
    validate_report,
    validate_traceability,
)
from scripts.embedding_research.validate_fixture_report import (
    main as validate_main,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PREVIEW = _j("cat", "alog", "_id")


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("trace-workspace")
    report_dir = root / "report"
    from scripts.embedding_research.generate_fixture_report import main as generate_report

    report_path = generate_report(report_dir)
    evidence_dir = root / "evidence"
    evidence_dir.mkdir()
    (root / "source_a.py").write_text("SOURCE_A = 1\n", encoding="utf-8")
    (evidence_dir / "artifact.json").write_text('{"artifact": true}', encoding="utf-8")
    return {
        "root": root,
        "report": Path(report_path),
        "evidence": evidence_dir,
    }


def _argv() -> list[str]:
    return [sys.executable, "-c", "print('ok')"]


def _command() -> dict:
    completed = subprocess.run(_argv(), capture_output=True, check=False)
    assert completed.returncode == 0
    return {
        "argv": _argv(),
        "cwd": ".",
        "exit_code": 0,
        "stdout_sha256": sha256_bytes(normalize_command_output(completed.stdout)),
        "stderr_sha256": sha256_bytes(normalize_command_output(completed.stderr)),
    }


def _document(workspace: dict[str, Path]) -> dict:
    root = workspace["root"]
    evidence_dir = workspace["evidence"]
    report_path = workspace["report"]
    profile = GeometryProfile.current()
    profile_payload = {"digest": profile.digest, **dict(profile.to_manifest())}
    source_files = [
        {"path": "source_a.py", "sha256": sha256_file(root / "source_a.py")},
        {"path": "evidence/artifact.json", "sha256": sha256_file(evidence_dir / "artifact.json")},
    ]
    artifact_path = "evidence/artifact.json"
    artifact_hashes = {artifact_path: sha256_file(evidence_dir / "artifact.json")}
    # DD §536: the generated report outputs are part of every record's artifact hashes.
    report_out = workspace["report"]
    report_html = report_out.with_name("report.html")
    for generated in (report_out, report_html):
        artifact_hashes[generated.relative_to(root).as_posix()] = sha256_file(generated)
    command = _command()
    records = []
    for requirement in REQUIREMENTS:
        record = {
            "requirement": requirement,
            "tests": [{"nodeid": f"{requirement.lower()}-test", "command": "python -m pytest"}],
            "static_scans": [{"rule": "synthetic-static-scan", "command": "python -m synthetic"}],
            "evidence_artifacts": [{"path": artifact_path, "sha256": artifact_hashes[artifact_path]}],
            "source_files": source_files,
            "commands": [dict(command)],
        }
        record["result"] = {
            "status": "PASS",
            "exit_code": 0,
            "source_hash": source_hash_from(source_files),
            "profile_digest": profile_payload["digest"],
            "output_hash": output_hash_from(record["commands"], artifact_hashes),
            "artifact_hashes": dict(artifact_hashes),
        }
        records.append(record)
    report_html = report_path.with_name("report.html")
    return {
        "schema_version": 1,
        "ledger": "R1-R14",
        "source": {"commit": "synthetic-commit", "files": source_files},
        "profile": profile_payload,
        "report": {
            "path": str(report_path.relative_to(root)),
            "sha256": sha256_file(report_path),
            "html_path": str(report_html.relative_to(root)),
            "html_sha256": sha256_file(report_html),
        },
        "records": records,
    }


def _problems(workspace: dict[str, Path], document: dict) -> list[str]:
    doc_path = workspace["evidence"] / "traceability.json"
    doc_path.write_text(json.dumps(document), encoding="utf-8")
    return validate_traceability(
        doc_path,
        report_path=workspace["report"],
        repo_root=workspace["root"],
        evidence_root=workspace["evidence"],
        check_commit=False,
    )


def test_valid_matrix_accepted(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    assert _problems(workspace, document) == []
    assert validate_report(workspace["report"]) == []
    assert set(document["profile"]) - {"digest"}
    assert profile_digest_from(document["profile"]) == document["profile"]["digest"]


def test_missing_record_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["records"] = [record for record in document["records"] if record["requirement"] != "R7"]
    problems = _problems(workspace, document)
    assert any("missing required record R7" in problem for problem in problems)


def test_duplicate_record_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["records"].append(copy.deepcopy(document["records"][2]))
    problems = _problems(workspace, document)
    assert any("duplicates" in problem for problem in problems)


def test_unknown_record_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["records"][4]["requirement"] = "R99"
    problems = _problems(workspace, document)
    assert any("unknown requirement" in problem for problem in problems)


def test_nonzero_command_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["records"][1]["commands"][0]["exit_code"] = 3
    problems = _problems(workspace, document)
    assert any("recorded nonzero exit_code" in problem for problem in problems)


def test_missing_artifact_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["records"][0]["evidence_artifacts"][0]["path"] = "evidence/does-not-exist.json"
    document["records"][0]["result"]["artifact_hashes"] = {
        "evidence/does-not-exist.json": document["records"][0]["result"]["artifact_hashes"]["evidence/artifact.json"]
    }
    problems = _problems(workspace, document)
    assert any("missing on disk" in problem for problem in problems)


def test_source_hash_mismatch_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["source"]["files"][0]["sha256"] = "0" * 64
    problems = _problems(workspace, document)
    assert any("hash mismatch" in problem for problem in problems)


def test_profile_hash_mismatch_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["profile"]["digest"] = "1" * 64
    problems = _problems(workspace, document)
    assert any("profile.digest recomputation mismatch" in problem for problem in problems)


def test_output_hash_mismatch_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["records"][3]["result"]["output_hash"] = "2" * 64
    problems = _problems(workspace, document)
    assert any("output_hash recomputation mismatch" in problem for problem in problems)


def test_malformed_command_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["records"][5]["commands"][0]["argv"] = []
    document["records"][5]["commands"][0].pop("stderr_sha256")
    problems = _problems(workspace, document)
    assert any("argv must be a non-empty string list" in problem for problem in problems)
    assert any("missing stderr_sha256" in problem for problem in problems)


def test_path_escape_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    escaped = workspace["root"] / "escaped.json"
    escaped.write_text('{"escaped": true}', encoding="utf-8")
    document["records"][6]["evidence_artifacts"][0] = {"path": "escaped.json", "sha256": sha256_file(escaped)}
    document["records"][6]["result"]["artifact_hashes"] = {"escaped.json": sha256_file(escaped)}
    problems = _problems(workspace, document)
    assert any("path escapes the evidence root" in problem for problem in problems)


def test_retired_vocabulary_is_rejected(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    document["records"][7]["tests"][0]["nodeid"] = f"{_PREVIEW}-node"
    problems = _problems(workspace, document)
    assert any("retired executable vocabulary" in problem for problem in problems)


def test_cli_accepts_traceability_and_reports_ok(workspace: dict[str, Path], monkeypatch) -> None:
    document = _document(workspace)
    assert _problems(workspace, document) == []
    doc_path = workspace["evidence"] / "traceability.json"
    # The CLI resolves the report and its declared evidence under the module root,
    # so point the module at the synthetic workspace for this invocation.
    monkeypatch.setattr("scripts.embedding_research.validate_fixture_report._ROOT", workspace["root"])
    monkeypatch.setattr("scripts.embedding_research.validate_fixture_report.EVIDENCE_ROOT", Path("evidence"))
    code = validate_main([str(workspace["report"]), "--traceability", str(doc_path)])
    assert code == 0


def test_cli_rejects_missing_traceability_file(workspace: dict[str, Path]) -> None:
    code = validate_main([str(workspace["report"]), "--traceability", str(workspace["evidence"] / "absent.json")])
    assert code == 1


def test_recursive_self_invocation_is_not_executed(workspace: dict[str, Path]) -> None:
    document = _document(workspace)
    for record in document["records"]:
        record["commands"] = [
            {
                "argv": [
                    sys.executable,
                    "-m",
                    "scripts.embedding_research.validate_fixture_report",
                    "report.json",
                    "--traceability",
                    "traceability.json",
                ],
                "cwd": ".",
                "exit_code": 0,
                "stdout_sha256": sha256_bytes(b""),
                "stderr_sha256": sha256_bytes(b""),
            }
        ]
        record["result"]["output_hash"] = output_hash_from(record["commands"], record["result"]["artifact_hashes"])
    # A recursive replay would re-enter the validator (and here fail); skipping yields PASS.
    assert _problems(workspace, document) == []


def test_report_has_no_retired_identity_columns(workspace: dict[str, Path]) -> None:
    report = json.loads(workspace["report"].read_text(encoding="utf-8"))
    blob = json.dumps(report)
    assert _PREVIEW not in blob
    assert _j("cat", "alog", "_fingerprint") not in blob
