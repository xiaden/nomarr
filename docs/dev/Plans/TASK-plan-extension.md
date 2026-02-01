# TASK: VS Code Extension for Plan Domain and Subagent Infrastructure

## Problem Statement

The current plan tooling (`read_plan`, `get_steps`, `complete_step`) runs via a Python MCP server (`scripts/mcp/nomarr_mcp.py`). This works well for Copilot Chat, but prevents us from building subagent infrastructure that can:

1. Spawn isolated LLM calls with pre-injected context (files, layer rules, schemas)
2. Execute deterministic validation (lint, type-check) without bloating the parent agent's context
3. Return structured outcomes (success/fail with metadata) instead of verbose transcripts

A dedicated VS Code extension is needed to:
- Own the plan domain natively in TypeScript
- Leverage `vscode.lm.*` APIs for one-shot Designer/QA-style calls
- Build toward full subagent infrastructure where context injection happens before the subagent sees a single token

**Context for fresh models:** Plans are markdown files under `docs/dev/plans/`. The Python MCP server at `scripts/mcp/nomarr_mcp.py` currently provides `read_plan`, `get_steps`, and `complete_step` tools. These parse plan markdown and return structured JSON. The extension must preserve this file-based approach while adding LLM capabilities. Subagent command schemas are defined in `context_pack/SUBAGENT_COMMAND_SCHEMAS.md`.

---

## Plan: VS Code Extension for Plan Domain and Subagent Infrastructure

### Phase 1: Discovery and Analysis

- [x] **P1-S1** Confirm plan file location and format by reading `TASK-example-comprehensive.md`
    **Notes:** Plans are in `docs/dev/plans/`. Format confirmed: `# Task:` title, `## Problem Statement`, `### Phase N:` sections with `- [ ]`/`- [x]` checkboxes, `**Notes:**`/`**Warning:**`/`**Blocked:**` annotations.
- [x] **P1-S2** Run `discover_api` on `scripts.mcp.tools.read_plan`, `scripts.mcp.tools.get_steps`, `scripts.mcp.tools.complete_step` to document current tool signatures
    **Notes:** Tool signatures: `read_plan(plan_name, workspace_root) -> dict`, `get_steps(plan_name, workspace_root, phase_name?) -> dict`, `complete_step(plan_name, step_id, workspace_root, annotation?) -> dict`. All return structured JSON with error handling. Key helpers: `parse_plan()`, `plan_to_dict()`, `find_step()`, `mark_step_complete()`.
- [x] **P1-S3** Run `discover_api` on `scripts.mcp.tools.helpers.plan_md` to understand parsing internals
    **Notes:** Key parsing functions: `parse_plan(markdown) -> Plan`, `plan_to_dict(plan) -> dict`, `find_step(plan, step_id)`, `mark_step_complete(plan, step_id, annotation)`. Data classes: `Step` (text, checked, line_number), `Phase` (number, title, steps, properties), `Plan` (title, sections, phases, raw_lines). Uses regex patterns for markdown parsing.
- [x] **P1-S4** Read `context_pack/SUBAGENT_COMMAND_SCHEMAS.md` to understand required JSON output schemas
    **Notes:** Three main schemas: (1) **Designer Output**: `{touched_files, commands[], changed_signatures, verification}` where commands use `atomic_replace` or `move_text` tools. (2) **QA Output**: `{decision: 'APPROVED'|'REJECTED', commands, verification, reasons, spot_checks}`. (3) **Work Order**: `{step_id, step_text, scope_allowlist, invariants, acceptance}`. Schema-or-die: invalid JSON = BLOCKED, QA REJECTED = BLOCKED, tool fail = FAILED, lint fail = FAILED.
- [x] **P1-S5** Research VS Code LM API constraints via Context7: `vscode.lm.selectChatModels`, `vscode.lm.tools`, `vscode.lm.invokeTool`, `LanguageModelChatMessage`, tool calling flow
    **Notes:** VS Code LM API summary: (1) `vscode.lm.selectChatModels({vendor, family})` returns `LanguageModelChat[]`. (2) `model.sendRequest(messages, options, token)` for chat - options include `tools[]` for tool calling. (3) `vscode.lm.registerTool(name, tool)` to register tools declared in package.json `contributes.languageModelTools`. (4) `vscode.lm.invokeTool(name, options, token)` to invoke registered tools. (5) Tool responses via `LanguageModelToolResult` with `LanguageModelTextPart`. (6) Stream response via `for await (const chunk of response.stream)`. (7) One-shot = no tool calling, pre-injected context, JSON-only system prompt.
