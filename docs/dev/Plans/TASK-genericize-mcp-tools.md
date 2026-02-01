# Task: Genericize MCP Tools for Standalone Package

## Problem Statement

The nomarr-dev MCP server contains tools that are 90% generic but have hardcoded patterns specific to nomarr's architecture (FastAPI routes, React API calls, DI patterns). Making these tools config-driven would enable:

1. Publishing as a standalone `python-mcp-devtools` package
2. Reuse across any Python monorepo with frontend
3. Community contribution and wider adoption
4. Cleaner separation between generic tooling and project-specific config

Currently hardcoded: route discovery patterns, API endpoint matching, call tracing logic, file path assumptions.

Target: Config-based architecture where all project-specific patterns live in `mcp_config.json`.

## Phases

### Phase 1: Design Configuration Schema

- [x] Create `scripts/mcp/config_schema.json` defining all configurable patterns
  **Notes:** Include backend patterns (route decorators, search paths), frontend patterns (API call patterns, search paths), project structure (workspace root detection), trace patterns (DI injection patterns)
- [x] Design fallback/defaults strategy for unconfigured projects
  **Notes:** Tools should work out-of-box for common patterns (FastAPI + React), but allow override
- [x] Document config schema with examples for FastAPI/Flask/Django + React/Vue/Svelte
  **Notes:** Create `docs/mcp-config-examples.md` with real-world configs

### Phase 2: Refactor Project-Specific Tools

- [x] Extract hardcoded patterns from `project_list_routes.py` to config
  **Notes:** Currently searches for @router.get/post/etc - make decorator patterns configurable
- [x] Extract hardcoded patterns from `project_check_api_coverage.py` to config
  **Notes:** Currently looks for api.get/post in .tsx files - make API call patterns configurable
- [x] Refactor `trace_calls.py` to use configurable import patterns
  **Notes:** Currently assumes nomarr.* module structure - generalize to any project
- [x] Refactor `trace_endpoint.py` to use configurable DI patterns
  **Notes:** Currently hardcoded to FastAPI Depends() - make injection detection configurable

### Phase 3: Create Config Loading Infrastructure

- [x] Implement `scripts/mcp/tools/helpers/config_loader.py`
  **Notes:** Load mcp_config.json from workspace root, validate against schema, provide defaults
- [x] Add config validation to MCP server startup
  **Notes:** Warn on invalid config, provide helpful error messages
- [x] Create `scripts/mcp/mcp_config.example.json` for nomarr
  **Notes:** Document all patterns currently hardcoded in the tools
- [x] Update nomarr_mcp.py to pass config to tools
    **Completed:** Module-level config variable _config loads on startup; all 4 tool decorators (project_list_routes, trace_endpoint, project_check_api_coverage, trace_calls) now pass config to tool implementations for dependency injection. Tested: config loads correctly, tools accept config parameter, zero linting errors.
  **Notes:** Inject config as parameter to tool functions, not global state

### Phase 4: Update Tool Implementations

- [x] Update all 4 project-specific tools to accept config parameter
    **Completed:** All 4 project-specific tools already accept optional config parameter from P3-S4: project_list_routes(project_root, config=None), trace_calls(qualified_name, project_root, config=None), project_check_api_coverage(filter_mode, route_path, config=None), trace_endpoint(qualified_name, project_root, config=None). Tested: tools work both with and without config (backward compatible).
  **Notes:** Backward compatible - work without config for common patterns
- [x] Add config documentation to each tool's docstring
    **Completed:** Updated docstrings for all 4 project-specific tools to document config keys used: project_list_routes (backend.routes.decorators), trace_calls (tracing.include_patterns, max_depth, filter_external), project_check_api_coverage (frontend.api_calls.patterns, search_paths), trace_endpoint (backend.dependency_injection.patterns). All docstrings include example patterns and default values. Zero linting errors.
  **Notes:** Explain what config keys each tool uses
- [ ] Add unit tests for config-based vs default behavior
  **Notes:** Test that defaults work, config overrides work, invalid config fails gracefully

### Phase 5: Repository Split Preparation

- [ ] Create `python-mcp-devtools/` directory structure
  **Notes:** Separate repo layout: src/mcp_devtools/, tests/, docs/, examples/
- [ ] Move generic tools to new structure (preserve git history)
  **Notes:** Use git filter-branch or git subtree to maintain commit history
- [ ] Create standalone pyproject.toml for package
  **Notes:** Independent versioning, deps (no nomarr-specific imports)
- [ ] Create README.md with installation and config docs
  **Notes:** Show npx usage, config examples, tool catalog
- [ ] Update nomarr to consume tools as dependency
  **Notes:** pip install from local path initially, then PyPI after publish

### Phase 6: Testing and Documentation

- [ ] Test all tools work with nomarr's config file
  **Notes:** No behavior regression from refactor
- [ ] Test tools work with minimal/no config (defaults)
  **Notes:** Should work for vanilla FastAPI + React projects
- [ ] Create example configs for 3+ frameworks
  **Notes:** FastAPI+React (our config), Flask+Vue, Django+Svelte
- [ ] Write contribution guide for adding new tools
  **Notes:** Encourage community tools for other languages/frameworks

## Completion Criteria

- All 4 project-specific tools use config instead of hardcoded patterns
- Tools work with zero config for common FastAPI + React setup
- Config schema is documented and validated on load
- Example configs exist for 3+ framework combinations
- All tests pass with both default and custom configs
- nomarr's mcp_config.json captures all current hardcoded behavior
- Ready to split into standalone repo (separate task)
