# Task: Agent Hierarchy — README Rewrite

## Problem Statement

The `.github/agents/README.md` documents the agent hierarchy, spawn chains, agent types, and rules. After Plans A, B, and C complete, the README is stale: Director has 6 agents (not 3), Exec-Planner is now Shared-Planner, QA-Engineer and QA-DocsEditor are new agents, user-invocable settings have changed, and there's no documentation for planning mechanisms, task routing, or shared resources.

This plan rewrites the README from scratch to reflect the final hierarchy state and adds three new sections: Planning Mechanisms, Task Routing Guide, and Shared Resources.

**Prerequisite:** TASK-agent-hierarchy-A-director-qa-fixes, TASK-agent-hierarchy-B-qa-renames-docs-editor, TASK-agent-hierarchy-C-shared-planner-rename

## Phases

### Phase 1: Update Existing Sections

- [ ] Rewrite the Architecture hierarchy tree to reflect: Director spawns 6 agents (including QA-Reviewer, Support-Researcher, Support-Debugger), Shared-Planner (renamed), QA-DocsEditor as new orchestrator of DocsAnalyzer + DocsGenerator + Support-Researcher, QA-Engineer as standalone leaf
- [ ] Update the Agent Types table: add QA-Engineer (renamed from qa-subagent), add QA-DocsEditor (new), rename Exec-Planner to Shared-Planner, update Director's Spawns column to 6 agents, update user-invocable status for QA-Reviewer (true), QA-DocsAnalyzer (false), test-probe (false)
- [ ] Update the Agent Definitions file listing section: rename exec-planner link to shared-planner, add qa-engineer and qa-docs-editor entries, remove qa-subagent reference, add test-probe with "test harness" note
- [ ] Update Hierarchy Rules: Director spawns 6, QA-DocsEditor orchestrates docs workflow, QA-DocsAnalyzer is internal-only (not user-invocable), Shared-Planner is a shared resource

### Phase 2: Add New Sections

- [ ] Add "Planning Mechanisms" section documenting: (1) `create-plan.prompt.md` for quick single plans, (2) `Shared-Planner` agent for plans from design docs, (3) `feature-planning` skill for multi-plan decomposition — with routing rules for when each is appropriate
- [ ] Add "Task Routing Guide" section with table: Quick fix → Agent (default), Design question → RnD-Manager, Create plan → Shared-Planner, Execute plan → execute-plan prompt, Quality review → QA-Reviewer, Investigate codebase → Support-Researcher, Debug failure → Support-Debugger, Write/improve docs → QA-DocsEditor, Full feature lifecycle → Director
- [ ] Add "Shared Resources" section documenting: Shared-Planner (multi-owner: Director, Exec-Manager, user), Support-Researcher (available to R&D, Planning, Director), Support-Debugger (available to Director, user) — explaining these cross department boundaries by design
- [ ] Verify the complete README by reading it end-to-end and confirming: no references to Exec-Planner, no references to qa-subagent, QA-DocsEditor appears in hierarchy tree + agent table + file listing, all user-invocable settings are consistent with actual agent files

## Completion Criteria

- README hierarchy tree matches actual YAML agents lists in all agent files
- Agent Types table includes all 24+ agents (22 original + QA-DocsEditor new - qa-subagent deleted = 23 total, counting README itself as documentation not an agent)
- Three new sections exist: Planning Mechanisms, Task Routing Guide, Shared Resources
- Zero references to `Exec-Planner`, `exec-planner`, or `qa-subagent`
- All file links resolve to existing `.agent.md` files
- Hierarchy Rules section is updated and numbered correctly

## References

- Design doc: `plans/dev/design-agent-hierarchy-restructure.md` (Phase C, Problem 6, Problem 7)
- Contracts: `plans/dev/agent-hierarchy-parts/CONTRACTS.md`
- Parts README: `plans/dev/agent-hierarchy-parts/README.md`
- Siblings: A-director-qa-fixes, B-qa-renames-docs-editor, C-shared-planner-rename
