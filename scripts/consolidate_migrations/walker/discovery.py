"""Migration file discovery and AST parsing utilities.

Responsible for locating V004--V019 migration files, parsing their AST, and
extracting module-level constants.  These functions form the entry point for
the replay engine -- callers obtain ``(module_node, upgrade_func_node)`` tuples
which are then passed to the recognizers and walker layers.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

# ---------------------------------------------------------------------------
# Version range for migrations to replay
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^V(\d+)_.*\.py$")


def _scan_version_range(migrations_dir: Path) -> tuple[int, int] | None:
    """Scan the migrations directory and return the (min, max) numeric version.

    Returns ``None`` if no ``V{NNN}_*.py`` files are found.
    """
    versions: set[int] = set()
    for child in migrations_dir.iterdir():
        if not child.is_file():
            continue
        match = _VERSION_RE.match(child.name)
        if match is None:
            continue
        versions.add(int(match.group(1)))

    if not versions:
        return None
    return (min(versions), max(versions))


# ---------------------------------------------------------------------------
# Migration discovery
# ---------------------------------------------------------------------------


def discover_migrations(
    migrations_dir: Path,
    *,
    min_version: int | None = None,
    max_version: int | None = None,
) -> list[Path]:
    """Find all ``V{NNN}_*.py`` migration files and return them sorted by version.

    By default discovers all migration files in the directory.  Pass
    *min_version* / *max_version* to constrain the range.

    Args:
        migrations_dir: Path to the ``nomarr/migrations/`` directory.
        min_version: Inclusive lower bound.  ``None`` means "discover from disk".
        max_version: Inclusive upper bound.  ``None`` means "discover from disk".

    Returns:
        List of ``Path`` objects sorted by numeric version.

    Raises:
        FileNotFoundError: If *migrations_dir* does not exist.

    """
    if not migrations_dir.is_dir():
        msg = f"Migrations directory not found: {migrations_dir}"
        raise FileNotFoundError(msg)

    # Auto-discover the version range from disk when bounds are not given
    if min_version is None or max_version is None:
        discovered = _scan_version_range(migrations_dir)
        if discovered is None:
            return []
        disk_min, disk_max = discovered
        if min_version is None:
            min_version = disk_min
        if max_version is None:
            max_version = disk_max

    versioned: list[tuple[int, Path]] = []
    for child in migrations_dir.iterdir():
        if not child.is_file():
            continue
        match = _VERSION_RE.match(child.name)
        if match is None:
            continue
        version = int(match.group(1))
        if min_version <= version <= max_version:
            versioned.append((version, child))

    versioned.sort(key=lambda pair: pair[0])
    return [path for _, path in versioned]


# ---------------------------------------------------------------------------
# AST parsing
# ---------------------------------------------------------------------------


def _parse_upgrade_function(source_path: Path) -> tuple[ast.Module, ast.FunctionDef]:
    """Read a migration file, parse its AST, and locate the ``upgrade`` function.

    Args:
        source_path: Path to a single migration ``.py`` file.

    Returns:
        A ``(module_node, upgrade_func_node)`` tuple so callers also have
        access to module-level constants and helper functions.

    Raises:
        ValueError: If no ``upgrade`` function is found in the module.

    """
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            return tree, node

    msg = f"No 'upgrade' function found in {source_path}"
    raise ValueError(msg)


def _extract_module_constants(module: ast.Module) -> dict[str, Any]:
    """Extract simple constant assignments from module-level code.

    Handles both plain assignments (``X = "value"``) and annotated
    assignments (``X: list[str] = [...]``).  Only captures literal
    values (strings, ints, bools, and lists of strings).

    Args:
        module: The parsed AST module node.

    Returns:
        A mapping of constant names to their resolved Python values.
    """
    constants: dict[str, Any] = {}
    for node in ast.iter_child_nodes(module):
        target: ast.Name | None = None
        value: ast.expr | None = None

        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name):
                target = t
                value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target = node.target
            value = node.value

        if target is None or value is None:
            continue

        # Simple scalar constants
        if isinstance(value, ast.Constant) and isinstance(value.value, str | int | bool):
            constants[target.id] = value.value
        # List-of-strings constants (e.g. _STATE_KEYS: list[str] = [...])
        elif isinstance(value, ast.List):
            str_values: list[str] = []
            all_strings = True
            for elt in value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    str_values.append(elt.value)
                else:
                    all_strings = False
                    break
            if all_strings and str_values:
                constants[target.id] = str_values

    return constants
