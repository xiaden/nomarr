"""AST parsing and dataclass discovery across the codebase."""

import ast
import sys
from pathlib import Path

from .config import is_ignored_module, resolve_domain, resolve_layer
from .model import DataclassInfo, ImportEdge, MissingDataclassCandidate


def find_dataclass_definitions(file_path: Path) -> list[tuple[str, int]]:
    """Parse a Python file and find all @dataclass definitions.

    Args:
        file_path: Path to Python file

    Returns:
        List of (class_name, line_number) tuples for each dataclass found

    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
        return []

    dataclasses = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if class has @dataclass decorator
        is_dataclass = False
        for decorator in node.decorator_list:
            # Handle @dataclass
            if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
                is_dataclass = True
                break
            # Handle @dataclasses.dataclass
            if isinstance(decorator, ast.Attribute) and decorator.attr == "dataclass":
                is_dataclass = True
                break

        if is_dataclass:
            dataclasses.append((node.name, node.lineno))

    return dataclasses


def path_to_module(file_path: Path, project_root: Path) -> str:
    """Convert file path to Python module path.

    Args:
        file_path: Absolute path to Python file
        project_root: Root directory of the project

    Returns:
        Module path (e.g., "nomarr.helpers.dto.navidrome")

    """
    try:
        rel_path = file_path.relative_to(project_root)
    except ValueError:
        return str(file_path)

    # Remove .py extension and convert path separators to dots
    module_parts = rel_path.with_suffix("").parts
    module_path = ".".join(module_parts)

    # Remove __init__ if present
    module_path = module_path.removesuffix(".__init__")

    return module_path


def discover_all_dataclasses(
    project_root: Path,
    search_paths: list[Path],
    layer_map: dict[str, str],
    domain_map: dict[str, str],
    ignore_prefixes: list[str],
) -> list[DataclassInfo]:
    """Walk the codebase and discover all @dataclass definitions.

    Args:
        project_root: Root directory of the project
        search_paths: List of directory paths to search
        layer_map: Mapping of module prefixes to layer names
        domain_map: Mapping of module prefixes to domain names
        ignore_prefixes: List of module prefixes to ignore

    Returns:
        List of DataclassInfo objects

    """
    dataclasses: list[DataclassInfo] = []

    for search_dir in search_paths:
        if not search_dir.exists():
            continue

        for py_file in search_dir.rglob("*.py"):
            definitions = find_dataclass_definitions(py_file)
            module_path = path_to_module(py_file, project_root)

            for class_name, _ in definitions:
                # Pre-compute layer, domain, and ignored status
                defining_layer = resolve_layer(module_path, layer_map)
                defining_domain = resolve_domain(module_path, domain_map)
                is_ignored = is_ignored_module(module_path, ignore_prefixes)

                info = DataclassInfo(
                    name=class_name,
                    defining_module=module_path,
                    defining_file=py_file,
                    defining_layer=defining_layer,
                    defining_domain=defining_domain,
                    is_ignored=is_ignored,
                )
                dataclasses.append(info)

    return dataclasses


def file_imports_name(file_path: Path, name: str, defining_module: str) -> bool:
    """Check if a file imports a specific name from a module.

    This is a best-effort heuristic check using AST parsing.

    Args:
        file_path: Path to Python file to check
        name: Name to look for (e.g., "PlaylistPreviewResult")
        defining_module: Module where name is defined

    Returns:
        True if file likely imports the name

    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return False

    # Check for imports
    for node in ast.walk(tree):
        # from X import Y style
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith(defining_module.rsplit(".", 1)[0])
        ):
            for alias in node.names:
                if alias.name == name:
                    return True

        # import X style (less common for dataclasses, but check anyway)
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Check if name is used as attribute access (simplified heuristic)
                if alias.name == defining_module and name in source:
                    return True

    return False


