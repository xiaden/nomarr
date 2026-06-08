"""MCP Code Intel - Codebase intelligence layer for AI agents.

This package provides development tools exposed via MCP (Model Context Protocol).

The main entry point is the server module:
    from mcp_code_intel.server import main, mcp, TOOL_IMPLS

Individual tool implementations can be imported from their modules:
    from mcp_code_intel.project_list_dir import project_list_dir
    from mcp_code_intel.trace_calls import trace_calls

Note: We intentionally do NOT re-export tool functions here to avoid
namespace shadowing issues (importing `from . import X` would get the
function, not the module, causing AttributeError when trying to access
`module.function`).
"""

__version__ = "0.1.0"
