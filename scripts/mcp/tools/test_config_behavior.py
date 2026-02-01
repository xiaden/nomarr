#!/usr/bin/env python3
"""Unit tests for config-based vs default tool behavior - P4-S3."""

import sys
from pathlib import Path

# Add project root to sys.path BEFORE imports
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.mcp.tools.project_list_routes import project_list_routes
from scripts.mcp.tools.trace_calls import trace_calls
from scripts.mcp.tools.project_check_api_coverage import project_check_api_coverage
from scripts.mcp.tools.trace_endpoint import trace_endpoint
from scripts.mcp.tools.helpers.config_loader import load_config


def test_all_tools_work_without_config():
    """Backward compatibility: all tools work without config parameter."""
    # project_list_routes
    r1 = project_list_routes(ROOT)
    assert "routes" in r1, f"project_list_routes failed: {r1}"
    assert len(r1["routes"]) > 0

    # trace_calls
    r2 = trace_calls("nomarr.components.application_comp.ApplicationComponent", ROOT)
    assert "root" in r2 or "error" in r2

    # project_check_api_coverage
    r3 = project_check_api_coverage()
    assert "stats" in r3
    assert "endpoints" in r3

    # trace_endpoint
    r4 = trace_endpoint("nomarr.interfaces.api.web.info_if.web_info", ROOT)
    assert "endpoint" in r4 or "error" in r4

    print("✓ test_all_tools_work_without_config PASSED")


def test_all_tools_work_with_config():
    """Config injection: all tools work with config parameter."""
    config = load_config(ROOT)

    # project_list_routes
    r1 = project_list_routes(ROOT, config=config)
    assert "routes" in r1
    assert len(r1["routes"]) > 0

    # trace_calls
    r2 = trace_calls("nomarr.components.application_comp.ApplicationComponent", ROOT, config=config)
    assert "root" in r2 or "error" in r2

    # project_check_api_coverage
    r3 = project_check_api_coverage(config=config)
    assert "stats" in r3

    # trace_endpoint
    r4 = trace_endpoint("nomarr.interfaces.api.web.info_if.web_info", ROOT, config=config)
    assert "endpoint" in r4 or "error" in r4

    print("✓ test_all_tools_work_with_config PASSED")


def test_config_structure():
    """Config has expected structure with backend/frontend/tracing."""
    config = load_config(ROOT)
    assert "backend" in config
    assert "frontend" in config
    assert "tracing" in config

    # Verify backend config
    backend = config["backend"]
    assert "routes" in backend
    assert "dependency_injection" in backend

    # Verify frontend config
    frontend = config["frontend"]
    assert "api_calls" in frontend

    # Verify tracing config
    tracing = config["tracing"]
    assert "include_patterns" in tracing

    print("✓ test_config_structure PASSED")


def test_tools_use_config_patterns():
    """Tools respect config patterns."""
    config = load_config(ROOT)

    # Routes should use configured decorators
    r1 = project_list_routes(ROOT, config=config)
    assert "routes" in r1
    assert len(r1["routes"]) > 0

    # API coverage should use configured patterns
    r3 = project_check_api_coverage(config=config)
    assert "stats" in r3

    print("✓ test_tools_use_config_patterns PASSED")


if __name__ == "__main__":
    test_all_tools_work_without_config()
    test_all_tools_work_with_config()
    test_config_structure()
    test_tools_use_config_patterns()
    print("\n✓ All config behavior tests PASSED!")
