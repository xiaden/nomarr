"""Shared infrastructure for static AQL safety tests."""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path

import pytest

_SHARED_PYTEST_MODULE = pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRODUCTION_ROOT = _REPO_ROOT / "nomarr"
_PERSISTENCE_DATABASE_ROOT = _PRODUCTION_ROOT / "persistence" / "database"
_SCRIPTS_ROOT = _REPO_ROOT / "scripts"

_AqlCall = tuple[str, int, str]
_ResolvedAqlCall = tuple[str, int, ast.AST]
_FStringAqlCall = tuple[str, int, ast.JoinedStr]
_BindVarAqlCall = tuple[str, int, ast.AST | None]
_Violation = tuple[str, int, str]
_EdgeInsertViolation = tuple[str, int, str, str]
_InterpolationClassifier = Callable[[ast.AST], bool]
_FStringInterpolation = tuple[str, int, str, str | None]
_INTERPOLATION_PLACEHOLDER = "__INTERPOLATION__"

DOCUMENT_COLLECTIONS = {
    "applied_migrations",
    "calibration_history",
    "calibration_state",
    "file_states",
    "health",
    "libraries",
    "library_files",
    "library_folders",
    "library_pipeline_states",
    "library_scans",
    "locks",
    "meta",
    "ml_capacity_estimates",
    "ml_capacity_probe_locks",
    "ml_model_outputs",
    "ml_models",
    "navidrome_playcounts",
    "navidrome_tracks",
    "segment_scores_stats",
    "sessions",
    "tags",
    "vector_promotion_locks",
    "vram_promises",
    "worker_claims",
    "worker_restart_policy",
}

EDGE_COLLECTIONS = {
    "file_has_state",
    "file_has_segment_stats",
    "file_has_vectors",
    "has_nd_id",
    "has_plays",
    "library_contains_file",
    "library_contains_folder",
    "library_has_pipeline_state",
    "library_has_scan",
    "model_has_calibration",
    "model_has_output",
    "song_has_tags",
    "tag_model_output",
}

_VALID_COLLECTIONS = DOCUMENT_COLLECTIONS | EDGE_COLLECTIONS
_KNOWN_COLLECTION_NAME_SKIPS: set[str] = set()

# Pattern A: LET-read followed by separate write on same collection
_RE_LET_READ = re.compile(
    r"LET\s+\w+.*?FOR\s+\w+\s+IN\s+(@@?\w+|\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_SEPARATE_WRITE = re.compile(
    r"(?:INSERT|UPSERT)\s+.*?\bIN(?:TO)?\s+(@@?\w+|\w+)",
    re.IGNORECASE | re.DOTALL,
)

# Pattern B: FOR-loop iterating collection + body has REMOVE AND INSERT on same collection
_RE_FOR_IN = re.compile(
    r"FOR\s+\w+\s+IN\s+(?!OUTBOUND|INBOUND|ANY|@\w)\s*(@@?\w+|\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_REMOVE_IN = re.compile(
    r"REMOVE\s+.*?\bIN\s+(@@?\w+|\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_INSERT_IN = re.compile(
    r"INSERT\s+.*?\bIN(?:TO)?\s+(@@?\w+|\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_COLLECTION_REFS = re.compile(
    r"(?:"
    r"FOR\s+\w+\s+IN\s+(?!OUTBOUND|INBOUND|ANY|@)"
    r"|INSERT\s+.*?\bIN(?:TO)?\s+"
    r"|UPSERT\s+.*?\bIN(?:TO)?\s+"
    r"|REMOVE\s+.*?\bIN\s+"
    r"|(?:OUTBOUND|INBOUND|ANY)\s+(?:@\w+\s+)?"
    r")"
    r"((?!@)\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_DYNAMIC_COLLECTION = re.compile(r"^vectors_track_(hot|cold)__")
_RE_INSERT_EDGE = re.compile(
    r"INSERT\s+\{([^}]+)\}\s+IN(?:TO)?\s+(\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_AQL_LOCAL_SYMBOLS = re.compile(
    r"(?:FOR\s+(\w+)(?:\s*,\s*(\w+))?\s+IN|LET\s+(\w+)\s*=|COLLECT\s+(\w+)\s*=)",
    re.IGNORECASE,
)
_RE_AQL_LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)


