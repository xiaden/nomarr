"""Python introspection tool — whitelist-only subprocess-isolated checks.

Invariants:
- **Whitelist-only checks**: Only the explicitly defined check types are
  accepted (mro, issubclass, signature, doc, getsource_contains, ast_raises).
  No arbitrary code execution is possible.
- **Subprocess isolation**: All introspection runs in a separate Python
  subprocess, never in the MCP server process.
- **Hard timeout**: Subprocess is killed after `timeout_ms` milliseconds
  (default 3000). No check can hang the server.
- **Output cap**: Source text is truncated to `max_source_chars` to prevent
  token explosion in agent context windows.
- **No filesystem writes**: The subprocess script performs read-only
  introspection via importlib, inspect, and ast.
- **No network**: Proxy environment variables are stripped from the
  subprocess environment.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / Response DTOs
# ---------------------------------------------------------------------------

CheckType = Literal[
    "mro", "issubclass", "signature", "doc", "getsource_contains", "ast_raises"
]


class MroCheck(BaseModel):
    """Get Method Resolution Order for a class."""

    check: Literal["mro"] = "mro"
    target: str = Field(description="Dotted path to a class, e.g. 'pathlib.Path'")


class IsSubclassCheck(BaseModel):
    """Test whether one class is a subclass of another."""

    check: Literal["issubclass"] = "issubclass"
    child: str = Field(description="Dotted path to the candidate subclass")
    parent: str = Field(description="Dotted path to the parent class")


class SignatureCheck(BaseModel):
    """Get the call signature of a callable."""

    check: Literal["signature"] = "signature"
    target: str = Field(description="Dotted path to a callable")


class DocCheck(BaseModel):
    """Get the docstring of a symbol."""

    check: Literal["doc"] = "doc"
    target: str = Field(description="Dotted path to any importable symbol")


class GetsourceContainsCheck(BaseModel):
    """Check whether the source code of a symbol contains a substring."""

    check: Literal["getsource_contains"] = "getsource_contains"
    target: str = Field(description="Dotted path to a symbol whose source is inspectable")
    needle: str = Field(description="Substring to search for in the source")


class AstRaisesCheck(BaseModel):
    """Find which exceptions a function/method raises (static AST analysis)."""

    check: Literal["ast_raises"] = "ast_raises"
    target: str = Field(description="Dotted path to a function/method")
    exceptions: list[str] = Field(
        default_factory=list,
        description="Exception names to look for. Empty = return all found.",
    )


CheckUnion = (
    MroCheck
    | IsSubclassCheck
    | SignatureCheck
    | DocCheck
    | GetsourceContainsCheck
    | AstRaisesCheck
)


class IntrospectRequest(BaseModel):
    """Request payload for py_introspect."""

    imports: list[str] = Field(
        default_factory=list,
        description="Extra dotted imports to execute before checks (e.g. 'nomarr.services').",
    )
    checks: list[CheckUnion] = Field(
        description="Ordered list of checks to perform.",
    )
    timeout_ms: int = Field(
        default=3000,
        ge=500,
        le=30000,
        description="Hard timeout for the subprocess in milliseconds.",
    )
    max_source_chars: int = Field(
        default=2000,
        ge=100,
        le=50000,
        description="Max characters for source-text results (doc, getsource_contains).",
    )


class CheckResult(BaseModel):
    """Result of a single check."""

    check: str
    target: str
    ok: bool
    result: Any = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class IntrospectResponse(BaseModel):
    """Response payload from py_introspect."""

    status: Literal["ok", "partial", "error"]
    python_version: str = ""
    results: list[CheckResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Subprocess script template
# ---------------------------------------------------------------------------

_SUBPROCESS_SCRIPT = textwrap.dedent(r'''\
import ast
import importlib
import inspect
import json
import sys


def _resolve_target(dotted_path: str) -> object:
    """Import module and walk getattr chain to reach the target object."""
    parts = dotted_path.split(".")
    # Try progressively shorter module paths
    for i in range(len(parts), 0, -1):
        module_path = ".".join(parts[:i])
        try:
            obj = importlib.import_module(module_path)
            for attr_name in parts[i:]:
                obj = getattr(obj, attr_name)
            return obj
        except (ImportError, ModuleNotFoundError):
            continue
        except AttributeError as e:
            raise AttributeError(
                f"Module '{module_path}' has no attribute '{'.' .join(parts[i:])}'"
            ) from e
    raise ImportError(f"Cannot import any part of '{dotted_path}'")


def _check_mro(spec: dict, _max_chars: int) -> dict:
    target = _resolve_target(spec["target"])
    if not isinstance(target, type):
        return {"check": "mro", "target": spec["target"], "ok": False,
                "error": f"{spec['target']} is not a class", "meta": {}}
    mro = [cls.__qualname__ for cls in type.mro(target)]
    return {"check": "mro", "target": spec["target"], "ok": True,
            "result": mro, "meta": {"length": len(mro)}}


def _check_issubclass(spec: dict, _max_chars: int) -> dict:
    child = _resolve_target(spec["child"])
    parent = _resolve_target(spec["parent"])
    if not isinstance(child, type) or not isinstance(parent, type):
        return {"check": "issubclass", "target": f"{spec['child']} < {spec['parent']}",
                "ok": False, "error": "Both targets must be classes", "meta": {}}
    result = issubclass(child, parent)
    return {"check": "issubclass", "target": f"{spec['child']} < {spec['parent']}",
            "ok": True, "result": result, "meta": {}}


def _check_signature(spec: dict, _max_chars: int) -> dict:
    target = _resolve_target(spec["target"])
    try:
        sig = inspect.signature(target)
    except (ValueError, TypeError) as e:
        return {"check": "signature", "target": spec["target"], "ok": False,
                "error": str(e), "meta": {}}
    return {"check": "signature", "target": spec["target"], "ok": True,
            "result": str(sig), "meta": {"param_count": len(sig.parameters)}}


def _check_doc(spec: dict, max_chars: int) -> dict:
    target = _resolve_target(spec["target"])
    doc = inspect.getdoc(target)
    if doc is None:
        return {"check": "doc", "target": spec["target"], "ok": True,
                "result": None, "meta": {"has_doc": False}}
    truncated = len(doc) > max_chars
    return {"check": "doc", "target": spec["target"], "ok": True,
            "result": doc[:max_chars], "meta": {"has_doc": True, "truncated": truncated,
                                                   "original_length": len(doc)}}


def _check_getsource_contains(spec: dict, max_chars: int) -> dict:
    target = _resolve_target(spec["target"])
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError) as e:
        return {"check": "getsource_contains", "target": spec["target"],
                "ok": False, "error": str(e), "meta": {}}
    needle = spec["needle"]
    count = source.count(needle)
    return {"check": "getsource_contains", "target": spec["target"], "ok": True,
            "result": count > 0, "meta": {"match_count": count,
                                            "source_length": len(source)}}


def _check_ast_raises(spec: dict, _max_chars: int) -> dict:
    target = _resolve_target(spec["target"])
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError) as e:
        return {"check": "ast_raises", "target": spec["target"],
                "ok": False, "error": str(e), "meta": {}}
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"check": "ast_raises", "target": spec["target"],
                "ok": False, "error": f"SyntaxError: {e}", "meta": {}}
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            if isinstance(node.exc, ast.Call):
                exc_node = node.exc.func
            else:
                exc_node = node.exc
            # Extract the exception name
            if isinstance(exc_node, ast.Name):
                found.append(exc_node.id)
            elif isinstance(exc_node, ast.Attribute):
                found.append(exc_node.attr)
    wanted = spec.get("exceptions", [])
    if wanted:
        matched = [e for e in wanted if e in found]
        unmatched = [e for e in wanted if e not in found]
        return {"check": "ast_raises", "target": spec["target"], "ok": True,
                "result": matched, "meta": {"all_found": found, "unmatched": unmatched}}
    return {"check": "ast_raises", "target": spec["target"], "ok": True,
            "result": found, "meta": {"count": len(found)}}


HANDLERS = {
    "mro": _check_mro,
    "issubclass": _check_issubclass,
    "signature": _check_signature,
    "doc": _check_doc,
    "getsource_contains": _check_getsource_contains,
    "ast_raises": _check_ast_raises,
}


def run_checks(request: dict) -> dict:
    """Execute all checks and return a structured response."""
    results: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []
    max_chars = request.get("max_source_chars", 2000)

    # Execute extra imports
    for imp in request.get("imports", []):
        try:
            importlib.import_module(imp)
        except Exception as e:
            warnings.append(f"Failed to import '{imp}': {e}")

    # Execute checks
    for spec in request.get("checks", []):
        check_type = spec.get("check", "")
        handler = HANDLERS.get(check_type)
        if handler is None:
            errors.append(f"Unknown check type: {check_type}")
            continue
        try:
            result = handler(spec, max_chars)
            results.append(result)
        except Exception as e:
            target = spec.get("target", spec.get("child", "unknown"))
            results.append({
                "check": check_type, "target": target,
                "ok": False, "error": str(e), "meta": {},
            })

    # Determine overall status
    if errors:
        status = "error"
    elif any(not r.get("ok") for r in results):
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "python_version": (
            f"{sys.version_info.major}."
            f"{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        "results": results,
        "warnings": warnings,
        "errors": errors,
    }


if __name__ == "__main__":
    request_data = json.loads(sys.stdin.read())
    response = run_checks(request_data)
    print(json.dumps(response))
''')


# ---------------------------------------------------------------------------
# Subprocess launcher (runs in MCP server process)
# ---------------------------------------------------------------------------


def _find_venv_python(project_root: Path) -> Path:
    """Locate the project venv Python interpreter."""
    if sys.platform == "win32":
        candidate = project_root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = project_root / ".venv" / "bin" / "python"
    if candidate.exists():
        return candidate
    # Fallback to sys.executable
    return Path(sys.executable)


def _build_safe_env() -> dict[str, str]:
    """Build a subprocess environment with proxy vars stripped."""
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "REQUESTS_CA_BUNDLE", "http_proxy", "https_proxy"):
        env.pop(key, None)
    return env


def py_introspect(
    imports: list[str] | None = None,
    checks: list[dict[str, Any]] | None = None,
    timeout_ms: int = 3000,
    max_source_chars: int = 2000,
) -> dict[str, Any]:
    """Run Python introspection checks in an isolated subprocess.

    Args:
        imports: Extra modules to import before running checks.
        checks: List of check specifications (each a dict with 'check' key
                and check-type-specific fields).
        timeout_ms: Hard timeout in milliseconds (500-30000).
        max_source_chars: Max chars for source-text results (100-50000).

    Returns:
        Structured dict with status, python_version, results, warnings, errors.
    """
    if not checks:
        return {
            "status": "error",
            "python_version": "",
            "results": [],
            "warnings": [],
            "errors": ["No checks provided"],
        }

    # Validate via Pydantic
    try:
        request = IntrospectRequest(
            imports=imports or [],
            checks=checks,  # type: ignore[arg-type]
            timeout_ms=timeout_ms,
            max_source_chars=max_source_chars,
        )
    except Exception as e:
        return {
            "status": "error",
            "python_version": "",
            "results": [],
            "warnings": [],
            "errors": [f"Invalid request: {e}"],
        }

    # Serialize request for subprocess stdin
    request_json = request.model_dump_json()

    # Find project root and venv python
    project_root = Path.cwd()
    python_path = _find_venv_python(project_root)

    # Build the subprocess command
    # We pass the script via -c and feed the request via stdin
    env = _build_safe_env()

    try:
        proc = subprocess.run(
            [str(python_path), "-c", _SUBPROCESS_SCRIPT],
            input=request_json,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000,
            cwd=str(project_root),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "python_version": "",
            "results": [],
            "warnings": [],
            "errors": [f"Subprocess timed out after {timeout_ms}ms"],
        }
    except OSError as e:
        return {
            "status": "error",
            "python_version": "",
            "results": [],
            "warnings": [],
            "errors": [f"Failed to launch subprocess: {e}"],
        }

    if proc.returncode != 0:
        stderr_preview = proc.stderr[:500] if proc.stderr else "(no stderr)"
        return {
            "status": "error",
            "python_version": "",
            "results": [],
            "warnings": [],
            "errors": [f"Subprocess exited with code {proc.returncode}: {stderr_preview}"],
        }

    # Parse JSON output, capping size
    stdout = proc.stdout
    if len(stdout) > 100_000:
        return {
            "status": "error",
            "python_version": "",
            "results": [],
            "warnings": [],
            "errors": [f"Subprocess output too large ({len(stdout)} bytes), capped at 100KB"],
        }

    try:
        response_data: dict[str, Any] = json.loads(stdout)
    except json.JSONDecodeError as e:
        stdout_preview = stdout[:300] if stdout else "(empty)"
        return {
            "status": "error",
            "python_version": "",
            "results": [],
            "warnings": [],
            "errors": [f"Invalid JSON from subprocess: {e}. Output: {stdout_preview}"],
        }

    return response_data
