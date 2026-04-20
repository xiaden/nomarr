# Task: Agent YAML Updates — Wire New Tools to Agent Files

## Problem Statement

Plans A–E create nine new MCP tools (`dd_create`, `dd_read`, `dd_archive`, `adr_create`, `adr_read`, `adr_search`, `log_write`, `log_read`, `plan_archive`) but no agent file references them yet. The design document defines a per-agent mapping table specifying exactly which tools each agent receives. Until the `.agent.md` YAML `tools:` arrays are updated, no agent can invoke the new tools.

Additionally, agents granted `log_read` need chain-of-command scoping documentation so they only read logs from permitted agents (one level up and one level down in the hierarchy).

Agent files are organized in department subdirectories:

- Root: `agent.agent.md` (excluded), `director.agent.md`, `exec-manager.agent.md`, `rnd-manager.agent.md`
- `Exec/`: `exec-executor`, `exec-fixer`, `exec-planner`
- `QA/`: `qa-reviewer`, `qa-subagent`, `qa-test-analyzer`, `qa-test-generator`, `qa-docs-analyzer`, `qa-docs-generator`
- `RnD/`: `rnd-dd-author`, `rnd-ideator`, `rnd-architect`, `rnd-estimator`, `rnd-improver`, `rnd-complexity-advisor`
- `Support/`: `support-researcher`, `support-debugger`, `support-pattern-enforcer`

**Prerequisites:** TASK-agent-artifact-tools-A through E (all tools must exist before wiring)

## Phases

### Phase 1: Add New Tool References to Agent YAML Frontmatter

- [x] Update `.github/agents/Exec/exec-executor.agent.md` and `.github/agents/Exec/exec-fixer.agent.md`: append `nomarr_dev/log_write` to each `tools:` array (log-write-only execution agents)
- [x] Update RnD-Advisory agents (`.github/agents/RnD/rnd-ideator.agent.md`, `RnD/rnd-estimator.agent.md`, `RnD/rnd-complexity-advisor.agent.md`, `RnD/rnd-improver.agent.md`): append `nomarr_dev/adr_read`, `nomarr_dev/log_write` to each `tools:` array
- [x] Update `.github/agents/Support/support-pattern-enforcer.agent.md`: append `nomarr_dev/adr_read`, `nomarr_dev/log_write` to `tools:` array (shared support agent, same tool set as RnD-Advisory)
- [x] Update QA-Leaf agents (`.github/agents/QA/qa-subagent.agent.md`, `QA/qa-test-analyzer.agent.md`, `QA/qa-test-generator.agent.md`, `QA/qa-docs-analyzer.agent.md`, `QA/qa-docs-generator.agent.md`): append `nomarr_dev/log_write` to each `tools:` array
- [x] Update `.github/agents/Exec/exec-planner.agent.md`: append `nomarr_dev/dd_read`, `nomarr_dev/adr_search`, `nomarr_dev/adr_read`, `nomarr_dev/log_write` to `tools:` array
- [x] Update `.github/agents/QA/qa-reviewer.agent.md`: append `nomarr_dev/dd_read`, `nomarr_dev/adr_search`, `nomarr_dev/adr_read`, `nomarr_dev/log_write`, `nomarr_dev/log_read` to `tools:` array
- [x] Update `.github/agents/RnD/rnd-dd-author.agent.md`: append `nomarr_dev/dd_create`, `nomarr_dev/dd_read`, `nomarr_dev/adr_create`, `nomarr_dev/adr_read`, `nomarr_dev/log_write` to `tools:` array
- [x] Update `.github/agents/RnD/rnd-architect.agent.md`: append `nomarr_dev/dd_read`, `nomarr_dev/adr_create`, `nomarr_dev/adr_search`, `nomarr_dev/adr_read`, `nomarr_dev/log_write` to `tools:` array
- [x] Update `.github/agents/director.agent.md`: append `nomarr_dev/dd_read`, `nomarr_dev/adr_search`, `nomarr_dev/adr_read`, `nomarr_dev/log_read` to `tools:` array
- [x] Update `.github/agents/rnd-manager.agent.md`: append `nomarr_dev/dd_read`, `nomarr_dev/adr_search`, `nomarr_dev/adr_read`, `nomarr_dev/log_read`, `nomarr_dev/log_write` to `tools:` array
- [x] Update `.github/agents/exec-manager.agent.md`: append `nomarr_dev/dd_read`, `nomarr_dev/dd_archive`, `nomarr_dev/adr_search`, `nomarr_dev/adr_read`, `nomarr_dev/plan_archive`, `nomarr_dev/log_read`, `nomarr_dev/log_write` to `tools:` array
- [x] Update `.github/agents/Support/support-researcher.agent.md`: append `nomarr_dev/dd_read`, `nomarr_dev/adr_search`, `nomarr_dev/adr_read`, `nomarr_dev/log_write`, `nomarr_dev/log_read` to `tools:` array
- [x] Update `.github/agents/Support/support-debugger.agent.md`: append `nomarr_dev/adr_search`, `nomarr_dev/adr_read`, `nomarr_dev/log_write`, `nomarr_dev/log_read` to `tools:` array

### Phase 2: Add Log-Read Chain-of-Command Scoping Documentation

- [x] In `.github/agents/director.agent.md`: add a `## Log Access` section documenting that `log_read` is scoped to own logs plus `rnd-manager` and `exec-manager` (direct reports only)
- [x] In `.github/agents/rnd-manager.agent.md`: add a `## Log Access` section documenting that `log_read` is scoped to own logs, `director` (up), and all `rnd-*` agents (down)
- [x] In `.github/agents/exec-manager.agent.md`: add a `## Log Access` section documenting that `log_read` is scoped to own logs, `director` (up), `exec-executor`, `exec-fixer`, `exec-planner` (down)
- [x] In `.github/agents/QA/qa-reviewer.agent.md`: add a `## Log Access` section documenting that `log_read` is scoped to own logs, `exec-manager` (up), `exec-executor` (audit target), `qa-test-analyzer`, `qa-docs-analyzer` (down)
- [x] In `.github/agents/Support/support-researcher.agent.md`: add a `## Log Access` section documenting that `log_read` is scoped to own logs plus `director`, `rnd-manager`, `exec-manager` (manager-level)
- [x] In `.github/agents/Support/support-debugger.agent.md`: add a `## Log Access` section documenting that `log_read` is scoped to own logs plus `director`, `rnd-manager`, `exec-manager` (manager-level), `exec-executor` (audit target)

## Completion Criteria

- All 21 agent files (excluding `agent.agent.md`) have correct `tools:` arrays matching the design doc agent-to-tool mapping table
- All file paths use correct subdirectory structure (`Exec/`, `QA/`, `RnD/`, `Support/`; managers + director at root)
- All tool references use `nomarr_dev/{tool_name}` format (underscore-separated, not hyphenated)
- Every agent with `log_read` has a `## Log Access` section listing permitted agent names
- No agent has tools it shouldn't — `dd_create` only on RnD-DDAuthor, `adr_create` only on RnD-DDAuthor and RnD-Architect, archive tools only on Exec-Manager
- YAML frontmatter remains valid (parseable `---` blocks with correct array syntax)

## References

- Design doc: `plans/dev/design-agent-artifact-tools.md` (Agent-to-Tool Mapping table, Log-Read Chain-of-Command table)
- Contracts: `plans/dev/agent-artifact-tools-parts/CONTRACTS.md` (Agent YAML Tool References convention)
- Parts breakdown: `plans/dev/agent-artifact-tools-parts/README.md`
