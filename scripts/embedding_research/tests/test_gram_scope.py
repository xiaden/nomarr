"""R13 — excluded production scope, synthetic-only fixtures, no optimizer/ANN/CTP artifact."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from scripts.embedding_research.tests._gram_evidence import EVIDENCE_ROOT, emit_evidence

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {"nomarr", "frontend", "onnxruntime", "torch", "cuda", "tensorflow", "jax", "librosa", "soundfile"}
)
# Assembled from fragments so the forbidden token is not itself a source literal.
_FORBIDDEN_TOKENS = (
    "cat" + "alog",
    "ctp",
    "optimiz" + "er",
    "approximate_" + "nearest",
    "ann_" + "index",
    "hnsw",
    "faiss",
    "spectral",
)
_REAL_ARTIFACT_SUFFIXES = frozenset(
    {".onnx", ".wav", ".flac", ".mp3", ".m4a", ".npy", ".npz", ".ckpt", ".pt", ".pth", ".duckdb", ".db"}
)
#: The geometry-era CPU path that must never reach production, audio, or an ANN/CTP optimizer.
_CPU_SURFACE = (
    "run.py",
    "cleanup.py",
    "common/geometry_analysis.py",
    "common/threshold_analysis.py",
    "common/head_analysis.py",
    "helpers/gram_segmentation.py",
    "helpers/chebyshev_segmentation.py",
    "db/geometry.py",
    "db/geometry_profile.py",
    "report/__init__.py",
)


def _package_sources():
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_excluded_scope_and_static_dependencies() -> None:
    violations: list[tuple[str, str]] = []
    for rel in _CPU_SURFACE:
        path = _PACKAGE_ROOT / rel
        assert path.is_file(), f"expected geometry CPU surface module missing: {rel}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for entry in node.names:
                    if entry.name.split(".")[0] in _FORBIDDEN_IMPORT_ROOTS:
                        violations.append((rel, entry.name))  # noqa: PERF401
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in _FORBIDDEN_IMPORT_ROOTS:
                violations.append((rel, node.module or ""))
    assert violations == [], f"production/research-tree imports on the CPU path: {violations}"

    token_hits: list[tuple[str, str]] = []
    for rel in _CPU_SURFACE:
        text = (_PACKAGE_ROOT / rel).read_text(encoding="utf-8").lower()
        for token in _FORBIDDEN_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", text):
                token_hits.append((rel, token))  # noqa: PERF401
    for path in sorted((_PACKAGE_ROOT / "tests").glob("test_gram_*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for token in _FORBIDDEN_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", text):
                token_hits.append((path.name, token))  # noqa: PERF401
    for helper in ("_gram_evidence.py", "_scalar_oracle.py"):
        text = (_PACKAGE_ROOT / "tests" / helper).read_text(encoding="utf-8").lower()
        for token in _FORBIDDEN_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", text):
                token_hits.append((helper, token))  # noqa: PERF401
    assert token_hits == [], f"forbidden optimizer/ANN/CTP tokens on the CPU path: {token_hits}"
    emit_evidence("r13-excluded-scope.json", {"forbidden_imports": [], "synthetic_forbidden_tokens": []})


def test_synthetic_fixture_only() -> None:
    artifacts = [
        str(path)
        for path in _PACKAGE_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in _REAL_ARTIFACT_SUFFIXES
        and not any(part.startswith(".") or part == "__pycache__" for part in path.parts)
    ]
    assert artifacts == [], f"real corpus/audio/model artifacts present: {artifacts}"
    evidence_files = [path for path in EVIDENCE_ROOT.glob("*") if path.is_file()]
    assert evidence_files, "synthetic evidence bundle must have been emitted"
    assert all(path.suffix == ".json" for path in evidence_files), "evidence bundle must be JSON only"
    emit_evidence(
        "r13-synthetic-only.json",
        {
            "synthetic_only": True,
            "real_corpus_artifacts": artifacts,
            "evidence_json_count": len(evidence_files),
        },
    )
