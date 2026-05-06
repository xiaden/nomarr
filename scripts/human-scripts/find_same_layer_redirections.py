#!/usr/bin/env python3
"""Find simple same-layer redirection wrappers.

This script looks for functions and methods that do little more than call other
code in the same Nomarr application layer and return the result unchanged.

It is intentionally conservative:

- only single-statement wrappers are reported
- arguments must be forwarded directly from the wrapper parameters
- the target call must resolve to the same layer as the caller

That makes the results better suited for a simplification pass than a broad AST
grep, while still remaining static and fast.

Examples:
    python scripts/human-scripts/find_same_layer_redirections.py
    python scripts/human-scripts/find_same_layer_redirections.py --layers services workflows
    python scripts/human-scripts/find_same_layer_redirections.py --format json
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

LAYER_ROOT = "nomarr"
SUPPORTED_LAYERS = (
    "interfaces",
    "services",
    "workflows",
    "components",
    "persistence",
    "helpers",
)
DEFAULT_LAYERS = ("interfaces", "services", "workflows", "components")


@dataclass(slots=True)
class ImportBinding:
    """Resolved import binding for a local name."""

    target: str
    kind: Literal["module", "symbol"]


@dataclass(slots=True)
class ClassInfo:
    """Minimal class metadata for redirection resolution."""

    name: str
    methods: set[str] = field(default_factory=set)
    self_attr_types: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ModuleInfo:
    """Static metadata extracted from a module."""

    module: str
    path: Path
    layer: str | None
    imports: dict[str, ImportBinding] = field(default_factory=dict)
    top_level_functions: set[str] = field(default_factory=set)
    top_level_classes: set[str] = field(default_factory=set)
    classes: dict[str, ClassInfo] = field(default_factory=dict)


@dataclass(slots=True)
class Candidate:
    """A same-layer wrapper candidate."""

    layer: str
    file: str
    line: int
    symbol: str
    call: str
    resolved_target: str | None
    resolution_kind: str
    forwarded_params: list[str]
    confidence: Literal["high", "medium"]
    reason: str


def extract_layer(module_path: str | None) -> str | None:
    """Extract the Nomarr architecture layer from a module path."""

    if not module_path or not module_path.startswith(f"{LAYER_ROOT}."):
        return None

    parts = module_path.split(".")
    if len(parts) < 2:
        return None

    layer = parts[1]
    if layer in SUPPORTED_LAYERS:
        return layer
    return None


def path_to_module(path: Path, repo_root: Path) -> str | None:
    """Convert a Python file path to a module path."""

    try:
        rel_path = path.relative_to(repo_root)
    except ValueError:
        return None

    if rel_path.suffix != ".py":
        return None

    module_parts = list(rel_path.with_suffix("").parts)
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    return ".".join(module_parts)


def resolve_relative_module(current_module: str, level: int, imported_module: str | None) -> str:
    """Resolve an absolute module path for a relative import."""

    package_parts = current_module.split(".")[:-1]
    if level > len(package_parts):
        return imported_module or ""

    base_parts = package_parts[: len(package_parts) - level + 1]
    if imported_module:
        base_parts.extend(imported_module.split("."))
    return ".".join(part for part in base_parts if part)


def build_imports(tree: ast.AST, module: str) -> dict[str, ImportBinding]:
    """Build a map of local import names to resolved targets."""

    bindings: dict[str, ImportBinding] = {}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[-1]
                bindings[local_name] = ImportBinding(target=alias.name, kind="module")
        elif isinstance(node, ast.ImportFrom):
            base_module = node.module or ""
            if node.level:
                base_module = resolve_relative_module(module, node.level, node.module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                target = f"{base_module}.{alias.name}" if base_module else alias.name
                bindings[local_name] = ImportBinding(target=target, kind="symbol")

    return bindings


def iter_nomarr_annotation_paths(
    node: ast.AST | None,
    imports: dict[str, ImportBinding],
    module: str,
    local_classes: set[str],
) -> list[str]:
    """Extract possible Nomarr type paths from an annotation node."""

    if node is None:
        return []

    if isinstance(node, ast.Name):
        if node.id in imports:
            return [imports[node.id].target]
        if node.id in local_classes:
            return [f"{module}.{node.id}"]
        return []

    if isinstance(node, ast.Attribute):
        base = dotted_name(node)
        if base is None:
            return []
        head = base.split(".", 1)[0]
        if head in imports and imports[head].kind == "module":
            suffix = base[len(head) + 1 :]
            return [f"{imports[head].target}.{suffix}"]
        if base.startswith(f"{LAYER_ROOT}."):
            return [base]
        return []

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value] if node.value.startswith(f"{LAYER_ROOT}.") else []

    if isinstance(node, ast.Subscript):
        return iter_nomarr_annotation_paths(node.value, imports, module, local_classes) + iter_nomarr_annotation_paths(
            node.slice,
            imports,
            module,
            local_classes,
        )

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return iter_nomarr_annotation_paths(node.left, imports, module, local_classes) + iter_nomarr_annotation_paths(
            node.right,
            imports,
            module,
            local_classes,
        )

    if isinstance(node, ast.Tuple):
        results: list[str] = []
        for elt in node.elts:
            results.extend(iter_nomarr_annotation_paths(elt, imports, module, local_classes))
        return results

    return []


def build_class_info(class_node: ast.ClassDef, module_info: ModuleInfo) -> ClassInfo:
    """Collect class methods and obvious injected self-attribute types."""

    class_info = ClassInfo(name=class_node.name)
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            class_info.methods.add(node.name)

    init_method = next(
        (
            node
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__init__"
        ),
        None,
    )
    if init_method is None:
        return class_info

    param_types: dict[str, str] = {}
    positional_args = list(init_method.args.posonlyargs) + list(init_method.args.args)
    for arg in positional_args:
        if arg.arg in {"self", "cls"}:
            continue
        paths = iter_nomarr_annotation_paths(
            arg.annotation,
            module_info.imports,
            module_info.module,
            module_info.top_level_classes,
        )
        resolved = next((path for path in paths if extract_layer(path)), None)
        if resolved:
            param_types[arg.arg] = resolved

    for stmt in init_method.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Attribute):
            continue
        if not isinstance(target.value, ast.Name) or target.value.id != "self":
            continue
        if not isinstance(stmt.value, ast.Name):
            continue
        resolved_type = param_types.get(stmt.value.id)
        if resolved_type:
            class_info.self_attr_types[target.attr] = resolved_type

    return class_info


def parse_module(path: Path, repo_root: Path) -> ModuleInfo | None:
    """Parse a Python module into static metadata."""

    module = path_to_module(path, repo_root)
    if module is None:
        return None

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"warning: failed to read {path}: {exc}", file=sys.stderr)
        return None

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        print(f"warning: failed to parse {path}: {exc}", file=sys.stderr)
        return None

    module_info = ModuleInfo(module=module, path=path, layer=extract_layer(module))
    module_info.imports = build_imports(tree, module)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_info.top_level_functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            module_info.top_level_classes.add(node.name)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            module_info.classes[node.name] = build_class_info(node, module_info)

    return module_info


def iter_target_files(repo_root: Path, layers: set[str]) -> list[Path]:
    """List Python files inside selected Nomarr layers."""

    files: list[Path] = []
    for layer in sorted(layers):
        layer_root = repo_root / LAYER_ROOT / layer
        if not layer_root.exists():
            continue
        for path in sorted(layer_root.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            files.append(path)
    return files


def strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """Remove a leading docstring expression from a statement list."""

    if not body:
        return body
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return body


def dotted_name(node: ast.AST) -> str | None:
    """Return dotted name text for simple Name/Attribute chains."""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def forwarded_param_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect the wrapper's forwardable parameter names."""

    names = {arg.arg for arg in func_node.args.posonlyargs}
    names.update(arg.arg for arg in func_node.args.args)
    names.update(arg.arg for arg in func_node.args.kwonlyargs)

    if func_node.args.vararg is not None:
        names.add(func_node.args.vararg.arg)
    if func_node.args.kwarg is not None:
        names.add(func_node.args.kwarg.arg)

    names.discard("self")
    names.discard("cls")
    return names


