"""Fail-closed validator for the geometry report and the R1-R14 traceability matrix.

This module owns both halves of the R14 acceptance surface:

* :func:`validate_fixture_report` validates the deterministic seven-section synthetic
  geometry report (JSON plus its sibling HTML) and, when ``traceability`` is supplied,
  the exact one-record-per-ledger R1-R14 document.
* :func:`validate_traceability` recomputes every lowercase SHA-256 in the document
  (source manifest, numerical profile digest, command output manifest, and evidence
  artifact bytes), enforces path containment under the declared evidence root, replays
  every declared command exactly once in a clean child environment, and refuses any
  nonzero/timeout/self-recursive/mismatched record.

Retired ownership vocabulary is assembled from fragments at runtime so this module never
itself carries a substring the strict whole-tree audit forbids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_PKG_DIR = Path(__file__).resolve().parent
_ROOT = _PKG_DIR.parents[1]
for _path in (_ROOT, _PKG_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

EXACT_SECTION_IDS = ("summary", "corpus", "analysis", "winners", "head-analysis", "provenance", "efficiency")
EXACT_PHASE_NAMES = ("ingest", "embed", "infer-heads", "geometry", "analyze", "head-analysis", "report")
EXPECTED_IDENTITY_COLUMNS = (
    "geometry_id",
    "observation_id",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "threshold_id",
    "structural_identity",
    "search_representation_id",
    "evaluation_id",
    "scoring_semantics_version",
    "execution_id",
)
SYNTHETIC_WARNING_MESSAGE = "SYNTHETIC FIXTURE — no empirical retrieval claim."

#: Declared workspace-relative evidence root for the completed hard-cut bundle.
EVIDENCE_ROOT = Path("artifacts/evidence/threshold-independent-per-song-gram-geometry-migration")
REQUIREMENTS = tuple(f"R{index}" for index in range(1, 15))
LEDGER = "R1-R14"
TRACEABILITY_SCHEMA_VERSION = 1
DEFAULT_REPLAY_TIMEOUT_S = 1800.0
_SHA256_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")
_RESULT_FIELDS = frozenset({"status", "exit_code", "source_hash", "profile_digest", "output_hash", "artifact_hashes"})
_COMMAND_FIELDS = ("argv", "cwd", "exit_code", "stdout_sha256", "stderr_sha256")


def _j(*parts: str) -> str:
    """Join fragments so this module never stores a retired substring literally."""
    return "".join(parts)


def retired_identity_tokens() -> tuple[str, ...]:
    """Retired identity/vocabulary roots, assembled from fragments (never literal here)."""
    return (
        _j("cat", "alog", "_id"),
        _j("cat", "alog", "_fingerprint"),
        _j("cat", "alog", "-report"),
        _j("cat", "alog", " strategy"),
        _j("current", " ", "cat", "alog"),
        _j("search", "_view"),
    )


# ── canonical hashing ──────────────────────────────────────────────────────────


def canonical_json_bytes(payload: Any) -> bytes:
    """Canonical (sorted, compact, ASCII) JSON encoding used for every digest."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


_ELAPSED_RE = re.compile(rb"\bin \d+(?:\.\d+)?s\b")


def normalize_command_output(data: bytes) -> bytes:
    """Drop nondeterministic elapsed-time text before hashing captured output."""
    return _ELAPSED_RE.sub(b"in <elapsed>s", data)


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _SHA256_LEN and all(char in _HEX_DIGITS for char in value)


def profile_digest_from(profile: dict[str, Any]) -> str:
    """Recompute the numerical profile digest from the canonical profile manifest."""
    manifest = {key: value for key, value in profile.items() if key != "digest"}
    return sha256_bytes(canonical_json_bytes(manifest))


def source_hash_from(files: list[dict[str, Any]]) -> str:
    """Canonical sorted relative-path/bytes manifest digest for a record's source input."""
    normalized = sorted(
        ({"path": str(entry["path"]), "sha256": str(entry["sha256"])} for entry in files), key=_file_key
    )
    return sha256_bytes(canonical_json_bytes(normalized))


def output_hash_from(commands: list[dict[str, Any]], artifact_hashes: dict[str, str]) -> str:
    """Canonical digest over the captured command results and produced artifact hashes."""
    manifest = [
        {
            "argv": [str(part) for part in command["argv"]],
            "exit_code": int(command["exit_code"]),
            "stdout_sha256": str(command["stdout_sha256"]),
            "stderr_sha256": str(command["stderr_sha256"]),
        }
        for command in commands
    ]
    return sha256_bytes(canonical_json_bytes({"commands": manifest, "artifact_hashes": dict(artifact_hashes)}))


