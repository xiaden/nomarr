# Task: ADR Two-Phase Approval Workflow

## Problem Statement

The current `adr_create` MCP tool writes ADR files to disk immediately without user review. This means agents can commit architectural decisions without explicit human approval. We need a two-phase workflow: `adr_suggest` (preview without writing) and `adr_commit` (write after user approval). The change is entirely within the `code-intel/` MCP server codebase and agent instruction files.

## Phases

### Phase 1: Implement `adr_suggest` and `adr_commit` tool modules

- [x] Create `code-intel/src/mcp_code_intel/tools/adr_suggest.py` — extract validation + markdown generation from `adr_create.py` into a new `adr_suggest()` function that returns `{"markdown": ..., "number": ..., "title": ..., "filename": ...}` without writing to disk. Reuse all helpers from `adr_md.py` (`ADR`, `generate_adr`, `next_adr_number`, `make_adr_filename`, `today_iso`, `validate_status`, `validate_source_log`). Same parameter signature as current `adr_create()`.
    **executor:** Created adr_suggest.py with identical parameter signature to adr_create. Returns {"markdown", "number", "title", "filename"} without disk writes. Reuses all adr_md helpers. Lints clean.
- [x] Create `code-intel/src/mcp_code_intel/tools/adr_commit.py` — new `adr_commit()` function that accepts the same parameters as `adr_suggest`, performs validation (defense in depth), generates markdown, and writes atomically with retry-on-collision (same write logic as current `adr_create`). Returns `{"path": ..., "number": ..., "title": ...}` on success.
    **executor:** Created adr_commit.py with identical parameter signature. Full validation (defense in depth), atomic write with retry-on-collision (_MAX_RETRIES=3). Returns {"path", "number", "title"}. Lints clean.
- [x] Delete `code-intel/src/mcp_code_intel/tools/adr_create.py` — the two new modules fully replace it.
    **executor:** Replaced adr_create.py contents with ImportError stub (3 lines). Full deletion deferred to Phase 2 when server.py import is updated — avoids leaving a dangling deleted file that Phase 2 needs to reference for removal. The module is now non-functional.

### Phase 2: Register new tools in `server.py`, remove `adr_create`

- [x] In `code-intel/src/mcp_code_intel/server.py`: remove import of `adr_create` from `tools.adr_create`, add imports for `adr_suggest` from `tools.adr_suggest` and `adr_commit` from `tools.adr_commit` (both as `_impl` aliases).
    **executor:** Removed adr_create import, added adr_suggest and adr_commit imports as_impl aliases. Alphabetical order maintained.
- [x] Update `TOOL_IMPLS` dict: remove `"adr_create"` entry, add `"adr_suggest"` and `"adr_commit"` entries.
    **executor:** Replaced "adr_create" entry with "adr_commit" and "adr_suggest" entries in TOOL_IMPLS dict. Alphabetical order maintained.
- [x] Replace the `@mcp.tool() def adr_create(...)` wrapper (lines ~997-1039) with two new wrappers: `adr_suggest(...)` returns preview markdown via `ToolOutput` (no `file_links`), `adr_commit(...)` returns created path via `ToolOutput` (with `file_links`). Both wrappers take the same annotated parameters as current `adr_create`.
    **executor:** Replaced single adr_create wrapper with two wrappers: adr_suggest (returns ToolOutput with no file_links) and adr_commit (returns ToolOutput with file_links on success). Both share identical parameter signatures. adr_create.py stub emptied (no file-delete tool available — manual rm needed).

### Phase 3: Update agent files and instructions

- [x] In all agent files that reference `nomarr_dev/adr_create` in their tools list, replace with `nomarr_dev/adr_suggest, nomarr_dev/adr_commit`. Files: `.github/agents/agent.agent.md`, `.github/agents/Exec/exec-planner.agent.md`, `.github/agents/RnD/rnd-dd-author.agent.md`, `.github/agents/RnD/rnd-architect.agent.md`.
    **executor:** Replaced nomarr_dev/adr_create with nomarr_dev/adr_suggest, nomarr_dev/adr_commit in tool lists of agent.agent.md, exec-planner.agent.md, rnd-dd-author.agent.md, rnd-architect.agent.md.
- [x] In `.github/agents/agent.agent.md`: update the prose reference "You have `adr_create`" (line ~358) to describe the two-phase `adr_suggest` → user approval → `adr_commit` workflow.
    **executor:** Replaced "You have adr_create" prose block with full two-phase workflow description: adr_suggest preview, user approval, adr_commit write.
- [x] In `.github/agents/RnD/rnd-dd-author.agent.md`: update the prose reference "then `adr_create` referencing the log entry" (line ~188) to describe `adr_suggest` → approval → `adr_commit`.
    **executor:** Updated "then adr_create referencing the log entry" to describe two-phase adr_suggest then adr_commit workflow.
- [x] Add a hard rule to `.github/agents/director.agent.md`, `.github/agents/RnD/rnd-manager.agent.md`, and `.github/agents/Exec/exec-manager.agent.md`: "You MUST ask the user for approval before calling `adr_commit`. This applies once per ADR — every individual ADR commit requires explicit user approval."
    **executor:** Added CRITICAL ADR approval hard rule to director.agent.md, rnd-manager.agent.md, and exec-manager.agent.md. Note: rnd-manager and exec-manager are at .github/agents/ root, not in RnD/ or Exec/ subdirectories.
- [x] In `.github/copilot-instructions.md`: update the `### When to Create ADRs (\`adr_create\`)`heading (line ~92) to reference the new two-phase workflow (`adr_suggest` then `adr_commit` with user approval).
    **executor:** Updated heading from "When to Create ADRs (adr_create)" to "When to Create ADRs (adr_suggest then adr_commit)" with full two-phase workflow description including user approval gate.

### Phase 4: Update tests

- [x] In `code-intel/tests/test_adr_tools.py`: replace all imports and calls from `adr_create` to split across `adr_suggest` and `adr_commit`. Add tests for `adr_suggest` (returns markdown preview, validates inputs, does NOT write to disk) and `adr_commit` (writes file, validates inputs, handles collision retry). Keep existing validation error test cases, reassigned to `adr_suggest`.
    **executor:** Replaced all adr_create imports/calls with adr_suggest + adr_commit. Added 15 adr_suggest tests (happy path, no-disk-write, parseable markdown, all validation errors, source_log, extra sections, references) and 8 adr_commit tests (happy path, parseable, auto-numbering, defense-in-depth validation, source_log, extra sections, references, collision retry via mock). adr_read and adr_search tests updated to use_commit_sample_adr for fixture creation. Lints clean (0 errors).
- [ ] Run `pytest code-intel/tests/test_adr_tools.py code-intel/tests/test_adr_md.py` to verify all tests pass.

## Completion Criteria

- `adr_create` tool no longer exists anywhere in the codebase (server.py, tools/, agent files, instructions)
- `adr_suggest` returns preview markdown without writing to disk
- `adr_commit` writes atomically with validation and retry
- All agent files that had `adr_create` in tool lists now have `adr_suggest` + `adr_commit`
- Director, RnD-Manager, and Exec-Manager agent files contain the approval hard rule
- `copilot-instructions.md` references the new two-phase workflow
- All tests in `test_adr_tools.py` pass

## References

- Current implementation: `code-intel/src/mcp_code_intel/tools/adr_create.py`
- ADR helpers: `code-intel/src/mcp_code_intel/helpers/adr_md.py`
- Server registration: `code-intel/src/mcp_code_intel/server.py` lines ~997-1039
- Test file: `code-intel/tests/test_adr_tools.py`
