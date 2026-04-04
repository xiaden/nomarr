# Task: Agent Hierarchy — Shared-Planner Rename

## Problem Statement

The `Exec-Planner` agent has the `Exec-` prefix implying it belongs to the Execution department, but it's a shared resource used by Director (initial planning), Exec-Manager (plan amendments), and users directly. Per user decision, it should be renamed to `Shared-Planner` to set the naming pattern for shared-usage agents. The file becomes `shared-planner.agent.md`, the name becomes `Shared-Planner`, and ALL cross-references must be updated.

The rename touches 5 agent files plus 1 skill file. The README is excluded (handled by Plan D's full rewrite).

**Prerequisite:** TASK-agent-hierarchy-A-director-qa-fixes (Director's agents list was modified in Plan A; Plan C modifies it again for the rename)

## Phases

### Phase 1: Rename Core File

- [ ] Create `.github/agents/shared-planner.agent.md` as a copy of `exec-planner.agent.md` with `name` changed from `Exec-Planner` to `Shared-Planner`; update the handoff agent reference if it points to itself; verify all body content is preserved
- [ ] Delete `.github/agents/exec-planner.agent.md`

### Phase 2: Update All Cross-References

- [ ] In `.github/agents/director.agent.md`, replace all occurrences of `Exec-Planner` with `Shared-Planner` (description field, agents list, handoff agent, body routing table, workflow section, escalation routing — 7 occurrences total)
- [ ] In `.github/agents/exec-manager.agent.md`, replace `Exec-Planner` with `Shared-Planner` in the YAML `agents` list (1 occurrence)
- [ ] In `.github/agents/rnd-dd-author.agent.md`, replace `Exec-Planner` with `Shared-Planner` in the handoff agent field (1 occurrence)
- [ ] In `.github/agents/support-researcher.agent.md`, replace `Exec-Planner` with `Shared-Planner` in the body text (1 occurrence)
- [ ] In `.github/skills/feature-planning/SKILL.md`, update the comment `see .github/agents/planner.agent.md` to `see .github/agents/shared-planner.agent.md` (line 151, 1 occurrence)
- [ ] Search entire `.github/` directory and `plans/` directory for any remaining `Exec-Planner` or `exec-planner` references (case-insensitive) and update; confirm zero remaining references outside of README.md (which Plan D handles)

## Completion Criteria

- `exec-planner.agent.md` no longer exists
- `shared-planner.agent.md` exists with `name: Shared-Planner` and identical body/tools/handoffs
- Zero occurrences of `Exec-Planner` or `exec-planner` in `.github/agents/` files except `README.md`
- Zero occurrences in `.github/skills/` or `.github/instructions/`
- Director, Exec-Manager, RnD-DDAuthor, and Support-Researcher all reference `Shared-Planner`
- feature-planning SKILL.md references `shared-planner.agent.md`

## References

- Design doc: `plans/dev/design-agent-hierarchy-restructure.md` (Problem 3, Decision 4 override)
- Contracts: `plans/dev/agent-hierarchy-parts/CONTRACTS.md`
- Parts README: `plans/dev/agent-hierarchy-parts/README.md`
- Siblings: A-director-qa-fixes, B-qa-renames-docs-editor, D-readme-rewrite