def unwrap_forwarded_call(
    stmt: ast.stmt,
) -> tuple[ast.Call, Literal["return", "await-return", "expr", "await-expr"]] | None:
    """Extract a call if the statement is a bare wrapper."""

    if isinstance(stmt, ast.Return):
        if isinstance(stmt.value, ast.Call):
            return stmt.value, "return"
        if isinstance(stmt.value, ast.Await) and isinstance(stmt.value.value, ast.Call):
            return stmt.value.value, "await-return"
        return None

    if isinstance(stmt, ast.Expr):
        if isinstance(stmt.value, ast.Call):
            return stmt.value, "expr"
        if isinstance(stmt.value, ast.Await) and isinstance(stmt.value.value, ast.Call):
            return stmt.value.value, "await-expr"
        return None

    return None


def args_are_passthrough(call: ast.Call, allowed_names: set[str]) -> tuple[bool, list[str]]:
    """Check whether a call forwards wrapper params directly."""

    forwarded: list[str] = []

    for arg in call.args:
        if isinstance(arg, ast.Name) and arg.id in allowed_names:
            forwarded.append(arg.id)
            continue
        if isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name) and arg.value.id in allowed_names:
            forwarded.append(f"*{arg.value.id}")
            continue
        return False, []

    for keyword in call.keywords:
        if keyword.arg is None:
            if isinstance(keyword.value, ast.Name) and keyword.value.id in allowed_names:
                forwarded.append(f"**{keyword.value.id}")
                continue
            return False, []
        if isinstance(keyword.value, ast.Name) and keyword.value.id in allowed_names:
            forwarded.append(keyword.arg)
            continue
        return False, []

    return True, forwarded


