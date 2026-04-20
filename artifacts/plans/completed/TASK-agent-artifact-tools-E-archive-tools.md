# Task: Archive Tools (plan_archive + dd_archive)

## Problem Statement

The Agent Artifact Tools feature introduces lifecycle-managed directories for plans and design documents (`pending/` → `completed/`). Two archive tools are needed to gate these transitions: `plan_archive` verifies every step is complete before moving a plan, and `dd_archive` verifies all convention-linked plans are completed before moving a design document. Both tools follow the established pure-function tool pattern, delegating to existing helpers (`plan_md.parse_plan`, `dd_md.parse_dd`) for parsing and validation.

**Prerequisites:** TASK-agent-artifact-tools-A (directory structure + path constants), TASK-agent-artifact-tools-B (dd_md helper with `parse_dd`)

## Phases

### Phase 1: Implement Archive Tool Modules

- [x] Create `code-intel/src/mcp_code_intel/tools/plan_archive.py`: implement `plan_archive(plan_name: str, ignore_blocked: bool = False, workspace_root: Path) -> dict[str, Any]` that resolves the plan file in `PLANS_PENDING_DIR` (`artifacts/plans/pending/`), reads and parses it via `plan_md.parse_plan()`, checks all steps have `checked=True` (returns error dict with `incomplete_steps` if not), then checks for steps with `**Blocked:**` annotations — if any found and `ignore_blocked=False`, returns error dict with `blocked_steps` list and `message` suggesting the caller verify blockers are resolved and retry with `ignore_blocked=True`; if `ignore_blocked=True`, proceeds despite blocked annotations — on success moves the file to `PLANS_COMPLETED_DIR` (`artifacts/plans/completed/`) via `shutil.move()` and returns `{"archived": True, "path": ..., "steps_completed": N}`; handle `FileNotFoundError` gracefully returning `{"error": "not_found", "message": ...}`
- [x] Create `code-intel/src/mcp_code_intel/tools/dd_archive.py`: implement `dd_archive(name: str, workspace_root: Path) -> dict[str, Any]` that resolves the DD file in `DESIGNS_PENDING_DIR` (`artifacts/designs/pending/`), parses it via `dd_md.parse_dd()`, extracts the slug from the filename, scans `PLANS_PENDING_DIR` for `TASK-{slug}-*.md` files (convention-based link), optionally checks `artifacts/designs/parts/{slug}/README.md` for additional plan names, returns error dict with `pending_plans` list if any linked plans still exist in pending, otherwise moves the DD to `DESIGNS_COMPLETED_DIR` (`artifacts/designs/completed/`) via `shutil.move()`, updates the `**Status:**` line to `Completed` before moving, and returns `{"archived": True, "path": ..., "linked_plans_completed": [...]}`; handle `FileNotFoundError` gracefully
- [x] Add unit-level validation: both tools must reject names containing path traversal characters (`/`, `\`, `..`), strip `.md` extension and any prefix during name normalization, and use the directory constants from Plan A's contracts (`PLANS_PENDING_DIR`, `PLANS_COMPLETED_DIR`, `DESIGNS_PENDING_DIR`, `DESIGNS_COMPLETED_DIR`)

### Phase 2: Server Registration and Verification

- [x] In `code-intel/src/mcp_code_intel/server.py`: add imports `from .tools.plan_archive import plan_archive as plan_archive_impl` and `from .tools.dd_archive import dd_archive as dd_archive_impl`; add both to `TOOL_IMPLS` dict
- [x] In `code-intel/src/mcp_code_intel/server.py`: create `@mcp.tool()` wrapper for `plan_archive` with `Annotated[str, "Plan name (with or without .md extension)"]` parameter, docstring describing verification behavior, delegating to `plan_archive_impl` and wrapping response in `ToolOutput`
- [x] In `code-intel/src/mcp_code_intel/server.py`: create `@mcp.tool()` wrapper for `dd_archive` with `Annotated[str, "Design document name (with or without DD- prefix or .md extension)"]` parameter, docstring describing linked-plan verification, delegating to `dd_archive_impl` and wrapping response in `ToolOutput`
- [x] Run `lint_project_backend` on `code-intel/` to verify both tools and server registration compile cleanly with no import or type errors

## Completion Criteria

- `plan_archive` tool exists, validates all steps complete, warns on blocked steps (overridable via `ignore_blocked=True`), moves plan from pending to completed
- `dd_archive` tool exists, validates no linked plans in pending, updates DD status to Completed, moves DD from pending to completed
- Both tools registered in `server.py` with `@mcp.tool()` wrappers following the `ToolOutput` response pattern
- Both tools handle `FileNotFoundError` and path traversal attempts gracefully with error dicts
- `lint_project_backend` passes on `code-intel/`

## References

- Design doc: `plans/dev/design-agent-artifact-tools.md` (plan_archive and dd_archive API sections)
- Contracts: `plans/dev/agent-artifact-tools-parts/CONTRACTS.md` (path constants, Plan A + Plan B contracts)
- Parts breakdown: `plans/dev/agent-artifact-tools-parts/README.md`
