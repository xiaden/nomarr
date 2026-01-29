# Copilot Instructions for Nomarr

These are the **always-on** hard rules. Layer-specific guidance auto-applies based on file paths.

---

## MANDATORY PROCESS REQUIREMENTS

**These requirements are NOT optional. Skipping them creates architectural debt and bugs.**

### 1. Layer-Specific Instructions (Auto-Applied)

**Layer-specific instructions automatically apply when editing files in their target directories.**

Instructions are stored in `.github/instructions/` and use the `applyTo` frontmatter property to auto-apply:

| Path Pattern | Instruction File | Auto-Applies To |
|--------------|------------------|-----------------|
| `nomarr/interfaces/` | `interfaces.instructions.md` | `nomarr/interfaces/**` |
| `nomarr/services/` | `services.instructions.md` | `nomarr/services/**` |
| `nomarr/workflows/` | `workflows.instructions.md` | `nomarr/workflows/**` |
| `nomarr/components/` | `components.instructions.md` | `nomarr/components/**` |
| `nomarr/persistence/` | `persistence.instructions.md` | `nomarr/persistence/**` |
| `nomarr/helpers/` | `helpers.instructions.md` | `nomarr/helpers/**` |
| `frontend/` | `frontend.instructions.md` | `frontend/**` |

These instructions contain:
- Layer-specific conventions and patterns
- Required validation steps (including mandatory `lint_backend`)
- Common mistakes to avoid
- File naming and structure rules
- MCP server tools relevant to the layer

**You do not need to manually read these files** - they are automatically included in context when working in their target directories.

### 2. Use MCP `discover_api` Before Editing Modules

**You MUST use the MCP `discover_api` tool to inspect module shapes before editing.**

- Run `discover_api` for each module you will modify
- Use the discovered function/class signatures as the source of truth
- Do not guess at existing APIs — verify them

```
# Example: discover API before modifying
mcp_nomarrdev_discover_api("nomarr.services.infrastructure.file_watcher_svc")
```

### 3. Run Layer Validation Scripts

**You MUST verify code quality before committing.**

All Python layers require `lint_backend` to pass with zero errors:

```python
# Via MCP tool (preferred)
lint_backend(path="nomarr/interfaces")
lint_backend(path="nomarr/services")
lint_backend(path="nomarr/workflows")
lint_backend(path="nomarr/components")
lint_backend(path="nomarr/persistence")
lint_backend(path="nomarr/helpers")
```

Each layer also has naming convention checkers in `.github/skills/layer-*/scripts/check_naming.py`.

**Frontend validation:**

```powershell
Push-Location frontend; npm run lint; npm run build; Pop-Location
```

---

## TOOL USAGE HIERARCHY (MANDATORY)

**These tool selection rules are NOT optional. Violating them wastes tokens and ignores purpose-built capabilities.**

### Rule: Use Specialized MCP Tools BEFORE Standard Tools

Check this hierarchy before reaching for `read_file`, `grep_search`, or `semantic_search`:

#### 1. Python Code Navigation in Nomarr (ALWAYS FIRST)

**Before reading any Python file, use:**

- `mcp_nomarrdev_discover_api(module_name)` - See exported classes/functions/signatures (~20 lines vs full file)
- `mcp_nomarrdev_locate_symbol(symbol_name)` - Find where something is defined
- `mcp_nomarrdev_get_source(qualified_name)` - Get exact function/class with line numbers
- `mcp_nomarrdev_trace_endpoint(endpoint)` - Trace FastAPI routes through DI layers
- `mcp_nomarrdev_trace_calls(function)` - Follow call chains from entry points
- `mcp_nomarrdev_check_api_coverage()` - See which endpoints are used by frontend

**These tools understand FastAPI DI and nomarr's architecture. Use them.**

#### 2. General Code Navigation (SECOND PRIORITY)

**For any file exploration:**

- `mcp_oraios_serena_get_symbols_overview(relative_path)` - See file structure before reading
- `mcp_oraios_serena_find_symbol(name_path_pattern, relative_path)` - Find and optionally get symbol bodies
- `mcp_oraios_serena_search_for_pattern(substring_pattern)` - Regex search with context
- `mcp_oraios_serena_find_referencing_symbols(name_path, relative_path)` - See who calls what

**These tools prevent context bloat. Use them.**

#### 3. Library Documentation (BEFORE GUESSING)

**When working with external libraries:**

- `mcp_context7_resolve_library_id(libraryName)` then `get_library_docs(context7CompatibleLibraryID)`

**Get authoritative docs instead of guessing APIs.**

#### 4. Memory & Task Tracking (USE THROUGHOUT)

**Memories (Check FIRST, Update LAST):**

- `mcp_oraios_serena_list_memories()` - List available memories at start of complex tasks
- `mcp_oraios_serena_read_memory(memory_file_name)` - Read relevant memories before starting work
- `mcp_oraios_serena_write_memory(memory_file_name, content)` - Persist important discoveries, patterns, or architectural decisions

