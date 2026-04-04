# Task: Agent Hierarchy — QA Renames + New DocsEditor Agent

## Problem Statement

The `qa-subagent.agent.md` (name: "QA") is an orphan — not referenced by any agent in the hierarchy, has the `agent` tool despite no `agents` list, and its name risks confusion with the formal QA-Reviewer chain. It needs renaming to QA-Engineer with a clear standalone identity.

Separately, a standalone documentation editing workflow is needed. Currently, QA-DocsAnalyzer and QA-DocsGenerator are only accessible through QA-Reviewer's quality gate (part of the execution pipeline). Users who want to proactively write or improve documentation have no agent entry point. A new QA-DocsEditor agent will orchestrate docs analysis and generation with codebase research support.

**Prerequisite:** None (independent of Plan A)

## Phases

### Phase 1: Rename qa-subagent to QA-Engineer

- [ ] Create `.github/agents/qa-engineer.agent.md` based on `qa-subagent.agent.md` with these changes: name set to `QA-Engineer`, description updated to clarify standalone QA role ("Standalone QA engineer for..."), `agent` tool removed from tools list, `agents: []` added explicitly
- [ ] Delete `.github/agents/qa-subagent.agent.md`
- [ ] Search all files in `.github/` for any references to "qa-subagent" or the name "QA" (as an agent name) and verify no orphan references remain

### Phase 2: Create QA-DocsEditor Agent

- [ ] Create `.github/agents/qa-docs-editor.agent.md` with frontmatter: name `QA-DocsEditor`, description explaining standalone docs editing workflow, `user-invocable: true`, `agents: [QA-DocsAnalyzer, QA-DocsGenerator, Support-Researcher]`, tools including `agent`, read tools, edit tools, and `vscode/askQuestions`, plus handoffs to QA-DocsAnalyzer, QA-DocsGenerator, and Support-Researcher
- [ ] Write QA-DocsEditor body instructions covering: (1) workflow for analyzing existing docs, (2) workflow for creating new docs, (3) workflow for fixing doc/code drift, (4) dispatch patterns for sub-agents, (5) when to use Support-Researcher for codebase context
- [ ] Verify QA-DocsAnalyzer agent file accepts being spawned by a parent other than QA-Reviewer (check its instructions don't assume Exec-Manager execution context)
- [ ] Verify QA-DocsGenerator is compatible as a sub-agent of QA-DocsEditor (check its input contract works without QA-DocsAnalyzer as the only parent)

## Completion Criteria

- `qa-subagent.agent.md` no longer exists
- `qa-engineer.agent.md` exists with name "QA-Engineer", no `agent` tool, clear standalone description
- `qa-docs-editor.agent.md` exists with name "QA-DocsEditor", agents list `[QA-DocsAnalyzer, QA-DocsGenerator, Support-Researcher]`, user-invocable true
- QA-DocsEditor body instructions cover analysis, creation, and drift-fix workflows
- No references to "qa-subagent" or bare "QA" (as agent name) remain in `.github/`

## References

- Design doc: `plans/dev/design-agent-hierarchy-restructure.md` (Problem 5, Phase B)
- Contracts: `plans/dev/agent-hierarchy-parts/CONTRACTS.md`
- Parts README: `plans/dev/agent-hierarchy-parts/README.md`
- Siblings: A-director-qa-fixes, C-shared-planner-rename, D-readme-rewrite