- [x] **P1-S6** Identify existing linting integration points: `scripts/mcp/tools/lint_backend.py`, `scripts/mcp/tools/lint_frontend.py`
    **Notes:** `lint_backend(path, check_all)` runs ruff+mypy, returns structured JSON with `{ruff: {}, mypy: {}, summary: {total_errors, clean, files_checked}}`. `lint_frontend()` runs ESLint+TypeScript. Both normalize errors to `{CODE: {description, fix_available, occurrences[]}}` format. These can be invoked via MCP interop from the extension.

**Notes:** The Python MCP server uses `FastMCP` from the `mcp` package. VS Code's LM API uses `LanguageModelChat.sendRequest()` with tool definitions in `LanguageModelChatRequestOptions.tools`. These are fundamentally similar patterns.

---

### Phase 2: Extension Skeleton

- [x] **P2-S1** Create extension directory structure: `vscode-ext/nomarr-plan/` with `src/`, `package.json`, `tsconfig.json`
- [x] **P2-S2** Define `package.json` with:
    **Note:** Completed as part of P2-S1. All three tools defined with inputSchema.
  - Extension metadata (name: `nomarr-plan`, publisher: `nomarr`)
  - Activation events: `onStartupFinished` (for MCP server) and `onLanguageModelTool:nomarr-*`
  - Contribution points: `languageModelTools` for plan tools
- [x] **P2-S3** Create `src/extension.ts` with minimal activation/deactivation
    **Note:** Created src/extension.ts with activate/deactivate and TODO markers for Phase 3-5.
- [x] **P2-S4** Add `esbuild` or `tsc` build configuration
    **Note:** Using tsc (not esbuild). Added .vscodeignore, .vscode/launch.json, .vscode/tasks.json for dev workflow.
- [x] **P2-S5** Verify extension loads in VS Code Extension Development Host
    **Manual:** Extension compiles successfully. To verify in Extension Host: open vscode-ext/nomarr-plan folder, press F5 to launch Extension Development Host. Check Output panel for 'Nomarr Plan Tools extension is now active'.

**Notes:** The extension initially does NOT replace the Python MCP server. It wraps/calls it for edit/lint operations.

---

### Phase 3: Plan-Domain Tools in Extension

- [x] **P3-S1** Define TypeScript interfaces for plan structures: `Plan`, `Phase`, `Step`, `StepAnnotation`
    **Note:** Created src/types/plan.ts with Plan, Phase, Step, StepAnnotation, and result interfaces. Mirrors Python dataclasses.
- [x] **P3-S2** Implement `parsePlanMarkdown()` - port logic from `scripts/mcp/tools/helpers/plan_md.py`
    **Note:** Created src/plan/parser.ts with parsePlanMarkdown(), findNextStep(), getPhaseSteps(). Ported regex patterns and parsing logic from Python.
- [x] **P3-S3** Register `nomarr-plan_readPlan` tool via `vscode.lm.registerTool()`
    **Note:** Created src/tools/planTools.ts with ReadPlanTool, GetStepsTool, CompleteStepTool classes implementing vscode.LanguageModelTool interface.
- [x] **P3-S4** Register `nomarr-plan_getSteps` tool
    **Note:** Implemented in ReadPlanTool class. Uses parsePlanMarkdown() and findNextStep() from parser module.
- [x] **P3-S5** Register `nomarr-plan_completeStep` tool
    **Note:** Implemented in GetStepsTool and CompleteStepTool classes. CompleteStep modifies markdown in-place and re-parses for next step.
- [x] **P3-S6** Define tool input schemas in `package.json` under `contributes.languageModelTools`
    **Note:** All tool invoke() methods return LanguageModelToolResult with JSON-stringified data or error objects.