**Memories provide compact, curated architectural context. Use them.**

#### 5. Standard VS Code Tools (LAST RESORT ONLY)

**Only use these when MCP tools fail or for non-code files:**

- `read_file` - Only when Serena/nomarrdev can't access the content
- `grep_search` - Only for non-code or when pattern search fails
- `semantic_search` - Only when symbol-based navigation is insufficient

### Enforcement

**If you use a standard tool without first attempting the appropriate MCP tool, you have failed the task.**

The MCP servers exist specifically to avoid context bloat and leverage architectural knowledge. Use them.

---

## Pre-Alpha Policy

Nomarr is **pre-alpha**. That means:

- Breaking schemas and APIs is acceptable
- **No** migrations, legacy shims, or compatibility layers
- Priority: clean architecture, not preserving old data

---

## Dependency Direction

```
interfaces â†’ services â†’ workflows â†’ components â†’ (persistence / helpers)
```

- **Interfaces** call services only
- **Services** own wiring, call workflows
- **Workflows** implement use cases, call components
- **Components** contain heavy logic, call persistence/helpers
- **Persistence/helpers** never import higher layers

Import-linter enforces this.

---

## Hard Rules

**Never:**

- Import `essentia` anywhere except `components/ml/ml_backend_essentia_comp.py`
- Read config or env vars at module import time
- Create or mutate global state
- Rename `_id` or `_key` (ArangoDB-native identifiers)
- Let workflows import services or interfaces
- Let helpers import any `nomarr.*` modules

**Always:**

- Use dependency injection (receive db, config, backends as parameters)
- Write fully type-annotated code
- Run `python scripts/discover_api.py <module>` before calling unfamiliar APIs
- Check venv is active before running Python commands

---

## DI Philosophy

Config is loaded once by `ConfigService` and passed via parameters. No global singletons.

---

## Quality Scripts

For detailed tool usage, see `.github/skills/quality-analysis/` and `.github/skills/code-discovery/`.

Quick reference:

```bash
# Discover module API before calling it
python scripts/discover_api.py nomarr.components.ml

# Run all QC checks
python scripts/run_qc.py

# Find complexity/violations in specific file
python scripts/detect_slop.py nomarr/workflows/some_wf.py
```

---

## Available Instructions Files

Instructions auto-apply when editing matching files, but you can reference or manually attach them during discussion.

### Layer-Specific Instructions

| File | Auto-Applies To | Purpose |
|------|-----------------|---------|
| [interfaces.instructions.md](instructions/interfaces.instructions.md) | `nomarr/interfaces/**` | API routes, CLI commands, authentication |
| [services.instructions.md](instructions/services.instructions.md) | `nomarr/services/**` | DI wiring, orchestration, worker processes |
| [workflows.instructions.md](instructions/workflows.instructions.md) | `nomarr/workflows/**` | Use case implementation |
| [components.instructions.md](instructions/components.instructions.md) | `nomarr/components/**` | Heavy domain logic, computation |
| [persistence.instructions.md](instructions/persistence.instructions.md) | `nomarr/persistence/**` | Database access, AQL queries |
| [helpers.instructions.md](instructions/helpers.instructions.md) | `nomarr/helpers/**` | Pure utilities, DTOs, exceptions |
| [frontend.instructions.md](instructions/frontend.instructions.md) | `frontend/**` | React + TypeScript UI |

### MCP Server Instructions

| File | Auto-Applies To | Purpose |
|------|-----------------|---------|
| [mcp-basics.instructions.md](instructions/mcp-basics.instructions.md) | `scripts/mcp/**` | MCP server fundamentals and setup |
| [mcp-tools.instructions.md](instructions/mcp-tools.instructions.md) | `scripts/mcp/tools/**` | MCP tool implementation patterns |
| [mcp-resources.instructions.md](instructions/mcp-resources.instructions.md) | `scripts/mcp/resources/**` | MCP resource implementation patterns |
| [mcp-prompts.instructions.md](instructions/mcp-prompts.instructions.md) | `scripts/mcp/prompts/**` | MCP prompt implementation patterns |
| [mcp-context.instructions.md](instructions/mcp-context.instructions.md) | `scripts/mcp/context/**` | MCP context provider patterns |

### Meta Instructions

| File | Auto-Applies To | Purpose |
|------|-----------------|---------|
| [instructions.instructions.md](instructions/instructions.instructions.md) | `.github/instructions/**/*.instructions.md` | Guidelines for creating instruction files |

**Each layer instruction includes:**
- Allowed/forbidden imports
- MCP server tools for that layer
- Naming conventions
- Validation checklist with mandatory `lint_backend` requirement

**During discussion:** Reference these files when planning changes. Suggest manual attachment if deeper context needed.

---

End of always-on instructions.