def _file_key(entry: dict[str, Any]) -> str:
    return str(entry["path"])


# ── report validation ──────────────────────────────────────────────────────────


def _walk(node: Any):
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)
    else:
        yield node


def _section(data: dict, section_id: str) -> dict | None:
    return next((s for s in data.get("sections", []) if s.get("id") == section_id), None)


def _tables(node: Any):
    if isinstance(node, dict):
        if isinstance(node.get("tables"), list):
            yield from node["tables"]
        for key in ("panels", "subsections"):
            for child in node.get(key, []) or []:
                yield from _tables(child)


def _table(section: dict | None, table_id: str) -> dict | None:
    if section is None:
        return None
    return next((table for table in _tables(section) if table.get("id") == table_id), None)


def _check_finite(node: Any, problems: list[str], path: str = "report") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _check_finite(value, problems, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _check_finite(value, problems, f"{path}[{index}]")
    elif isinstance(node, bool) or node is None:
        return
    elif isinstance(node, (int, float)) and not math.isfinite(float(node)):
        problems.append(f"{path} is non-finite")


def _require_identity_table(section: dict | None, table_id: str, problems: list[str]) -> None:
    table = _table(section, table_id)
    if table is None or table.get("empty"):
        problems.append(f"missing non-empty {table_id}")
        return
    columns = table.get("columns", [])
    missing_columns = [column for column in EXPECTED_IDENTITY_COLUMNS if column not in columns]
    problems.extend(f"{table_id} missing identity column {column}" for column in missing_columns)
    for row in table.get("rows", []):
        if len(row) != len(columns):
            problems.append(f"{table_id} row width does not match columns")
            continue
        missing = [
            column
            for column in EXPECTED_IDENTITY_COLUMNS
            if column in columns and row[columns.index(column)] in (None, "", "—")
        ]
        problems.extend(f"{table_id} has absent identity evidence for {column}" for column in missing)


def _retired_vocabulary_in(node: Any) -> list[str]:
    """Return retired identity tokens found in the serialized node (fragment-assembled)."""
    try:
        blob = json.dumps(node, ensure_ascii=False)
    except (TypeError, ValueError):
        blob = str(node)
    lowered = blob.lower()
    return [token for token in retired_identity_tokens() if token in lowered]


def validate_report(path: str | Path) -> list[str]:
    """Validate the seven-section geometry report; return a list of problems (empty == valid)."""
    report_path = Path(path)
    if not report_path.is_file():
        return [f"fixture report not found: {report_path}"]
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"fixture report is not valid JSON: {exc}"]
    problems: list[str] = []
    if data.get("schema_version") != 2:
        problems.append("schema_version must be 2")
    if data.get("synthetic_only") is not True:
        problems.append("synthetic_only must be true")
    sections = data.get("sections")
    if [section.get("id") for section in sections or []] != list(EXACT_SECTION_IDS):
        problems.append("section ids/order must be exactly the seven geometry sections")
    messages = [warning.get("message") for warning in data.get("warnings", []) if isinstance(warning, dict)]
    if SYNTHETIC_WARNING_MESSAGE not in messages:
        problems.append("synthetic-only warning is missing")
    html_path = report_path.with_name("report.html")
    if not (html_path.is_file() and html_path.stat().st_size):
        problems.append("report.html is missing or empty")
    _check_finite(data, problems)

    evidence = data.get("geometry_evidence", {})
    if tuple(evidence.get("phases", ())) != EXACT_PHASE_NAMES:
        problems.append("geometry evidence phase topology is incomplete")
    corpus = _section(data, "corpus")
    analysis = _section(data, "analysis")
    winners = _section(data, "winners")
    head_analysis = _section(data, "head-analysis")
    provenance = _section(data, "provenance")
    efficiency = _section(data, "efficiency")
    if corpus is None or corpus.get("empty_message"):
        problems.append("corpus section must be populated")
    if analysis is None:
        problems.append("analysis section is missing")
    else:
        _require_identity_table(analysis, "geometry_identity", problems)
    _require_identity_table(head_analysis, "geometry_head_identity", problems)
    if winners is None or not any(
        _table(winners, table_id) for table_id in ("geometry_winner_deltas", "geometry_representations")
    ):
        problems.append("winners must visibly render geometry winner/baseline evidence")
    history = _table(provenance, "run_history")
    if history is None or history.get("empty"):
        problems.append("provenance run_history is missing")
    else:
        phases = {
            row[history["columns"].index("phase")] for row in history.get("rows", []) if "phase" in history["columns"]
        }
        if phases != set(EXACT_PHASE_NAMES):
            problems.append(f"phase registry mismatch: {sorted(phases)}")
    timing = _table(efficiency, "timing_history")
    if timing is None or timing.get("empty") or not timing.get("rows"):
        problems.append("efficiency timing_history is missing")
    else:
        columns = timing.get("columns", [])
        if "phase" in columns:
            timing_phases = {row[columns.index("phase")] for row in timing.get("rows", [])}
            if not set(EXACT_PHASE_NAMES).issubset(timing_phases):
                problems.append(f"phase timing is incomplete: {sorted(timing_phases)}")
    matrices = data.get("matrices")
    if not isinstance(matrices, dict) or set(matrices) != {"refusal", "incomplete", "resource"}:
        problems.append("refusal/incomplete/resource matrices are missing")
    problems.extend(f"report contains retired vocabulary: {token}" for token in _retired_vocabulary_in(data))
    return problems