def resolve_call_target(
    call: ast.Call,
    module_info: ModuleInfo,
    class_info: ClassInfo | None,
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str | None, str, Literal["high", "medium"]]:
    """Resolve a call target to a best-effort symbol path and confidence."""

    func_expr = call.func

    if isinstance(func_expr, ast.Name):
        local_name = func_expr.id
        if local_name in module_info.top_level_classes or local_name[:1].isupper():
            return None, "constructor-or-class-call", "high"
        if local_name in module_info.top_level_functions:
            return f"{module_info.module}.{local_name}", "local-function", "high"
        binding = module_info.imports.get(local_name)
        if binding and binding.kind == "symbol":
            if local_name[:1].isupper():
                return None, "constructor-or-class-call", "high"
            return binding.target, "imported-symbol", "high"
        return None, "unresolved-name", "medium"

    if not isinstance(func_expr, ast.Attribute):
        return None, "unsupported-call-shape", "medium"

    owner = func_expr.value
    if isinstance(owner, ast.Name) and owner.id in {"self", "cls"}:
        if class_info and func_expr.attr in class_info.methods:
            return f"{module_info.module}.{class_info.name}.{func_expr.attr}", "same-class-method", "high"
        return None, "unresolved-self-call", "medium"

    if isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name) and owner.value.id == "self":
        if class_info:
            owner_type = class_info.self_attr_types.get(owner.attr)
            if owner_type:
                return f"{owner_type}.{func_expr.attr}", "injected-same-layer-attr", "high"
        return None, "unresolved-self-attr", "medium"

    if isinstance(owner, ast.Name):
        binding = module_info.imports.get(owner.id)
        if binding and binding.kind == "module":
            return f"{binding.target}.{func_expr.attr}", "imported-module-attr", "high"

        param_names = forwarded_param_names(func_node)
        if owner.id in param_names:
            arg_node = next(
                (arg for arg in list(func_node.args.posonlyargs) + list(func_node.args.args) if arg.arg == owner.id),
                None,
            )
            if arg_node:
                annotation_paths = iter_nomarr_annotation_paths(
                    arg_node.annotation,
                    module_info.imports,
                    module_info.module,
                    module_info.top_level_classes,
                )
                resolved = next((path for path in annotation_paths if extract_layer(path)), None)
                if resolved:
                    return f"{resolved}.{func_expr.attr}", "typed-param-attr", "medium"

    owner_name = dotted_name(owner)
    if owner_name and owner_name.startswith(f"{LAYER_ROOT}."):
        return f"{owner_name}.{func_expr.attr}", "absolute-attr", "high"

    return None, "unresolved-attribute", "medium"


