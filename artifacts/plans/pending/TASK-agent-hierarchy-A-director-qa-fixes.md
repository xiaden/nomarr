# Task: Agent Hierarchy — Director Fix + QA Adjustments

## Problem Statement

The Director agent has a critical blindness bug: its YAML `agents` field lists only `[RnD-Manager, Exec-Planner, Exec-Manager]` but its body instructions reference spawning Support-Researcher (for file reading) and Support-Debugger (for failure analysis). This means Director literally cannot spawn agents it tells itself to spawn. Additionally, QA-Reviewer is only accessible via Exec-Manager's execution cycle — there's no way to commission an independent quality review.

This plan fixes Director's agents list, adds QA routing, and corrects inconsistent `user-invocable` settings across QA agents and test-probe.

**Prerequisite:** None (first plan in the set)

## Phases

### Phase 1: Fix Director Agent

- [ ] In `.github/agents/director.agent.md`, update the YAML `agents` field from `[RnD-Manager, Exec-Planner, Exec-Manager]` to `[RnD-Manager, Exec-Planner, Exec-Manager, QA-Reviewer, Support-Researcher, Support-Debugger]`
- [ ] In `.github/agents/director.agent.md`, update the `description` field to include QA-Reviewer in the spawn list (currently mentions Support-Researcher and Support-Debugger but not QA-Reviewer)
- [ ] In the Director's body routing table (the "Need → Agent" table), add a row: `"Review this code/PR"` → `**QA-Reviewer**`
- [ ] In the Director's "Multi-Plan Feature Workflow" section, add a step or note about QA-Reviewer availability for independent quality reviews outside the execution cycle
- [ ] Add a `handoff` entry for QA-Reviewer in the Director's YAML frontmatter handoffs section (e.g., label: "Review Quality", agent: QA-Reviewer)

### Phase 2: QA and Test Visibility Adjustments

- [ ] In `.github/agents/qa-reviewer.agent.md`, change `user-invocable: false` to `user-invocable: true` (or remove the field entirely since true is the default)
- [ ] In `.github/agents/qa-docs-analyzer.agent.md`, change `user-invocable: true` to `user-invocable: false`
- [ ] In `.github/agents/test-probe.agent.md`, add `user-invocable: false` to the YAML frontmatter
- [ ] Verify consistency: search all `.github/agents/*.agent.md` files for `user-invocable` settings and confirm they match the proposed state in the contracts ledger

## Completion Criteria

- Director's YAML `agents` list contains exactly 6 agents: RnD-Manager, Exec-Planner, Exec-Manager, QA-Reviewer, Support-Researcher, Support-Debugger
- Director's description and body content reference all 6 agents consistently
- Director has a QA routing path in its body
- QA-Reviewer is user-invocable (true or field absent)
- QA-DocsAnalyzer is NOT user-invocable (false)
- test-probe is NOT user-invocable (false)

## References

- Design doc: `plans/dev/design-agent-hierarchy-restructure.md` (Phase A, Problems 1-2, Problem 5)
- Contracts: `plans/dev/agent-hierarchy-parts/CONTRACTS.md`
- Parts README: `plans/dev/agent-hierarchy-parts/README.md`
- Siblings: B-qa-renames-docs-editor, C-shared-planner-rename, D-readme-rewrite