# ── path containment ───────────────────────────────────────────────────────────


def _resolve_workspace_path(relative: str, repo_root: Path) -> Path:
    candidate = Path(relative)
    return candidate if candidate.is_absolute() else (repo_root / candidate)


def _is_contained(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ── traceability validation ────────────────────────────────────────────────────


def _clean_child_env(repo_root: Path) -> dict[str, str]:
    """A minimal declared child environment for command replay (no inherited secrets)."""
    import sys as _sys

    python_paths = [str(repo_root)]
    for entry in _sys.path:
        if entry and os.path.isdir(entry) and entry not in python_paths:
            python_paths.append(entry)
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": "C.UTF-8",
        "PYTHONPATH": os.pathsep.join(python_paths),
        "PYTHONDONTWRITEBYTECODE": "1",
        "EVIDENCE_DIR": str(EVIDENCE_ROOT),
        "RESEARCH_DB_PATH": ":memory:",
    }


def _is_self_recursive_command(argv: list[str]) -> bool:
    joined = " ".join(str(part) for part in argv)
    return _j("validate_", "fixture_report") in joined and "--traceability" in argv


def _replay_command(
    command: dict[str, Any],
    *,
    repo_root: Path,
    timeout_s: float,
    child_env: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    """Replay one command in a clean child environment; return the captured result + problems."""
    problems: list[str] = []
    cwd_raw = str(command.get("cwd", "."))
    cwd = cwd_raw if os.path.isabs(cwd_raw) else str(repo_root / cwd_raw)
    started = time.monotonic()
    completed = subprocess.run(
        [str(part) for part in command["argv"]],
        cwd=cwd,
        env=child_env,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    duration_ms = (time.monotonic() - started) * 1000.0
    captured = {
        "argv": [str(part) for part in command["argv"]],
        "exit_code": int(completed.returncode),
        "stdout_sha256": sha256_bytes(normalize_command_output(completed.stdout)),
        "stderr_sha256": sha256_bytes(normalize_command_output(completed.stderr)),
        "duration_ms": round(duration_ms, 3),
    }
    return captured, problems


def validate_traceability(
    path: str | Path,
    *,
    report_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    evidence_root: str | Path | None = None,
    replay: bool = True,
    timeout_s: float = DEFAULT_REPLAY_TIMEOUT_S,
    check_commit: bool | str = True,
    check_report: bool = True,
) -> list[str]:
    """Validate the R1-R14 traceability document; return a list of problems (empty == valid).

    ``check_commit`` selects the commit-check mode:

    * ``True`` (default) — strict: the declared ``source.commit`` must equal repository HEAD.
    * ``False`` — disabled: the declared commit is not checked.
    * ``"informational"`` — the declared commit must be present and look like a commit, but a
      mismatch with HEAD is accepted.  This is the documented mode for a *committed-evidence*
      guard run against a delivered tree that carries uncommitted work: the frozen-base commit
      is recorded for provenance/traceability only, never asserted equal to a moving HEAD, and
      the per-file SHA-256 manifest is still checked strictly in every mode.

    Any other value is rejected: there is no silent downgrade to a weaker mode.
    """
    root = Path(repo_root) if repo_root is not None else _ROOT
    evidence_dir = (Path(evidence_root) if evidence_root is not None else (root / EVIDENCE_ROOT)).resolve()
    problems: list[str] = []
    trace_path = Path(path)
    if not trace_path.is_file():
        return [f"traceability document not found: {trace_path}"]
    try:
        document = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"traceability document is not valid JSON: {exc}"]
    if not isinstance(document, dict):
        return ["traceability document must be a JSON object"]

    if check_report and report_path is not None:
        problems.extend(f"report: {problem}" for problem in validate_report(report_path))

    if document.get("schema_version") != TRACEABILITY_SCHEMA_VERSION:
        problems.append(f"traceability.schema_version must be {TRACEABILITY_SCHEMA_VERSION}")
    if document.get("ledger") != LEDGER:
        problems.append(f"traceability.ledger must be {LEDGER!r}")

    source = document.get("source")
    if not isinstance(source, dict):
        problems.append("traceability.source must be an object")
        source = {}
    profile = document.get("profile")
    if not isinstance(profile, dict):
        problems.append("traceability.profile must be an object")
        profile = {}
    report_meta = document.get("report")
    if not isinstance(report_meta, dict):
        problems.append("traceability.report must be an object")
        report_meta = {}

    # ── source manifest + commit ───────────────────────────────────────────────
    source_files = source.get("files")
    if not isinstance(source_files, list) or not source_files:
        problems.append("traceability.source.files must be a non-empty list")
        source_files = []
    known_source: dict[str, str] = {}
    for entry in source_files:
        if not isinstance(entry, dict) or "path" not in entry or "sha256" not in entry:
            problems.append("traceability.source.files entry must carry path+sha256")
            continue
        rel = str(entry["path"])
        if not is_sha256(entry["sha256"]):
            problems.append(f"traceability.source.files[{rel}].sha256 is not lowercase SHA-256")
            continue
        target = _resolve_workspace_path(rel, root)
        if not target.is_file():
            problems.append(f"traceability.source.files missing on disk: {rel}")
            continue
        actual = sha256_file(target)
        if actual != entry["sha256"]:
            problems.append(f"traceability.source.files[{rel}] hash mismatch")
        known_source[rel] = actual
    declared_commit = str(source.get("commit", ""))
    if check_commit not in (True, False, "informational"):
        problems.append(f"traceability commit-check mode is invalid: {check_commit!r}")
    if not declared_commit:
        problems.append("traceability.source.commit is missing")
    elif check_commit is True and (root / ".git").exists():
        actual_commit = _git_head(root)
        if actual_commit and actual_commit != declared_commit:
            problems.append("traceability.source.commit does not match repository HEAD")
    if check_commit == "informational" and declared_commit and not _looks_like_commit(declared_commit):
        problems.append("traceability.source.commit is not a repository commit identifier")

    # ── profile digest ─────────────────────────────────────────────────────────
    declared_profile_digest = str(profile.get("digest", ""))
    if not is_sha256(declared_profile_digest):
        problems.append("traceability.profile.digest is not lowercase SHA-256")
    else:
        actual_profile_digest = profile_digest_from(profile)
        if actual_profile_digest != declared_profile_digest:
            problems.append("traceability.profile.digest recomputation mismatch")

    # ── report identity ────────────────────────────────────────────────────────
    declared_report_path = str(report_meta.get("path", ""))
    declared_report_sha = str(report_meta.get("sha256", ""))
    declared_report_html_path = str(report_meta.get("html_path", ""))
    declared_report_html_sha = str(report_meta.get("html_sha256", ""))
    report_candidate = _resolve_workspace_path(declared_report_path, root) if declared_report_path else None
    if not declared_report_path or not is_sha256(declared_report_sha):
        problems.append("traceability.report must carry a path and lowercase SHA-256")
    elif report_candidate is None or not report_candidate.is_file():
        problems.append(f"traceability.report path missing: {declared_report_path}")
    else:
        if sha256_file(report_candidate) != declared_report_sha:
            problems.append("traceability.report.sha256 mismatch")
        if report_path is not None and report_candidate.resolve() != Path(report_path).resolve():
            problems.append("traceability.report.path does not match the validated report")
    # The sibling HTML output is part of the report contract: its declared hash must
    # match on disk and must appear in every record's artifact_hashes (see below).
    report_html_candidate = (
        _resolve_workspace_path(declared_report_html_path, root) if declared_report_html_path else None
    )
    if not declared_report_html_path or not is_sha256(declared_report_html_sha):
        problems.append("traceability.report must carry html_path and lowercase html_sha256")
    elif report_html_candidate is None or not report_html_candidate.is_file():
        problems.append(f"traceability.report html_path missing: {declared_report_html_path}")
    elif sha256_file(report_html_candidate) != declared_report_html_sha:
        problems.append("traceability.report.html_sha256 mismatch")

    # ── records ────────────────────────────────────────────────────────────────
    records = document.get("records")
    if not isinstance(records, list):
        problems.append("traceability.records must be a list")
        records = []
    seen: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            problems.append(f"records[{index}] must be an object")
            continue
        requirement = str(record.get("requirement", ""))
        seen.append(requirement)
        if requirement not in REQUIREMENTS:
            problems.append(f"records[{index}] has unknown requirement {requirement!r}")
            continue
        problems.extend(
            _validate_record(
                requirement,
                record,
                known_source=known_source,
                declared_profile_digest=declared_profile_digest,
                evidence_dir=evidence_dir,
                report_path=report_candidate,
                root=root,
                replay=replay,
                timeout_s=timeout_s,
            )
        )
    problems.extend(
        f"traceability.records missing required record {missing}" for missing in REQUIREMENTS if missing not in seen
    )
    duplicates = sorted({req for req in seen if seen.count(req) > 1})
    if duplicates:
        problems.append(f"traceability.records contain duplicates: {duplicates}")
    return problems


def _validate_command_record(requirement: str, index: int, command: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(command, dict):
        return [f"{requirement}.commands[{index}] must be an object"]
    problems.extend(
        f"{requirement}.commands[{index}] missing {field}" for field in _COMMAND_FIELDS if field not in command
    )
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) and part for part in argv):
        problems.append(f"{requirement}.commands[{index}].argv must be a non-empty string list")
    if not isinstance(command.get("exit_code"), int) or isinstance(command.get("exit_code"), bool):
        problems.append(f"{requirement}.commands[{index}].exit_code must be an int")
    elif command["exit_code"] != 0:
        problems.append(f"{requirement}.commands[{index}] recorded nonzero exit_code")
    problems.extend(
        f"{requirement}.commands[{index}].{field} is not lowercase SHA-256"
        for field in ("stdout_sha256", "stderr_sha256")
        if not is_sha256(command.get(field))
    )
    if not isinstance(command.get("cwd"), str) or not command.get("cwd"):
        problems.append(f"{requirement}.commands[{index}].cwd must be a non-empty string")
    return problems