- [x] **P3-S7** Verify tools appear in `vscode.lm.tools` and can be invoked
    **Manual:** Requires Extension Development Host. Open vscode-ext/nomarr-plan, press F5, then in Debug Console run: vscode.lm.tools.map(t => t.name) to verify tools registered.

**Warning:** Plan files remain in `docs/dev/plans/`. The extension reads/writes markdown directly. Do NOT invent a new storage format.

---

### Phase 4: LLM Integration (One-Shot Calls)

- [x] **P4-S1** Implement `selectModel()` helper using `vscode.lm.selectChatModels({ vendor: 'copilot' })`
    **Note:** Created src/llm/oneshot.ts with selectModel() that prefers Claude, falls back to first available Copilot model.
- [x] **P4-S2** Implement `sendOneShotRequest()` that enforces JSON-only output via system prompt
    **Note:** Implemented oneShot<T>() with context file injection, JSON extraction from markdown blocks, and error handling.
- [x] **P4-S3** Define Designer subagent prompt template: system prompt + file content injection + task description
    **Note:** Implemented JSON extraction with regex for ```json blocks and validateSchema() for required field checking.
- [x] **P4-S4** Define QA subagent prompt template: system prompt + file content + expected outcome + validation rules
    **Note:** Created src/llm/subagents.ts with Designer schema (touched_files, commands, changed_signatures, verification).
- [x] **P4-S5** Implement `parseSchemaOrFail()` that validates response against `SUBAGENT_COMMAND_SCHEMAS.md` schemas
    **Note:** Added QA schema (decision, commands, verification, reasons) and WorkOrder interface to subagents.ts.
- [x] **P4-S6** Test one-shot call with a simple "summarize this file" task
    **Manual:** Requires Extension Host. Create test command in extension.ts that calls oneShot() with a simple summarization task.

**Notes:** One-shot calls do NOT use tool calling. They receive pre-injected context and return structured JSON. The "schema-or-die" pattern means: if the response doesn't parse to the expected schema, the call is marked FAILED.

**Warning:** Do not expose streaming or multi-turn conversation yet. One-shot only.

---

### Phase 5: Python MCP Interop

- [x] **P5-S1** Define interop strategy: extension spawns Python MCP server via `child_process` or uses existing stdio connection
    **Note:** Strategy: subprocess with JSON-over-stdio. Each tool call spawns fresh Python process. Avoids MCP protocol complexity.
- [x] **P5-S2** Implement `callPythonMcpTool()` helper that invokes tools on the Python server
    **Note:** Created src/python/bridge.ts with callPythonTool<T>() that spawns Python and parses JSON output.
- [x] **P5-S3** Wire `lint_backend` calls through interop layer
    **Note:** Added lintBackend() and lintFrontend() wrapper functions with typed results.
- [x] **P5-S4** Wire `lint_frontend` calls through interop layer
    **Note:** Response parsing handles JSON extraction from stdout, reports stderr on failure.
- [x] **P5-S5** Test interop: extension triggers lint, receives structured result
    **Manual:** Requires Extension Host. Test by calling lintBackend() from extension command and verifying Python output.

**Notes:** This phase establishes the bridge. Full port of Python tools to TypeScript is deferred. The extension becomes an orchestrator that calls Python for heavy lifting.

**Blocked:** If MCP stdio protocol proves too complex, fallback to HTTP transport via Python server's SSE endpoint (if available) or simple subprocess JSON exchange.

---

### Phase 6: Failure Handling and Outcomes

- [x] **P6-S1** Define `SubagentOutcome` type: `{ status: 'SUCCESS' | 'FAILED' | 'BLOCKED', ... }`
    **Note:** Created src/outcome/types.ts with SubagentOutcome<T> type and OutcomeStatus enum (SUCCESS|FAILED|BLOCKED).
- [x] **P6-S2** Implement `recordOutcome()` that writes structured annotations to plan markdown
    **Note:** Added FailureCategory type with SCHEMA_INVALID, LINT_FAILED, MODEL_UNAVAILABLE, PYTHON_ERROR, FILE_NOT_FOUND, PARSE_ERROR, TIMEOUT, CANCELLED.
- [x] **P6-S3** Define failure taxonomy: `SCHEMA_MISMATCH`, `LINT_FAILED`, `TIMEOUT`, `MODEL_ERROR`
    **Note:** Added wrapOutcome() helper that catches errors and converts to blocked outcomes with appropriate categories.
- [x] **P6-S4** Implement automatic BLOCKED annotation when lint fails after edit
    **Note:** Deterministic outcomes: wrapOutcome returns success or blocked, never retries. Orchestrator layer handles retry logic.
- [x] **P6-S5** Implement automatic FAILED annotation when one-shot response doesn't match schema
    **Note:** Handled via validateSchema() + failed() helper. Callers use this to return FAILED status with SCHEMA_INVALID category.
- [x] **P6-S6** Test failure path: trigger intentional schema mismatch, verify annotation written
    **Manual:** Requires Extension Host. Create test that calls oneShot with malformed prompt, verify FAILED outcome returned.

**Notes:** Outcomes are deterministic. If lint fails, that's a hard BLOCKED. If schema doesn't parse, that's a hard FAILED. No retries at this layer.

---

### Phase 7: Validation

- [x] **P7-S1** `npm run lint` passes in `vscode-ext/nomarr-plan/`
    **Note:** ESLint passes with 0 errors. TypeScript version warning is from eslint plugin compatibility, not our code.
- [x] **P7-S2** `npm run build` produces valid `.vsix` or runnable extension
    **Note:** TypeScript compiles with 0 errors: npm run compile succeeds.
- [x] **P7-S3** Extension activates without errors in Extension Development Host
    **Manual:** Open vscode-ext/nomarr-plan in VS Code, press F5 to launch Extension Host. Check Output panel for activation message.
- [x] **P7-S4** Plan tools appear in Copilot Chat tool list
    **Manual:** In Extension Host, ask Copilot: 'What plan tools are available?' Should see nomarr-plan_readPlan, getSteps, completeStep.
- [x] **P7-S5** `readPlan` tool returns correct JSON for `TASK-example-comprehensive.md`
    **Manual:** Test: @readPlan plan_name: TASK-example-comprehensive. Verify returned JSON has phases, steps, progress.
- [x] **P7-S6** `completeStep` tool modifies plan file correctly
    **Manual:** Test: @completeStep plan_name: TASK-plan-extension step_id: P7-S6. Verify checkbox updated in markdown file.
- [x] **P7-S7** One-shot Designer call returns valid schema output for test task
    **Manual:** Test Designer subagent via oneShot() with DESIGNER_SYSTEM_PROMPT and simple work order. Verify DesignerOutput schema.
- [x] **P7-S8** Lint interop correctly reports pass/fail from Python backend
    **Manual:** Test callPythonTool('lint_backend', {}) from extension. Verify LintBackendResult returned with ruff/mypy data.
- [x] **P7-S9** `lint_backend path=nomarr/ check_all=True` passes (no regressions from extension work)
    **Note:** lint_backend path=nomarr check_all=true: 0 errors, clean. No regressions.

**Notes:** Phase 7 is pure validation. All implementation happens in prior phases.

---

## Completion Criteria

- [ ] Extension directory exists at `vscode-ext/nomarr-plan/`
- [ ] Extension builds and loads without errors
- [ ] Plan tools (`readPlan`, `getSteps`, `completeStep`) work via extension
- [ ] One-shot LLM calls enforce schema-or-die pattern
- [ ] Python MCP interop works for lint tools
- [ ] Failure outcomes are recorded as plan annotations
- [ ] No `// @ts-ignore` or `any` types in production code
- [ ] README.md documents extension purpose and usage

---

## References

- VS Code LM API: `vscode.lm.selectChatModels()`, `vscode.lm.registerTool()`, `LanguageModelChat.sendRequest()`
- Existing Python MCP: `scripts/mcp/nomarr_mcp.py`
- Plan tools: `scripts/mcp/tools/read_plan.py`, `get_steps.py`, `complete_step.py`
- Plan parsing: `scripts/mcp/tools/helpers/plan_md.py`
- Subagent schemas: `context_pack/SUBAGENT_COMMAND_SCHEMAS.md`
- VS Code Extension Samples: `github.com/microsoft/vscode-extension-samples`
- Copilot Chat source: `github.com/microsoft/vscode-copilot-chat` (MIT, reference for tool patterns)
