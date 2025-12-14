"""Edge type mapping and utilities."""

from __future__ import annotations

# Map from ast_case to specific edge type
AST_CASE_TO_EDGE_TYPE = {
    # Function/method calls
    "Case1b-LocalImport": "CALLS_FUNCTION",
    "Case1c-ClassInstantiation": "CALLS_CLASS",
    "Case1c-CallableClass": "CALLS_CLASS",  # Calling __call__ on class instance
    "Case1d-CallableIndexFallback": "CALLS_FUNCTION",
    # Method calls
    "Case2a-SelfMethod": "CALLS_METHOD",
    "Case2b-ClassMethod": "CALLS_METHOD",
    "Case2c-AttributeCall": "CALLS_METHOD",
    # Special patterns
    "CaseA-ModuleAttributeAccess": "CALLS_ATTRIBUTE",
    "CaseB-DependencyInjection": "CALLS_DEPENDENCY",
    "CaseT-ThreadTarget": "CALLS_THREAD_TARGET",
    "CaseM-ModuleLevelCall": "CALLS_FUNCTION",
    # Non-call edges
    "TypeAnnotation": "USES_TYPE",
    "DecoratorRegistration": "CALLS",
    # Structural edges
    "ClassContainment": "CONTAINS",
    "MethodContainment": "CONTAINS",
    "FunctionContainment": "CONTAINS",
    "Import": "IMPORTS",
    "ImportFrom": "IMPORTS",
}

# Edge types for reachability traversal
# All CALLS_* types should be followed when computing reachability
REACHABLE_EDGE_TYPES = {
    "CALLS",  # Generic fallback for edges without ast_case
    "CALLS_FUNCTION",
    "CALLS_METHOD",
    "CALLS_CLASS",
    "CALLS_ATTRIBUTE",
    "CALLS_DEPENDENCY",
    "CALLS_THREAD_TARGET",
    "USES_TYPE",
    "IMPORTS",
}


def get_edge_type_from_ast_case(ast_case: str | None) -> str:
    """
    Get the edge type for a given ast_case.

    Returns specific CALLS_* type if known, otherwise "CALLS" as fallback.
    """
    if not ast_case:
        return "CALLS"

    return AST_CASE_TO_EDGE_TYPE.get(ast_case, "CALLS")