def find_imports_of_dataclass(
    project_root: Path,
    search_paths: list[Path],
    dataclass_name: str,
    defining_module: str,
    layer_map: dict[str, str],
    domain_map: dict[str, str],
    ignore_prefixes: list[str],
) -> tuple[list[str], set[str], set[str], set[str], list[ImportEdge], int]:
    """Find all modules that import a specific dataclass.

    Args:
        project_root: Root directory of the project
        search_paths: List of directory paths to search
        dataclass_name: Name of the dataclass
        defining_module: Module where dataclass is defined
        layer_map: Mapping of module prefixes to layer names
        domain_map: Mapping of module prefixes to domain names
        ignore_prefixes: List of module prefixes to ignore

    Returns:
        Tuple of (
            list of importing modules (excluding ignored),
            set of importing top-level packages (legacy, excluding ignored),
            set of importing layers (excluding ignored),
            set of importing domains (excluding ignored),
            list of ImportEdge objects (excluding ignored),
            count of ignored imports
        )

    """
    importing_modules: list[str] = []
    importing_packages: set[str] = set()
    importing_layers: set[str] = set()
    importing_domains: set[str] = set()
    import_edges: list[ImportEdge] = []
    ignored_count: int = 0

    for search_dir in search_paths:
        if not search_dir.exists():
            continue

        for py_file in search_dir.rglob("*.py"):
            importer_module = path_to_module(py_file, project_root)

            # Skip the defining module itself
            if importer_module == defining_module:
                continue

            if file_imports_name(py_file, dataclass_name, defining_module):
                # Check if this importer should be ignored
                if is_ignored_module(importer_module, ignore_prefixes):
                    ignored_count += 1
                    continue

                importing_modules.append(importer_module)

                # Extract legacy top-level package (for backward compat)
                parts = importer_module.split(".")
                if len(parts) >= 2 and parts[0] == "nomarr":
                    importing_packages.add(parts[1])
                elif parts[0] == "tests":
                    importing_packages.add("tests")

                # Resolve layer and domain
                importer_layer = resolve_layer(importer_module, layer_map)
                importer_domain = resolve_domain(importer_module, domain_map)
                importing_layers.add(importer_layer)
                importing_domains.add(importer_domain)

                # Create import edge
                imported_layer = resolve_layer(defining_module, layer_map)
                edge = ImportEdge(
                    importer_module=importer_module,
                    imported_module=defining_module,
                    importer_layer=importer_layer,
                    imported_layer=imported_layer,
                )
                import_edges.append(edge)

    return (
        importing_modules,
        importing_packages,
        importing_layers,
        importing_domains,
        import_edges,
        ignored_count,
    )


def analyze_usage(
    project_root: Path,
    search_paths: list[Path],
    dataclasses: list[DataclassInfo],
    layer_map: dict[str, str],
    domain_map: dict[str, str],
    ignore_prefixes: list[str],
) -> list[ImportEdge]:
    """Analyze usage patterns for all dataclasses (mutates DataclassInfo objects).

    Args:
        project_root: Root directory of the project
        search_paths: List of directory paths to search
        dataclasses: List of DataclassInfo objects to analyze
        layer_map: Mapping of module prefixes to layer names
        domain_map: Mapping of module prefixes to domain names
        ignore_prefixes: List of module prefixes to ignore

    Returns:
        List of all ImportEdge objects found during analysis

    """
    all_edges: list[ImportEdge] = []

    for dc in dataclasses:
        (
            modules,
            packages,
            layers,
            domains,
            edges,
            ignored_count,
        ) = find_imports_of_dataclass(
            project_root,
            search_paths,
            dc.name,
            dc.defining_module,
            layer_map,
            domain_map,
            ignore_prefixes,
        )
        dc.imported_by_modules = modules
        dc.imported_by_packages = packages
        dc.imported_by_layers = layers
        dc.imported_by_domains = domains
        dc.ignored_import_count = ignored_count
        all_edges.extend(edges)

    return all_edges


def _to_pascal_case(snake_str: str) -> str:
    """Convert snake_case to PascalCase."""
    return "".join(word.capitalize() for word in snake_str.split("_"))


def _has_dict_return(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, list[str]]:
    """Check if function returns a literal dict with >= 3 string keys.

    Returns:
        Tuple of (has_dict_return, list_of_key_names)

    """
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Return)
            and node.value
            and isinstance(node.value, ast.Dict)
            and len(node.value.keys) >= 3
        ):
            key_names = []
            all_string_keys = True
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    key_names.append(key.value)
                else:
                    all_string_keys = False
                    break
            if all_string_keys:
                return True, key_names
    return False, []


def _has_tuple_return(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, int]:
    """Check if function returns a literal tuple with >= 3 elements.

    Returns:
        Tuple of (has_tuple_return, element_count)

    """
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Return)
            and node.value
            and isinstance(node.value, ast.Tuple)
            and len(node.value.elts) >= 3
        ):
            return True, len(node.value.elts)
    return False, 0


def _has_wide_params(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, list[str]]:
    """Check if function has wide parameter list (>= 5 params or >= 4 snake_case params).

    Returns:
        Tuple of (has_wide_params, list_of_param_names)

    """
    func_args = [arg.arg for arg in func_node.args.args if arg.arg not in ("self", "cls")]

    if len(func_args) >= 5:
        return True, func_args

    if len(func_args) >= 4:
        # Check if most params are snake_case (contain underscore)
        snake_case_count = sum(1 for arg in func_args if "_" in arg)
        if snake_case_count >= len(func_args) - 1:  # Most are snake_case
            return True, func_args

    return False, []


