# ADR-005: Agent System Architecture and Artifact Management

**Status:** Accepted  
**Date:** 2026-04-03  
**Tags:** agents, tooling, code-intel, institutional-memory, architecture  
**Source Log:** exec-director#L2  

## Context

Nomarr development uses AI agents extensively. Without structure, agent conversations were ephemeral — decisions were made and forgotten, dead ends were repeated, and architectural choices had no persistent record. Agents had no defined roles, leading to inconsistent quality: sometimes an agent would plan and execute in the same pass, or skip review entirely. The code-intel MCP server had no tools for managing architectural artifacts (ADRs, design documents, logs).

## Decision

### Agent Hierarchy

Establish four departments with clear responsibilities and handoff patterns:

- **Exec** (Execution): Director, Manager, Executor, Fixer, Planner. Owns implementation lifecycle — planning, executing phases, reviewing, fixing.
- **QA** (Quality Assurance): Reviewer, TestAnalyzer, TestGenerator, DocsAnalyzer, DocsGenerator, QA subagent. Owns quality gates — lint, tests, docs, coverage.
- **RnD** (Research & Design): Manager, DDAuthor, Ideator, Architect, ComplexityAdvisor, Estimator, Improver. Owns the thinking phase — design documents, option analysis, estimation.
- **Support**: Researcher, Debugger, PatternEnforcer. Shared services — deep investigation, root cause analysis, consistency enforcement.

Agents are organized in `.github/agents/{Department}/` directories. Each agent has defined inputs, outputs, and spawn permissions (who it can call).

### Artifact Management

Code-intel MCP tools for persistent artifacts:

- **ADRs** (`adr_create`, `adr_read`, `adr_search`): Architectural Decision Records in `artifacts/decisions/`. Agents create ADRs when making decisions that constrain future work.
- **Design Documents** (`dd_create`, `dd_read`, `dd_archive`): Feature designs in `artifacts/designs/`. Lifecycle: pending → parts (decomposed) → completed.
- **Agent Logs** (`log_write`, `log_read`): Observations, discoveries, dead ends, blockers in `artifacts/logs/`. Agents log when they find something a future agent should know.
- **Plan Archive** (`plan_archive`): Moves completed plans from pending to completed.

All artifact parsers normalize EOL per ADR-002.

### Artifact Storage

`artifacts/` directory is gitignored except for structure (`.gitkeep` files) and plan examples. Artifact content is transient per-developer — ADRs that matter get promoted to committed documentation. The directory structure is committed so agents always have somewhere to write.

## Consequences

**Positive:**

- Institutional memory survives across conversations — dead ends, discoveries, and decisions are recorded
- Clear agent roles prevent quality shortcuts (executor can't skip review)
- ADR search before decisions prevents contradicting existing choices
- Log entries surface patterns across sessions (e.g., recurring blockers)

**Negative:**

- Agent system adds overhead for simple tasks (overkill for single-file changes)
- Artifact tools increase MCP server surface area
- Agents must be disciplined about logging (too much noise defeats the purpose)

**Deferred:**

- Automated ADR promotion (from artifacts/ to committed docs/)
- Cross-session agent memory beyond file artifacts
- Metrics/dashboards for agent activity

## References

- ADR-002: EOL normalization (applied to all artifact parsers)
- Agent definitions: .github/agents/{Exec,QA,RnD,Support}/
- Skills: .github/skills/{feature-planning,feature-execution}/
- Code-intel tools: code-intel/src/mcp_code_intel/tools/{adr,dd,log,plan}_*.py