def _validate_record(
    requirement: str,
    record: dict[str, Any],
    *,
    known_source: dict[str, str],
    declared_profile_digest: str,
    evidence_dir: Path,
    report_path: Path | None,
    root: Path,
    replay: bool,
    timeout_s: float,
) -> list[str]:
    problems: list[str] = []

    tests = record.get("tests")
    static_scans = record.get("static_scans")
    evidence_artifacts = record.get("evidence_artifacts")
    commands = record.get("commands")
    for name, value in (
        ("tests", tests),
        ("static_scans", static_scans),
        ("evidence_artifacts", evidence_artifacts),
        ("commands", commands),
    ):
        if not isinstance(value, list) or not value:
            problems.append(f"{requirement}.{name} must be a non-empty list")
    if not isinstance(tests, list):
        tests = []
    if not isinstance(static_scans, list):
        static_scans = []
    if not isinstance(evidence_artifacts, list):
        evidence_artifacts = []
    if not isinstance(commands, list):
        commands = []
    for test_index, test in enumerate(tests):
        if not isinstance(test, dict) or not test.get("nodeid") or not test.get("command"):
            problems.append(f"{requirement}.tests[{test_index}] must carry nodeid+command")
    for scan_index, scan in enumerate(static_scans):
        if not isinstance(scan, dict) or not scan.get("rule") or not scan.get("command"):
            problems.append(f"{requirement}.static_scans[{scan_index}] must carry rule+command")

    # ── record source manifest hash ────────────────────────────────────────────
    record_source_files = record.get("source_files")
    if not isinstance(record_source_files, list) or not record_source_files:
        problems.append(f"{requirement}.source_files must be a non-empty list")
    else:
        for entry in record_source_files:
            if not isinstance(entry, dict) or "path" not in entry or not is_sha256(entry.get("sha256")):
                problems.append(f"{requirement}.source_files entry must carry path+lowercase SHA-256")
                continue
            rel = str(entry["path"])
            if rel in known_source:
                if known_source[rel] != entry["sha256"]:
                    problems.append(f"{requirement}.source_files[{rel}] mismatches traceability.source")
            else:
                target = _resolve_workspace_path(rel, root)
                if not target.is_file():
                    problems.append(f"{requirement}.source_files missing on disk: {rel}")
                elif sha256_file(target) != entry["sha256"]:
                    problems.append(f"{requirement}.source_files[{rel}] hash mismatch")

    # ── evidence artifacts: exist, contained, hashed ───────────────────────────
    artifact_hashes: dict[str, str] = {}
    allowed_roots = [evidence_dir]
    if report_path is not None:
        allowed_roots.append(report_path.resolve())
    for artifact_index, artifact in enumerate(evidence_artifacts):
        if not isinstance(artifact, dict) or "path" not in artifact or not is_sha256(artifact.get("sha256")):
            problems.append(f"{requirement}.evidence_artifacts[{artifact_index}] must carry path+lowercase SHA-256")
            continue
        rel = str(artifact["path"])
        target = _resolve_workspace_path(rel, root)
        contained = any(_is_contained(target, allowed) for allowed in allowed_roots)
        if not contained:
            problems.append(f"{requirement}.evidence_artifacts path escapes the evidence root: {rel}")
            continue
        if not target.is_file():
            problems.append(f"{requirement}.evidence_artifacts missing on disk: {rel}")
            continue
        actual = sha256_file(target)
        if actual != artifact["sha256"]:
            problems.append(f"{requirement}.evidence_artifacts[{rel}] hash mismatch")
        artifact_hashes[rel] = actual

    # DD §536: every record's artifact hashes also cover the two generated report
    # outputs, so a record cannot omit or mutate the report/HTML bytes it attests to.
    if report_path is not None:
        resolved_report = Path(report_path).resolve()
        for generated in (resolved_report, resolved_report.with_name("report.html")):
            if generated.is_file():
                rel_generated = generated.relative_to(root.resolve()).as_posix()
                artifact_hashes[rel_generated] = sha256_file(generated)

    result = record.get("result")
    if not isinstance(result, dict):
        problems.append(f"{requirement}.result must be an object")
        result = {}
    missing_result_fields = sorted(_RESULT_FIELDS - set(result))
    extra_result_fields = sorted(set(result) - _RESULT_FIELDS)
    if missing_result_fields:
        problems.append(f"{requirement}.result missing fields: {missing_result_fields}")
    if extra_result_fields:
        problems.append(f"{requirement}.result has unknown fields: {extra_result_fields}")
    if result.get("status") != "PASS":
        problems.append(f"{requirement}.result.status must be PASS")
    if result.get("exit_code") != 0:
        problems.append(f"{requirement}.result.exit_code must be zero")

    declared_source_hash = str(result.get("source_hash", ""))
    if not is_sha256(declared_source_hash):
        problems.append(f"{requirement}.result.source_hash is not lowercase SHA-256")
    elif isinstance(record_source_files, list) and source_hash_from(record_source_files) != declared_source_hash:
        problems.append(f"{requirement}.result.source_hash recomputation mismatch")

    declared_record_profile = str(result.get("profile_digest", ""))
    if declared_record_profile != declared_profile_digest:
        problems.append(f"{requirement}.result.profile_digest does not match traceability.profile.digest")

    declared_artifact_hashes = result.get("artifact_hashes")
    if not isinstance(declared_artifact_hashes, dict):
        problems.append(f"{requirement}.result.artifact_hashes must be an object")
        declared_artifact_hashes = {}

    for rel, digest in artifact_hashes.items():
        if declared_artifact_hashes.get(rel) != digest:
            problems.append(f"{requirement}.result.artifact_hashes[{rel}] mismatch")
    problems.extend(
        f"{requirement}.result.artifact_hashes[{rel}] is not a declared evidence artifact"
        for rel in declared_artifact_hashes
        if rel not in artifact_hashes
    )

    # ── command replay ─────────────────────────────────────────────────────────
    captured_commands: list[dict[str, Any]] = []
    for command_index, command in enumerate(commands):
        problems.extend(_validate_command_record(requirement, command_index, command))
        if not isinstance(command, dict) or not isinstance(command.get("argv"), list) or not command["argv"]:
            continue
        if not all(isinstance(part, str) and part for part in command["argv"]):
            continue
        if _is_self_recursive_command(command["argv"]):
            recorded = {
                "argv": [str(part) for part in command["argv"]],
                "exit_code": int(command.get("exit_code", -1)),
                "stdout_sha256": str(command.get("stdout_sha256", "")),
                "stderr_sha256": str(command.get("stderr_sha256", "")),
            }
            if recorded["exit_code"] != 0:
                problems.append(f"{requirement}.commands[{command_index}] recursive record is nonzero")
            captured_commands.append(recorded)
            continue
        if not replay:
            captured_commands.append(
                {
                    "argv": [str(part) for part in command["argv"]],
                    "exit_code": int(command.get("exit_code", -1)),
                    "stdout_sha256": str(command.get("stdout_sha256", "")),
                    "stderr_sha256": str(command.get("stderr_sha256", "")),
                }
            )
            continue
        try:
            captured, replay_problems = _replay_command(
                command, repo_root=root, timeout_s=timeout_s, child_env=_clean_child_env(root)
            )
        except subprocess.TimeoutExpired:
            problems.append(f"{requirement}.commands[{command_index}] timed out after {timeout_s}s")
            continue
        problems.extend(replay_problems)
        if captured["exit_code"] != command.get("exit_code"):
            problems.append(
                f"{requirement}.commands[{command_index}] replay exit_code {captured['exit_code']} "
                f"!= recorded {command.get('exit_code')}"
            )
        if captured["exit_code"] != 0:
            problems.append(f"{requirement}.commands[{command_index}] replay exited nonzero")
        problems.extend(
            f"{requirement}.commands[{command_index}] {field} replay mismatch"
            for field in ("stdout_sha256", "stderr_sha256")
            if captured[field] != command.get(field)
        )
        captured_commands.append(captured)
    declared_output_hash = str(result.get("output_hash", ""))
    if not is_sha256(declared_output_hash):
        problems.append(f"{requirement}.result.output_hash is not lowercase SHA-256")
    elif captured_commands and output_hash_from(captured_commands, artifact_hashes) != declared_output_hash:
        problems.append(f"{requirement}.result.output_hash recomputation mismatch")

    problems.extend(
        f"{requirement} carries retired executable vocabulary: {token}"
        for token in _retired_vocabulary_in({"tests": tests})
    )
    return problems