def _looks_like_structured_return_annotation(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[bool, str]:
    """Check if function has a return annotation suggesting structured data.

    Detects return types like:
    - dict, Dict[...], Mapping[...]
    - tuple[...]
    - list[dict], list[Dict[...]], Sequence[dict]

    Args:
        func_node: Function AST node to inspect

    Returns:
        Tuple of (has_structured_return, description)
        where description is a string like "dict[str, Any]" or "list[dict]"

    """
    if not func_node.returns:
        return False, ""

    returns = func_node.returns

    # Helper to get annotation as string (simplified)
    def annotation_to_string(node: ast.expr) -> str:
        """Convert annotation node to readable string."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Subscript):
            base = annotation_to_string(node.value)
            if isinstance(node.slice, ast.Tuple):
                args = ", ".join(annotation_to_string(elt) for elt in node.slice.elts)
            else:
                args = annotation_to_string(node.slice)
            return f"{base}[{args}]"
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Constant):
            return str(node.value)
        return "..."

    # Check for dict-like returns
    if isinstance(returns, ast.Name):
        if returns.id in ("dict", "Dict", "Mapping"):
            return True, returns.id
    elif isinstance(returns, ast.Subscript):
        base_name = annotation_to_string(returns.value)
        if base_name in ("dict", "Dict", "Mapping"):
            full_type = annotation_to_string(returns)
            return True, full_type
        # Check for list[dict] or Sequence[dict]
        if base_name in ("list", "List", "Sequence"):
            # Check if the element type is dict-like
            if isinstance(returns.slice, ast.Name) and returns.slice.id in ("dict", "Dict"):
                return True, f"{base_name}[dict]"
            if isinstance(returns.slice, ast.Subscript):
                elem_base = annotation_to_string(returns.slice.value)
                if elem_base in ("dict", "Dict"):
                    full_type = annotation_to_string(returns)
                    return True, full_type
        # Check for tuple[...]
        if base_name in ("tuple", "Tuple"):
            full_type = annotation_to_string(returns)
            return True, full_type

    return False, ""


def discover_missing_dataclasses(
    project_root: Path,
    search_paths: list[Path],
    layer_map: dict[str, str],
    domain_map: dict[str, str],
    ignore_prefixes: list[str],
) -> list[MissingDataclassCandidate]:
    """Walk the codebase and find functions that might benefit from dataclass/DTO.

    Detects three patterns:
    1. Functions returning literal dicts with >= 3 string keys
    2. Functions returning literal tuples with >= 3 elements
    3. Functions with wide parameter lists (>= 5 params or >= 4 snake_case params)

    Only analyzes functions in services/workflows/components layers.
    Deduplicates by (module, function) to ensure only one candidate per function.

    Args:
        project_root: Root directory of the project
        search_paths: List of package directories to search for dataclasses
        layer_map: Mapping of module prefixes to layer names
        domain_map: Mapping of module prefixes to domain names
        ignore_prefixes: List of module prefixes to ignore

    Returns:
        List of MissingDataclassCandidate objects (deduplicated by module + function)

    """
    candidates: list[MissingDataclassCandidate] = []
    seen: set[tuple[str, str]] = set()  # Track (module, function) pairs
    allowed_layers = {"services", "workflows", "components"}

    for search_path in search_paths:
        if not search_path.exists():
            continue

        for py_file in search_path.rglob("*.py"):
            module_path = path_to_module(py_file, project_root)

            # Skip ignored modules
            if is_ignored_module(module_path, ignore_prefixes):
                continue

            # Resolve layer and domain
            layer = resolve_layer(module_path, layer_map)
            domain = resolve_domain(module_path, domain_map)

            # Skip if not in allowed layers
            if layer not in allowed_layers:
                continue

            # Parse the file
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, UnicodeDecodeError) as e:
                print(f"Warning: Could not parse {py_file}: {e}", file=sys.stderr)
                continue

            # Build a set of functions that are methods (defined inside classes)
            class_methods: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            class_methods.add(item.name)

            # Walk all function definitions
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                func_name = node.name

                # Always skip __init__
                if func_name == "__init__":
                    continue

                # Check for deduplication
                key = (module_path, func_name)
                if key in seen:
                    continue

                # Determine if function is private and if it's a method
                is_private = func_name.startswith("_")
                is_method = func_name in class_methods

                # Skip ALL private methods - they are internal implementation details
                if is_private and is_method:
                    continue

                # SPECIAL HANDLING FOR SERVICE METHODS
                # Service methods should almost always return DTOs if they return structured data
                is_service = layer == "services"
                if is_service and is_method and not is_private:
                    # Check for dict return first
                    has_dict, dict_keys = _has_dict_return(node)
                    if has_dict:
                        suggested_name = _to_pascal_case(func_name) + "Result"
                        reason = f"Service method return should be a DTO (currently returns literal dict with {len(dict_keys)} fields)"
                        candidates.append(
                            MissingDataclassCandidate(
                                module=module_path,
                                function=func_name,
                                defining_file=py_file,
                                layer=layer,
                                domain=domain,
                                reason=reason,
                                fields=dict_keys,
                                suggested_name=suggested_name,
                                is_private=is_private,
                            ),
                        )
                        seen.add(key)
                        continue

                    # Check for tuple return
                    has_tuple, tuple_count = _has_tuple_return(node)
                    if has_tuple:
                        suggested_name = _to_pascal_case(func_name) + "Result"
                        reason = f"Service method return should be a DTO (currently returns literal tuple with {tuple_count} elements)"
                        fields = [f"field{i + 1}" for i in range(tuple_count)]
                        candidates.append(
                            MissingDataclassCandidate(
                                module=module_path,
                                function=func_name,
                                defining_file=py_file,
                                layer=layer,
                                domain=domain,
                                reason=reason,
                                fields=fields,
                                suggested_name=suggested_name,
                                is_private=is_private,
                            ),
                        )
                        seen.add(key)
                        continue

                    # Check for structured return annotation
                    has_structured, type_desc = _looks_like_structured_return_annotation(node)
                    if has_structured:
                        suggested_name = _to_pascal_case(func_name) + "Result"
                        reason = f"Service method return should be a DTO (currently returns {type_desc})"
                        candidates.append(
                            MissingDataclassCandidate(
                                module=module_path,
                                function=func_name,
                                defining_file=py_file,
                                layer=layer,
                                domain=domain,
                                reason=reason,
                                fields=[],  # Can't infer fields from annotation alone
                                suggested_name=suggested_name,
                                is_private=is_private,
                            ),
                        )
                        seen.add(key)
                        continue

                # Priority 1: Dict return
                # For private functions: only flag module-level helpers (not methods)
                # For public functions/methods: flag both
                has_dict, dict_keys = _has_dict_return(node)
                if has_dict:
                    suggested_name = _to_pascal_case(func_name) + "Result"
                    reason = f"Returns literal dict with {len(dict_keys)} fields"
                    candidates.append(
                        MissingDataclassCandidate(
                            module=module_path,
                            function=func_name,
                            defining_file=py_file,
                            layer=layer,
                            domain=domain,
                            reason=reason,
                            fields=dict_keys,
                            suggested_name=suggested_name,
                            is_private=is_private,
                        ),
                    )
                    seen.add(key)
                    continue  # Only one candidate per function

                # Priority 2: Tuple return
                # Same logic as dict: only module-level private helpers
                has_tuple, tuple_count = _has_tuple_return(node)
                if has_tuple:
                    suggested_name = _to_pascal_case(func_name) + "Result"
                    reason = f"Returns literal tuple with {tuple_count} elements"
                    fields = [f"field{i + 1}" for i in range(tuple_count)]
                    candidates.append(
                        MissingDataclassCandidate(
                            module=module_path,
                            function=func_name,
                            defining_file=py_file,
                            layer=layer,
                            domain=domain,
                            reason=reason,
                            fields=fields,
                            suggested_name=suggested_name,
                            is_private=is_private,
                        ),
                    )
                    seen.add(key)
                    continue  # Only one candidate per function

                # Priority 3: Wide parameter list
                # ONLY for PUBLIC top-level functions (not methods, not private)
                if not is_method and not is_private:
                    has_wide, param_names = _has_wide_params(node)
                    if has_wide:
                        suggested_name = _to_pascal_case(func_name) + "Params"
                        reason = f"Function has {len(param_names)} parameters; consider a dataclass for input shape"
                        candidates.append(
                            MissingDataclassCandidate(
                                module=module_path,
                                function=func_name,
                                defining_file=py_file,
                                layer=layer,
                                domain=domain,
                                reason=reason,
                                fields=param_names,
                                suggested_name=suggested_name,
                                is_private=is_private,
                            ),
                        )
                        seen.add(key)

    return candidates
