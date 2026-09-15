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

from scripts.embedding_research.config import OUTPUT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

_HERE = Path(__file__).resolve()
WORKSPACE_ROOT = _HERE.parents[3]
PACKAGE_ROOT = _HERE.parents[1]
# Sole scientific JSON/hash root.  The retired artifacts/evidence fixture root is not
# a compatibility location; callers must migrate to config.OUTPUT_ROOT.
EVIDENCE_ROOT = OUTPUT_ROOT


def _j(*parts: str) -> str:
    """Join fragments so this module never stores a retired substring literally."""
    return "".join(parts)


_RESULT_SURFACE_NAMES: tuple[str, ...] = (
    "geometry_threshold_class_map",
    "geometry_class_aggregate_metrics",
    "geometry_class_query_metrics",
    "geometry_class_neighborhoods",
    "geometry_baseline_aggregate_metrics",
    "geometry_baseline_query_metrics",
    "geometry_baseline_neighborhoods",
    "geometry_evaluation_corpus",
    "geometry_threshold_structural",
    "geometry_head_label_provenance",
    "geometry_result_provenance",
)
_RESULT_METRIC_NAMES: tuple[str, ...] = ("map_k", "mrr", "ndcg_k", "recall_k", "disc")


def normalized_result_layer() -> dict[str, Any]:
    """Return the deterministic evidence contract shared by every producer."""
    return {
        "surface_names": list(_RESULT_SURFACE_NAMES),
        "threshold_to_class": {"count": 171, "first_index": 0, "last_index": 170},
        "class_scoped_metrics": {"rulers": ["artist", "genre", "head"], "metric_names": list(_RESULT_METRIC_NAMES)},
        "baseline": {"threshold_independent": True, "block_count": 1},
    }


def result_layer_scan_tokens() -> tuple[str, ...]:
    """Markers for the retired nested/EAV evidence shape.

    The active ``evidence_json`` head-evidence *column* is deliberately absent: it is a
    legitimate flat column name, so it is only forbidden when it carries the retired
    nested shape (see :func:`_retired_evidence_json`).
    """
    return ("queries[*].neighborhood", 'threshold_map\\": [', "geometry_" + "analysis_records")


#: Nested keys of the retired giant ``evidence_json`` blob.
_RETIRED_NESTED_KEYS: tuple[str, ...] = ("queries", "threshold_map", "hypotheses", "neighborhood")


def _retired_evidence_json(text: str) -> bool:
    """True only when an ``evidence_json`` key carries the retired nested shape.

    A flat ``evidence_json`` column/serialization is legitimate; the retired marker is an
    ``evidence_json`` object that itself contains one of the retired nested result keys.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return False
    return _has_nested_evidence_json(document)


def _has_nested_evidence_json(node: Any) -> bool:
    if isinstance(node, dict):
        nested = node.get("evidence_json")
        if _contains_retired_nested_key(nested):
            return True
        return any(_has_nested_evidence_json(value) for value in node.values())
    if isinstance(node, list):
        return any(_has_nested_evidence_json(value) for value in node)
    return False


def _contains_retired_nested_key(node: Any) -> bool:
    if isinstance(node, dict):
        return any(key in _RETIRED_NESTED_KEYS for key in node) or any(
            _contains_retired_nested_key(value) for value in node.values()
        )
    if isinstance(node, list):
        return any(_contains_retired_nested_key(value) for value in node)
    return False


def scan_result_layer_files(root: Path) -> list[dict[str, Any]]:
    """Find retired nested-result markers in JSON files below *root*."""
    matches: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = scan_text(text, result_layer_scan_tokens())
        if _retired_evidence_json(text):
            found = sorted({*found, "evidence_json"})
        if found:
            try:
                display_path = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                display_path = path.resolve().as_posix()
            matches.append({"path": display_path, "tokens": found})
    return matches


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _evidence_destination(path: str | Path) -> Path:
    """Resolve and validate a scientific JSON destination without touching disk."""
    root = OUTPUT_ROOT.resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        destination = candidate.resolve()
    else:
        destination = (root / candidate).resolve()
    if destination.suffix != ".json":
        raise ValueError("evidence destinations must use the .json suffix")
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError("evidence destination must be contained by OUTPUT_ROOT") from exc
    return destination


def write_evidence(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write one finite, deterministic normalized-result evidence document."""
    destination = _evidence_destination(path)
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