def _is_name_with_id(node: ast.AST, *names: str) -> bool:
    """Return True when the AST node is a Name matching one of the ids."""
    return isinstance(node, ast.Name) and node.id in names


def _contains_if_expression(node: ast.AST) -> bool:
    """Return True when the AST node contains a ternary conditional."""
    return any(isinstance(child, ast.IfExp) for child in ast.walk(node))


def _is_collection_name_interpolation(node: ast.AST) -> bool:
    """Return True for safe dynamic vector collection name expressions."""
    return _is_name_with_id(node, "collection_name") or (
        isinstance(node, ast.Attribute) and node.attr == "collection_name"
    )


def _is_integer_param_interpolation(node: ast.AST) -> bool:
    """Return True for known numeric interpolation parameters."""
    return _is_name_with_id(node, "nprobe", "limit")


def _is_limit_clause_interpolation(node: ast.AST) -> bool:
    """Return True for validated LIMIT-clause fragments."""
    return _is_name_with_id(node, "limit_clause")


def _is_sort_clause_interpolation(node: ast.AST) -> bool:
    """Return True for validated SORT-clause fragments."""
    return _is_name_with_id(node, "sort_clause")


def _is_filter_clause_interpolation(node: ast.AST) -> bool:
    """Return True for validated FILTER-clause fragments."""
    return _is_name_with_id(
        node,
        "filter_clause",
        "filter_block",
        "library_filter",
        "library_filter_clause",
    )


def _is_field_assignments_interpolation(node: ast.AST) -> bool:
    """Return True for validated field assignment fragments."""
    return _is_name_with_id(node, "field_assignments")


def _is_conditional_fragment_interpolation(node: ast.AST) -> bool:
    """Return True for hardcoded conditional AQL fragments."""
    return _contains_if_expression(node)


def _is_operator_interpolation(node: ast.AST) -> bool:
    """Return True for closed-set operator variables."""
    return _is_name_with_id(node, "op")


SAFE_FSTRING_INTERPOLATION_TAXONOMY: dict[str, _InterpolationClassifier] = {
    "collection_name": _is_collection_name_interpolation,
    "integer_param": _is_integer_param_interpolation,
    "limit_clause": _is_limit_clause_interpolation,
    "sort_clause": _is_sort_clause_interpolation,
    "filter_clause": _is_filter_clause_interpolation,
    "field_assignments": _is_field_assignments_interpolation,
    "conditional_fragment": _is_conditional_fragment_interpolation,
    "operator": _is_operator_interpolation,
}


