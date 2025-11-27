"""
Code graph builder tool for Nomarr.

Builds AST-based call graphs with reachability analysis.
"""

from .config import load_config, resolve_paths
from .discovery import discover_python_files
from .entrypoints import find_interface_entrypoints
from .graph_builder import build_callable_index, build_graph_for_file, merge_graphs
from .models import CodeGraph, Edge, Node
from .output import write_output
from .reachability import compute_reachability

__all__ = [
    "CodeGraph",
    "Edge",
    "Node",
    "build_callable_index",
    "build_graph_for_file",
    "compute_reachability",
    "discover_python_files",
    "find_interface_entrypoints",
    "load_config",
    "merge_graphs",
    "resolve_paths",
    "write_output",
]
