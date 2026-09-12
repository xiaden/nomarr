"""Shared deterministic scan/emit helpers for the hard-cut geometry evidence bundle.

Every helper here is side-effect free apart from writing canonical JSON to an explicit
``--output`` path.  No helper reads audio, an ONNX model, CUDA, or a real corpus, and no
helper embeds a timestamp or run id: the static artifacts must hash identically when the
validator replays the declared commands.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

_HERE = Path(__file__).resolve()
WORKSPACE_ROOT = _HERE.parents[3]
PACKAGE_ROOT = _HERE.parents[1]
EVIDENCE_ROOT = WORKSPACE_ROOT / "artifacts/evidence/threshold-independent-per-song-gram-geometry-migration"


def _j(*parts: str) -> str:
    """Join fragments so this module never stores a retired substring literally."""
    return "".join(parts)


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_evidence(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write a canonical compact JSON evidence artifact (no digest field)."""
    destination = Path(path)
    if not destination.is_absolute():
        destination = WORKSPACE_ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(payload))
    return destination


def iter_python_files(root: Path, *, include_tests: bool) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        in_tests = "tests" in path.relative_to(root).parts
        if in_tests and not include_tests:
            continue
        files.append(path)
    return files


def relative(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()


def retired_rule_names() -> dict[str, tuple[str, ...]]:
    """The six independent retired-runtime rules, keys and tokens fragment-assembled."""
    return {
        _j("no-vector-centroid-runtime"): (_j("run_spherical", "_segmentation"), _j("temporal", "_segment")),
        _j("no-distance-dispatch-runtime"): (_j("global", "_dist"), _j("DIST", "_FNS")),
        _j("no-baseline-vector-adapter"): (_j("_to_unit", "_rows"),),
        _j("no-", "cat", "alog", "-head-runner"): (
            _j("run_shared_", "cat", "alog", "_head_analysis"),
            _j("_collect_segment_", "membership"),
        ),
        _j("no-", "cat", "alog", "-report-loader"): (_j("search", "_views"), _j("load_", "cat", "alog", "_report")),
        _j("no-fixture-", "cat", "alog", "-path"): (
            _j("cat", "alogs/"),
            _j("current", ".json"),
            _j("snapshot", ".duckdb"),
        ),
    }


def rule_for(name: str) -> tuple[str, ...]:
    rules = retired_rule_names()
    if name == "all":
        combined: set[str] = set()
        for tokens in rules.values():
            combined.update(tokens)
        return tuple(sorted(combined))
    if name in rules:
        return rules[name]
    assembled = _j("cat", "alog")
    available = ", ".join(sorted(rules))
    raise SystemExit(f"unknown rule {name!r} (retired {assembled} rule scan); available: {available}")


def scan_text(text: str, tokens: Iterable[str]) -> list[str]:
    lowered = text.lower()
    return sorted({token for token in tokens if token.lower() in lowered})


def scan_files(files: Iterable[Path], tokens: Iterable[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = scan_text(text, tokens)
        if found:
            matches.append({"path": relative(path), "tokens": found})
    return matches


def definition_names(text: str) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def imported_names(text: str) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(part.name.split(".")[-1] for part in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(part.name for part in node.names)
    return names


def called_names(text: str) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names