def _extract_string_literal(
    node: ast.AST,
    interpolation_placeholder: str | None = None,
) -> str | None:
    """Return a static string value when the AST node can be resolved safely."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _extract_string_literal(
            node.left,
            interpolation_placeholder=interpolation_placeholder,
        )
        right = _extract_string_literal(
            node.right,
            interpolation_placeholder=interpolation_placeholder,
        )
        if left is None or right is None:
            return None
        return left + right

    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                if interpolation_placeholder is None:
                    return None

                parts.append(interpolation_placeholder)
                continue

            text = _extract_string_literal(
                value,
                interpolation_placeholder=interpolation_placeholder,
            )
            if text is None:
                return None
            parts.append(text)

        return "".join(parts)

    return None


def _is_aql_execute_call(node: ast.Call) -> bool:
    """Return True when the call target is an `.aql.execute(...)` invocation."""
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "execute"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "aql"
    )


class _AqlExecuteVisitor(ast.NodeVisitor):
    """Collect statically analyzable AQL strings passed to `aql.execute()`."""

    def __init__(self, file_path: Path, repo_root: Path) -> None:
        self._display_path = file_path.relative_to(repo_root).as_posix()
        self.calls: list[_AqlCall] = []
        self.resolved_calls: list[_ResolvedAqlCall] = []
        self.bind_var_calls: list[_BindVarAqlCall] = []
        self._local_assignments_stack: list[dict[str, ast.AST]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_body(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_body(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_assignment(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._record_assignment([node.target], node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_aql_execute_call(node) and node.args:
            resolved_node = self._resolve_query_node(node.args[0])
            if resolved_node is not None:
                self.resolved_calls.append((self._display_path, node.lineno, resolved_node))

            bind_vars_node = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "bind_vars"),
                None,
            )
            resolved_bind_vars_node = self._resolve_query_node(bind_vars_node) if bind_vars_node is not None else None
            self.bind_var_calls.append((self._display_path, node.lineno, resolved_bind_vars_node))

            aql_string = _extract_string_literal(node.args[0])
            if aql_string is None and resolved_node is not None:
                aql_string = _extract_string_literal(resolved_node)
            if aql_string is not None:
                self.calls.append((self._display_path, node.lineno, aql_string))

        self.generic_visit(node)

    def _visit_function_body(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self._local_assignments_stack.append({})
        self.generic_visit(node)
        self._local_assignments_stack.pop()

    def _record_assignment(self, targets: list[ast.expr], value: ast.AST) -> None:
        if not self._local_assignments_stack:
            return

        current_assignments = self._local_assignments_stack[-1]
        for target in targets:
            if isinstance(target, ast.Name):
                current_assignments[target.id] = value

    def _resolve_query_node(self, node: ast.AST) -> ast.AST | None:
        if not isinstance(node, ast.Name) or not self._local_assignments_stack:
            return node

        current_assignments = self._local_assignments_stack[-1]
        seen_names: set[str] = set()
        resolved_node: ast.AST = node

        while isinstance(resolved_node, ast.Name):
            if resolved_node.id in seen_names:
                return None

            seen_names.add(resolved_node.id)
            next_node = current_assignments.get(resolved_node.id)
            if next_node is None:
                return None
            resolved_node = next_node

        return resolved_node


class _FStringAqlVisitor(ast.NodeVisitor):
    """Collect formatted values from a resolved AQL f-string and classify them."""

    def __init__(self, file_path: str, line_number: int) -> None:
        self._file_path = file_path
        self._line_number = line_number
        self.interpolations: list[_FStringInterpolation] = []

    def visit_FormattedValue(self, node: ast.FormattedValue) -> None:
        pattern_id = self._classify(node.value)
        expression = ast.unparse(node.value)
        self.interpolations.append((self._file_path, self._line_number, expression, pattern_id))
        self.generic_visit(node)

    @staticmethod
    def _classify(node: ast.AST) -> str | None:
        for pattern_id, classifier in SAFE_FSTRING_INTERPOLATION_TAXONOMY.items():
            if classifier(node):
                return pattern_id
        return None


def _find_aql_execute_calls(file_path: Path, repo_root: Path) -> list[_AqlCall]:
    """Return `(file_path, line_number, aql_string)` tuples for a Python file."""
    module = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    visitor = _AqlExecuteVisitor(file_path=file_path, repo_root=repo_root)
    visitor.visit(module)
    return visitor.calls


def _find_resolved_aql_execute_calls(
    file_path: Path,
    repo_root: Path,
) -> list[_ResolvedAqlCall]:
    """Return `(file_path, line_number, query_node)` tuples for resolvable calls."""
    module = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    visitor = _AqlExecuteVisitor(file_path=file_path, repo_root=repo_root)
    visitor.visit(module)
    return visitor.resolved_calls


def _find_bind_var_aql_calls(
    file_path: Path,
    repo_root: Path,
) -> list[_BindVarAqlCall]:
    """Return `(file_path, line_number, bind_vars_node)` tuples for execute calls."""
    module = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    visitor = _AqlExecuteVisitor(file_path=file_path, repo_root=repo_root)
    visitor.visit(module)
    return visitor.bind_var_calls


def _scan_aql_execute_calls(root: Path, repo_root: Path = _REPO_ROOT) -> list[_AqlCall]:
    """Walk a Python tree and collect statically analyzable `aql.execute()` calls."""
    if not root.exists():
        return []

    calls: list[_AqlCall] = []
    for file_path in sorted(root.rglob("*.py")):
        calls.extend(_find_aql_execute_calls(file_path=file_path, repo_root=repo_root))
    return calls


def _find_fstring_aql_calls(
    root: Path = _PRODUCTION_ROOT,
    repo_root: Path = _REPO_ROOT,
) -> list[_FStringAqlCall]:
    """Return every resolvable `aql.execute()` whose query is an f-string."""
    if not root.exists():
        return []

    calls: list[_FStringAqlCall] = []
    for file_path in sorted(root.rglob("*.py")):
        for display_path, line_number, query_node in _find_resolved_aql_execute_calls(
            file_path=file_path,
            repo_root=repo_root,
        ):
            if isinstance(query_node, ast.JoinedStr):
                calls.append((display_path, line_number, query_node))

    return calls


def _scan_all_aql_strings(
    root: Path,
    repo_root: Path = _REPO_ROOT,
) -> list[_AqlCall]:
    """Return all resolvable AQL strings, normalizing f-strings with placeholders."""
    if not root.exists():
        return []

    calls: list[_AqlCall] = []
    for file_path in sorted(root.rglob("*.py")):
        for display_path, line_number, query_node in _find_resolved_aql_execute_calls(
            file_path=file_path,
            repo_root=repo_root,
        ):
            aql_string = _extract_string_literal(
                query_node,
                interpolation_placeholder=_INTERPOLATION_PLACEHOLDER,
            )
            if aql_string is not None:
                calls.append((display_path, line_number, aql_string))

    return calls


def _extract_aql_local_symbols(aql: str) -> set[str]:
    """Return AQL local variable names introduced by FOR/LET/COLLECT clauses."""
    symbols: set[str] = set()
    for match in _RE_AQL_LOCAL_SYMBOLS.finditer(aql):
        symbols.update(group.lower() for group in match.groups() if group is not None)
    return symbols


def _strip_aql_comments(aql: str) -> str:
    """Remove `// ...` comments so regex scans only executable AQL."""
    return _RE_AQL_LINE_COMMENT.sub("", aql)


def _extract_traversal_collection_name(aql: str, match: re.Match[str]) -> str | None:
    """Return the edge collection token following a traversal vertex expression."""
    if not any(keyword in match.group(0).upper() for keyword in ("OUTBOUND", "INBOUND", "ANY")):
        return None

    remainder = aql[match.end() :]
    next_token_match = re.match(r"(?:\.\w+)?\s+(@@?\w+|\w+)", remainder)
    if next_token_match is None:
        return None

    return next_token_match.group(1)


def _extract_collection_references(aql: str) -> list[str]:
    """Extract collection names from AQL while skipping local symbols and helpers."""
    query = _strip_aql_comments(aql)
    local_symbols = _extract_aql_local_symbols(query)
    collection_names: list[str] = []

    for match in _RE_COLLECTION_REFS.finditer(query):
        candidate = match.group(1)
        normalized_candidate = candidate.lower()

        if (
            candidate.startswith("@")
            or normalized_candidate == _INTERPOLATION_PLACEHOLDER.lower()
            or candidate != normalized_candidate
            or candidate[:1].isdigit()
            or normalized_candidate in local_symbols
            or normalized_candidate in _KNOWN_COLLECTION_NAME_SKIPS
        ):
            traversal_candidate = _extract_traversal_collection_name(query, match)
            if traversal_candidate is None:
                continue
            candidate = traversal_candidate
            normalized_candidate = candidate.lower()

        if candidate.startswith("@"):
            continue
        if normalized_candidate == _INTERPOLATION_PLACEHOLDER.lower():
            continue
        if candidate != normalized_candidate or candidate[:1].isdigit():
            continue
        if normalized_candidate in local_symbols or normalized_candidate in _KNOWN_COLLECTION_NAME_SKIPS:
            continue

        collection_names.append(candidate)

    return collection_names


def _unwrap_cast(node: ast.AST | None) -> ast.AST | None:
    """Return the underlying AST node when wrapped in `cast(...)`."""
    current = node
    while (
        isinstance(current, ast.Call)
        and isinstance(current.func, ast.Name)
        and current.func.id == "cast"
        and len(current.args) >= 2
    ):
        current = current.args[1]
    return current


def _resolve_module_string_literal(
    node: ast.AST | None,
    module_constants: dict[str, str],
) -> str | None:
    """Resolve a module-level string literal or constant reference."""
    unwrapped = _unwrap_cast(node)
    if unwrapped is None:
        return None

    literal = _extract_string_literal(unwrapped)
    if literal is not None:
        return literal

    if isinstance(unwrapped, ast.Name):
        return module_constants.get(unwrapped.id)

    return None


def _extract_module_string_constants(module: ast.Module) -> dict[str, str]:
    """Collect module-level string constants from simple assignments."""
    constants: dict[str, str] = {}
    for statement in module.body:
        targets: list[ast.expr] = []
        value: ast.AST | None = None

        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
            value = statement.value

        if value is None:
            continue

        resolved_value = _resolve_module_string_literal(value, constants)
        if resolved_value is None:
            continue

        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = resolved_value

    return constants


def _extract_bind_var_collection_names(
    bind_vars_node: ast.AST | None,
    module_constants: dict[str, str],
) -> list[str]:
    """Return resolved collection names from bind vars like `{"@collection": NAME}`."""
    bind_vars_dict = _unwrap_cast(bind_vars_node)
    if not isinstance(bind_vars_dict, ast.Dict):
        return []

    collection_names: list[str] = []
    for key_node, value_node in zip(bind_vars_dict.keys, bind_vars_dict.values, strict=True):
        key = _resolve_module_string_literal(key_node, module_constants)
        if key is None or not key.startswith("@"):
            continue

        collection_name = _resolve_module_string_literal(value_node, module_constants)
        if collection_name is not None:
            collection_names.append(collection_name)

    return collection_names


def _find_read_write_conflicts(aql: str) -> set[str]:
    """Return collection names involved in unsafe read+write patterns."""
    conflicts: set[str] = set()

    # Pattern A: LET-read + separate write on same collection
    let_read_colls = {m.group(1).lower() for m in _RE_LET_READ.finditer(aql)}
    separate_write_colls = {m.group(1).lower() for m in _RE_SEPARATE_WRITE.finditer(aql)}
    conflicts |= let_read_colls & separate_write_colls

    # Pattern B: FOR-loop iterating collection + body has REMOVE AND INSERT on it
    for_colls = {m.group(1).lower() for m in _RE_FOR_IN.finditer(aql)}
    remove_colls = {m.group(1).lower() for m in _RE_REMOVE_IN.finditer(aql)}
    # Strip UPSERT blocks before checking for standalone INSERTs — the INSERT
    # branch inside UPSERT is atomic (not a separate write) and must not trigger
    # Pattern B.
    aql_for_insert_check = re.sub(
        r"\bUPSERT\b.*?\bIN(?:TO)?\s+\w+",
        "",
        aql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    insert_colls = {m.group(1).lower() for m in _RE_INSERT_IN.finditer(aql_for_insert_check)}
    for coll in for_colls:
        if coll in remove_colls and coll in insert_colls:
            conflicts.add(coll)

    return conflicts


def _find_violations(root: Path) -> list[_Violation]:
    """Return sorted `(file_path, line_number, collection)` violations under a tree."""
    violations: list[_Violation] = []
    for file_path, line_number, aql in _scan_aql_execute_calls(root):
        violations.extend(
            (file_path, line_number, collection) for collection in sorted(_find_read_write_conflicts(aql))
        )

    return sorted(violations)


def _format_violations(violations: list[_Violation]) -> str:
    """Return a human-readable failure message for conflict violations."""
    lines = ["Mixed read/write AQL conflicts found:"]
    lines.extend(f"- {file_path}:{line_number} -> {collection}" for file_path, line_number, collection in violations)
    return "\n".join(lines)


def _find_fstring_interpolation_violations(
    root: Path = _PERSISTENCE_DATABASE_ROOT,
) -> tuple[int, list[_Violation]]:
    """Return the f-string call count and any unsafe interpolation violations."""
    violations: list[_Violation] = []
    fstring_calls = _find_fstring_aql_calls(root)

    for file_path, line_number, query_node in fstring_calls:
        visitor = _FStringAqlVisitor(file_path=file_path, line_number=line_number)
        visitor.visit(query_node)
        violations.extend(
            (interpolation_file, interpolation_line, expression)
            for interpolation_file, interpolation_line, expression, pattern_id in visitor.interpolations
            if pattern_id is None
        )

    return len(fstring_calls), sorted(violations)


def _format_fstring_interpolation_violations(
    site_count: int,
    violations: list[_Violation],
) -> str:
    """Return a human-readable failure message for unsafe f-string AQL pieces."""
    lines = [
        f"Unsafe AQL f-string interpolations found across {site_count} f-string sites:",
    ]
    lines.extend(f"- {file_path}:{line_number} -> {expression}" for file_path, line_number, expression in violations)
    return "\n".join(lines)


def _format_collection_name_violations(violations: list[_Violation]) -> str:
    """Return a human-readable failure message for invalid collection names."""
    lines = ["Invalid AQL collection names found:"]
    lines.extend(f"- {file_path}:{line_number} -> {collection}" for file_path, line_number, collection in violations)
    return "\n".join(lines)


def _find_edge_insert_violations(
    root: Path = _PERSISTENCE_DATABASE_ROOT,
) -> list[_EdgeInsertViolation]:
    """Return edge INSERT or UPSERT-INSERT documents missing `_from` or `_to`."""
    violations: list[_EdgeInsertViolation] = []

    for file_path, line_number, aql in _scan_all_aql_strings(root):
        for match in _RE_INSERT_EDGE.finditer(aql):
            document_literal, collection_name = match.groups()
            normalized_collection_name = collection_name.lower()
            if normalized_collection_name not in EDGE_COLLECTIONS:
                continue

            missing_keys: list[str] = []
            if re.search(r"(?<!\w)_from\s*:", document_literal) is None:
                missing_keys.append("_from")
            if re.search(r"(?<!\w)_to\s*:", document_literal) is None:
                missing_keys.append("_to")

            if missing_keys:
                violations.append(
                    (
                        file_path,
                        line_number,
                        collection_name,
                        ", ".join(missing_keys),
                    )
                )

    return sorted(violations)


def _format_edge_insert_violations(violations: list[_EdgeInsertViolation]) -> str:
    """Return a human-readable failure message for incomplete edge INSERTs."""
    lines = ["Edge INSERT/UPSERT statements missing required `_from`/`_to` keys:"]
    lines.extend(
        f"- {file_path}:{line_number} -> {collection} missing {missing_keys}"
        for file_path, line_number, collection, missing_keys in violations
    )
    return "\n".join(lines)
