"""AST utilities for code graph building.

This package provides utilities for extracting information from Python AST nodes:
- metadata: Layer, docstrings, return annotations, class attributes, function params
- type_extraction: Type annotations and USES_TYPE edge creation
- import_extraction: Import statement parsing
- call_extraction: Function/method call detection and CALLS edge creation
"""

from __future__ import annotations

# Re-export all public functions from submodules
from .call_extraction import extract_calls_from_function
from .import_extraction import extract_imports_from_function
from .metadata import (
    extract_class_attributes,
    extract_decorator_targets,
    extract_function_params,
    extract_return_var_names,
    get_docstring,
    get_layer_from_module_path,
    get_return_annotation,
    is_fastapi_route_decorator,
)
from .type_extraction import extract_type_annotations_from_function, extract_type_names_from_annotation

__all__ = [
    # Call extraction
    "extract_calls_from_function",
    "extract_class_attributes",
    "extract_decorator_targets",
    "extract_function_params",
    # Import extraction
    "extract_imports_from_function",
    "extract_return_var_names",
    "extract_type_annotations_from_function",
    # Type extraction
    "extract_type_names_from_annotation",
    "get_docstring",
    # Metadata extraction
    "get_layer_from_module_path",
    "get_return_annotation",
    "is_fastapi_route_decorator",
]