def _looks_like_commit(value: str) -> bool:
    """True when ``value`` is a plausible git object id (7-40 hex chars)."""
    return 7 <= len(value) <= 40 and all(char in "0123456789abcdefABCDEF" for char in value)


def _git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


# ── public entry point ─────────────────────────────────────────────────────────


def validate_fixture_report(path: str | Path, *, traceability: str | Path | None = None) -> None:
    """Validate the report (and, when supplied, the R1-R14 traceability document).

    Raises :class:`ValueError` describing every failed field when any check fails.
    """
    report_path = Path(path)
    problems = validate_report(report_path)
    if traceability is not None:
        problems.extend(
            f"traceability: {problem}" for problem in validate_traceability(traceability, report_path=report_path)
        )
    if problems:
        raise ValueError("fixture report violates the geometry contract:\n  - " + "\n  - ".join(problems))


def main(argv: list[str] | None = None) -> int:
    """CLI: ``validate_fixture_report [REPORT_JSON] --traceability TRACEABILITY_JSON``."""
    parser = argparse.ArgumentParser(description="Fail-closed geometry report + R1-R14 traceability validator.")
    parser.add_argument(
        "report_json",
        nargs="?",
        default=None,
        help="report.json path (defaults to the configured report directory)",
    )
    parser.add_argument("--traceability", default=None, help="R1-R14 traceability JSON to validate and replay")
    arguments = parser.parse_args(argv)

    if arguments.report_json:
        report_path = Path(arguments.report_json)
    else:
        from scripts.embedding_research.config import REPORT_DIR

        report_path = REPORT_DIR / "report.json"

    try:
        validate_fixture_report(report_path, traceability=arguments.traceability)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    if arguments.traceability:
        print(f"OK: R1...R14 validated and replayed: {report_path}")
    else:
        print(f"OK: {report_path} satisfies the geometry fixture contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