def iter_callables(tree: ast.Module) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str | None]]:
    """Yield top-level functions and class methods with class name context."""

    items: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str | None]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            items.append((node, None))
        elif isinstance(node, ast.ClassDef):
            items.extend(
                (child, node.name) for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return items


def analyze_file(path: Path, repo_root: Path, module_info: ModuleInfo) -> list[Candidate]:
    """Analyze a single file and return same-layer wrapper candidates."""

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    candidates: list[Candidate] = []

    if module_info.layer is None:
        return candidates

    for func_node, class_name in iter_callables(tree):
        if func_node.name == "__init__":
            continue

        body = strip_docstring(func_node.body)
        if len(body) != 1:
            continue

        call_info = unwrap_forwarded_call(body[0])
        if call_info is None:
            continue

        call, wrapper_kind = call_info
        is_passthrough, forwarded = args_are_passthrough(call, forwarded_param_names(func_node))
        if not is_passthrough:
            continue

        class_info = module_info.classes.get(class_name) if class_name else None
        resolved_target, resolution_kind, confidence = resolve_call_target(call, module_info, class_info, func_node)
        target_layer = extract_layer(resolved_target)
        if target_layer != module_info.layer:
            continue

        symbol = f"{module_info.module}.{func_node.name}"
        if class_name:
            symbol = f"{module_info.module}.{class_name}.{func_node.name}"

        try:
            call_text = ast.unparse(call)
        except Exception:
            call_text = "<unparse failed>"

        reason = f"single {wrapper_kind} wrapper with direct param pass-through to same-layer target"
        candidates.append(
            Candidate(
                layer=module_info.layer,
                file=str(path.relative_to(repo_root)),
                line=func_node.lineno,
                symbol=symbol,
                call=call_text,
                resolved_target=resolved_target,
                resolution_kind=resolution_kind,
                forwarded_params=forwarded,
                confidence=confidence,
                reason=reason,
            )
        )

    return candidates


def collect_candidates(repo_root: Path, layers: set[str]) -> list[Candidate]:
    """Scan selected layers and collect same-layer wrapper candidates."""

    candidates: list[Candidate] = []
    for path in iter_target_files(repo_root, layers):
        module_info = parse_module(path, repo_root)
        if module_info is None:
            continue
        file_candidates = analyze_file(path, repo_root, module_info)
        candidates.extend(file_candidates)
    return sorted(candidates, key=lambda item: (item.layer, item.file, item.line, item.symbol))


def format_text(candidates: list[Candidate]) -> str:
    """Render human-readable output."""

    if not candidates:
        return "No same-layer redirection candidates found."

    lines = [f"Found {len(candidates)} same-layer redirection candidate(s).", ""]
    current_layer: str | None = None

    for candidate in candidates:
        if candidate.layer != current_layer:
            current_layer = candidate.layer
            lines.append(f"[{current_layer}]")

        lines.append(
            "- "
            f"{candidate.file}:{candidate.line} {candidate.symbol} -> {candidate.call} "
            f"[target={candidate.resolved_target or 'unresolved'}, resolution={candidate.resolution_kind}, "
            f"confidence={candidate.confidence}]"
        )

    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root (defaults to the current Nomarr repo root).",
    )
    parser.add_argument(
        "--layers",
        nargs="+",
        choices=SUPPORTED_LAYERS,
        default=list(DEFAULT_LAYERS),
        help="Nomarr layers to scan.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    args = parse_args(argv or sys.argv[1:])
    repo_root = args.repo_root.resolve()
    layers = set(args.layers)

    candidates = collect_candidates(repo_root, layers)

    if args.format == "json":
        payload: dict[str, Any] = {
            "repo_root": str(repo_root),
            "layers": sorted(layers),
            "count": len(candidates),
            "candidates": [asdict(candidate) for candidate in candidates],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_text(candidates))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
