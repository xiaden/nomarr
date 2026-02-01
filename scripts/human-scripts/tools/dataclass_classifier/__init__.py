"""Dataclass Classification Toolkit

A toolkit for analyzing and classifying @dataclass definitions in the Nomarr codebase
according to architectural principles.
"""

__version__ = "1.0.0"

from .classify import classify_all, classify_dataclass, detect_suspect_imports, infer_domain_from_dataclass
from .config import get_config_paths, is_ignored_module, load_config, resolve_domain, resolve_layer
from .discovery import (
    analyze_usage,
    discover_all_dataclasses,
    discover_missing_dataclasses,
    find_dataclass_definitions,
    find_imports_of_dataclass,
)
from .model import DataclassInfo, ImportEdge, MissingDataclassCandidate
from .report import print_summary, write_json_output, write_text_output

__all__ = [
    "DataclassInfo",
    "ImportEdge",
    "MissingDataclassCandidate",
    "analyze_usage",
    "classify_all",
    "classify_dataclass",
    "detect_suspect_imports",
    "discover_all_dataclasses",
    "discover_missing_dataclasses",
    "find_dataclass_definitions",
    "find_imports_of_dataclass",
    "get_config_paths",
    "infer_domain_from_dataclass",
    "is_ignored_module",
    "load_config",
    "print_summary",
    "resolve_domain",
    "resolve_layer",
    "write_json_output",
    "write_text_output",
]
