"""Reusable MCP tools for Python project analysis and code tracing.

This package contains generic, config-driven tools for:
- Listing project routes from FastAPI applications
- Tracing function/method call chains
- Checking API coverage between backend and frontend
- Tracing FastAPI endpoints through dependency injection

All tools support zero-config defaults with optional JSON configuration for
advanced customization of project paths, patterns, and tracing behavior.

Version: 0.1.0
"""

__version__ = "0.1.0"
__author__ = "Nomarr Contributors"
__all__ = [
    "project_list_routes",
    "trace_calls",
    "project_check_api_coverage",
    "trace_endpoint",
]
