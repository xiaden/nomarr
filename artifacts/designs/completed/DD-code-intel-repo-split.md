# Code-Intel Repository Split and Infrastructure Migration — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-04-24  

---

## Scope

cross-repo

---

## Problem Statement

Generic agentic coding infrastructure — agents, skills, hooks, generic instructions, and the MCP server — has accumulated inside the `nomarr` application repository. This violates separation of concerns: a self-hosted music library should not own general-purpose AI tooling. `code-intel` is already architecturally independent (its README says "designed to work with any Python codebase") but physically embedded. The goal is to extract `code-intel` into a standalone public GitHub repository that owns all generic agent infrastructure, while nomarr retains only music-library-domain content.

---

## Architecture

## Section 1: Target Folder Structure Inside `code-intel`

`code-intel` will be published as a standalone repo. Its root structure after migration:

```
code-intel/                          ← repo root (currently a subdirectory of nomarr)
├── src/                             ← MCP server Python package — UNCHANGED layout
│   └── mcp_code_intel/
│       ├── server.py
│       ├── tools/
│       ├── helpers/
│       ├── schemas/
│       └── __init__.py
├── hooks/                           ← moved from nomarr/.github/hooks/
│   ├── shared_context/              ← Python package — UNCHANGED internals
│   │   ├── __init__.py
│   │   ├── context_tools.py
│   │   ├── correlation.py
│   │   ├── normalizer.py
│   │   └── storage.py
│   ├── shared-context-pretooluse.py
│   ├── shared-context-pretooluse.json
│   ├── shared-context-posttooluse-all.py
│   ├── shared-context-posttooluse-all.json
│   ├── shared-context-posttooluse-runsubagent.py
│   ├── shared-context-posttooluse-runsubagent.json
│   ├── shared-context-subagentstart.py
│   ├── shared-context-subagentstart.json
│   ├── shared-context-subagentstop.py
│   ├── shared-context-subagentstop.json
│   ├── validate-runsubagent-agent.py
│   ├── validate-runsubagent-agent.json
│   ├── dump-hook-input.py
│   ├── README.md
│   ├── _probe_payloads.jsonl
│   ├── subagentstart-probe.json
│   ├── test-probe.json
│   └── tests/
│       ├── __init__.py
│       └── test_shared_context.py
├── agents/                          ← moved from nomarr/.github/agents/
│   ├── agent.agent.md
│   ├── director.agent.md
│   ├── exec-manager.agent.md
│   ├── rnd-manager.agent.md
│   ├── README.md
│   ├── Exec/
│   │   ├── exec-executor.agent.md
│   │   ├── exec-fixer.agent.md
│   │   └── exec-planner.agent.md
│   ├── QA/
│   │   ├── qa-docs-analyzer.agent.md
│   │   ├── qa-docs-generator.agent.md
│   │   ├── qa-reviewer.agent.md
│   │   ├── qa-subagent.agent.md
│   │   ├── qa-test-analyzer.agent.md
│   │   └── qa-test-generator.agent.md
│   ├── RnD/
│   │   ├── rnd-architect.agent.md
│   │   ├── rnd-complexity-advisor.agent.md
│   │   ├── rnd-dd-author.agent.md
│   │   ├── rnd-estimator.agent.md
│   │   ├── rnd-ideator.agent.md
│   │   └── rnd-improver.agent.md
│   └── Support/
│       ├── support-debugger.agent.md
│       ├── support-librarian.agent.md
│       ├── support-pattern-enforcer.agent.md
│       └── support-researcher.agent.md
├── skills/                          ← moved from nomarr/.github/skills/ (generic only)
│   ├── artifact-context/
│   ├── code-discovery/
│   ├── code-generation/
│   ├── code-migration/
│   ├── context7/
│   ├── copilot-hooks/
│   ├── copilot-sdk-python/
│   ├── doc-coauthoring/
│   ├── feature-execution/
│   ├── feature-planning/
│   ├── layer-workflows/             ← currently empty; placeholder for future generic skill
│   ├── mcp-builder/
│   ├── playwright-cli/
│   ├── quality-analysis/
│   ├── skill-creator/
│   └── skill-maintenance/
├── instructions/                    ← generic instructions (moved + newly created)
│   ├── copilot-base.md              ← NEW: generic section split from copilot-instructions.md
│   ├── agent-skills.instructions.md
│   ├── agents.instructions.md
│   ├── instructions.instructions.md
│   ├── prompt.instructions.md
│   ├── task-plans.instructions.md
│   └── use-cliche-data-in-docs.instructions.md
├── artifacts/                       ← code-intel own development workspace (fresh, empty)
│   ├── decisions/
│   ├── designs/
│   ├── logs/
│   ├── plans/
│   ├── requirements/
│   └── scratch/
├── schemas/                         ← already here — no change
│   ├── ADR_MARKDOWN_SCHEMA.json
│   └── PLAN_MARKDOWN_SCHEMA.json
├── docs/                            ← already here — no change
├── tests/                           ← already here — no change
├── config_schema.json               ← already here — no change
├── mcp_config.example.json          ← already here — no change
├── pyproject.toml                   ← stays at repo root — no change
└── README.md                        ← update to remove "Embedded in Nomarr Monorepo" status
```

### `pyproject.toml` location

`pyproject.toml` stays exactly where it is: `code-intel/pyproject.toml` in the nomarr workspace. When code-intel is a standalone repo, this file is at the repo root. No changes to path or content required.

### Hooks Python package resolution

Each hook `.py` script contains:
```python
HOOKS_DIR = Path(__file__).resolve().parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))
from shared_context import ...
```

`Path(__file__).resolve().parent` evaluates to the directory containing the script file — `code-intel/hooks/` after migration. `shared_context/` lives in that same directory. **No code changes are needed in any hook Python file.** Only the hook JSON command paths need updating (see Section 3).

---

## Section 2: Classification — What Moves vs What Stays

### `.github/skills/`

| File/Path | Move/Stay | Destination | Reason |
| ----------- | ----------- | ------------- | -------- |
| `artifact-context/` | **Move** | `code-intel/skills/artifact-context/` | Generic: agent artifact pattern for any project |
| `code-discovery/` | **Move** | `code-intel/skills/code-discovery/` | Generic: module discovery for any codebase |
| `code-generation/` | **Move** | `code-intel/skills/code-generation/` | Generic: scaffolding for any project |
| `code-migration/` | **Move** | `code-intel/skills/code-migration/` | Generic: refactor/migration pattern |
| `context7/` | **Move** | `code-intel/skills/context7/` | Generic: third-party doc fetching |
| `copilot-hooks/` | **Move** | `code-intel/skills/copilot-hooks/` | Generic: VS Code hook authoring guide |
| `copilot-sdk-python/` | **Move** | `code-intel/skills/copilot-sdk-python/` | Generic: Copilot Python SDK guide |
| `doc-coauthoring/` | **Move** | `code-intel/skills/doc-coauthoring/` | Generic: documentation workflow |
| `docker/` | **Stay** | `.github/skills/docker/` | Nomarr-specific: references Nomarr Docker credentials, ArangoDB ports, AQL queries |
| `feature-execution/` | **Move** | `code-intel/skills/feature-execution/` | Generic: agent execution pipeline |
| `feature-planning/` | **Move** | `code-intel/skills/feature-planning/` | Generic: design-to-plan pipeline |
| `layer-workflows/` | **Move** | `code-intel/skills/layer-workflows/` | Empty placeholder; moves with generic infra |
| `mcp-builder/` | **Move** | `code-intel/skills/mcp-builder/` | Generic: MCP server construction guide |
| `playwright-cli/` | **Move** | `code-intel/skills/playwright-cli/` | Generic: browser automation |
| `quality-analysis/` | **Move** | `code-intel/skills/quality-analysis/` | Generic: code quality checks |
| `skill-creator/` | **Move** | `code-intel/skills/skill-creator/` | Generic: skill authoring meta-skill |
| `skill-maintenance/` | **Move** | `code-intel/skills/skill-maintenance/` | Generic: skill validation tooling |

### `.github/agents/`

All 24 agent files are generic (none reference nomarr layers, ArangoDB, or music domain):

| File/Path | Move/Stay | Destination | Reason |
| ----------- | ----------- | ------------- | -------- |
| `agent.agent.md` | **Move** | `code-intel/agents/` | Generic default agent |
| `director.agent.md` | **Move** | `code-intel/agents/` | Generic orchestrator |
| `exec-manager.agent.md` | **Move** | `code-intel/agents/` | Generic plan lifecycle manager |
| `rnd-manager.agent.md` | **Move** | `code-intel/agents/` | Generic R&D department head |
| `README.md` | **Move** | `code-intel/agents/` | Agent catalog docs |
| `Exec/exec-executor.agent.md` | **Move** | `code-intel/agents/Exec/` | Generic plan executor |
| `Exec/exec-fixer.agent.md` | **Move** | `code-intel/agents/Exec/` | Generic review fixer |
| `Exec/exec-planner.agent.md` | **Move** | `code-intel/agents/Exec/` | Generic plan creator |
| `QA/qa-docs-analyzer.agent.md` | **Move** | `code-intel/agents/QA/` | Generic docs QA |
| `QA/qa-docs-generator.agent.md` | **Move** | `code-intel/agents/QA/` | Generic docs generator |
| `QA/qa-reviewer.agent.md` | **Move** | `code-intel/agents/QA/` | Generic quality gate |
| `QA/qa-subagent.agent.md` | **Move** | `code-intel/agents/QA/` | Generic QA subagent |
| `QA/qa-test-analyzer.agent.md` | **Move** | `code-intel/agents/QA/` | Generic test analysis |
| `QA/qa-test-generator.agent.md` | **Move** | `code-intel/agents/QA/` | Generic test generation |
| `RnD/rnd-architect.agent.md` | **Move** | `code-intel/agents/RnD/` | Generic options analyst |
| `RnD/rnd-complexity-advisor.agent.md` | **Move** | `code-intel/agents/RnD/` | Generic complexity analysis |
| `RnD/rnd-dd-author.agent.md` | **Move** | `code-intel/agents/RnD/` | Generic design doc author |
| `RnD/rnd-estimator.agent.md` | **Move** | `code-intel/agents/RnD/` | Generic effort estimator |
| `RnD/rnd-ideator.agent.md` | **Move** | `code-intel/agents/RnD/` | Generic ideation |
| `RnD/rnd-improver.agent.md` | **Move** | `code-intel/agents/RnD/` | Generic improvement suggestions |
| `Support/support-debugger.agent.md` | **Move** | `code-intel/agents/Support/` | Generic debugger |
| `Support/support-librarian.agent.md` | **Move** | `code-intel/agents/Support/` | Generic artifact navigator |
| `Support/support-pattern-enforcer.agent.md` | **Move** | `code-intel/agents/Support/` | Generic consistency propagator |
| `Support/support-researcher.agent.md` | **Move** | `code-intel/agents/Support/` | Generic codebase researcher |

### `.github/hooks/`

All hook files are generic (hooks capture agent lifecycle events, not nomarr domain logic):

| File/Path | Move/Stay | Destination | Reason |
| ----------- | ----------- | ------------- | -------- |
| `shared_context/` (package) | **Move** | `code-intel/hooks/shared_context/` | Core hook logic; generic agent context tracking |
| `shared-context-pretooluse.py` | **Move** | `code-intel/hooks/` | Generic: intercepts runSubagent tool calls |
| `shared-context-pretooluse.json` | **Move** | `code-intel/hooks/` | Hook config; command path updated (see Section 3) |
| `shared-context-posttooluse-all.py` | **Move** | `code-intel/hooks/` | Generic PostToolUse handler |
| `shared-context-posttooluse-all.json` | **Move** | `code-intel/hooks/` | Hook config; command path updated |
| `shared-context-posttooluse-runsubagent.py` | **Move** | `code-intel/hooks/` | Generic: captures runSubagent output |
| `shared-context-posttooluse-runsubagent.json` | **Move** | `code-intel/hooks/` | Hook config; command path updated |
| `shared-context-subagentstart.py` | **Move** | `code-intel/hooks/` | Generic: subagent lifecycle |
| `shared-context-subagentstart.json` | **Move** | `code-intel/hooks/` | Hook config; command path updated |
| `shared-context-subagentstop.py` | **Move** | `code-intel/hooks/` | Generic: subagent lifecycle |
| `shared-context-subagentstop.json` | **Move** | `code-intel/hooks/` | Hook config; command path updated |
| `validate-runsubagent-agent.py` | **Move** | `code-intel/hooks/` | Generic: validates agent names |
| `validate-runsubagent-agent.json` | **Move** | `code-intel/hooks/` | Hook config; command path updated |
| `dump-hook-input.py` | **Move** | `code-intel/hooks/` | Dev utility; generic |
| `README.md` | **Move** | `code-intel/hooks/` | Hook documentation |
| `_probe_payloads.jsonl` | **Move** | `code-intel/hooks/` | Test data |
| `subagentstart-probe.json` | **Move** | `code-intel/hooks/` | Test config |
| `test-probe.json` | **Move** | `code-intel/hooks/` | Test config |
| `tests/` | **Move** | `code-intel/hooks/tests/` | Hook unit tests |
| `__pycache__/` | **Delete** | — | Never committed |

### `.github/instructions/`

| File | Move/Stay | Destination | Reason |
| ------ | ----------- | ------------- | -------- |
| `agent-skills.instructions.md` | **Move** | `code-intel/instructions/` | Generic: applies to `**/.github/skills/**/SKILL.md` |
| `agents.instructions.md` | **Move** | `code-intel/instructions/` | Generic: applies to `**/*.agent.md` |
| `components.instructions.md` | **Stay** | `.github/instructions/` | Nomarr: `applyTo: nomarr/components/**` |
| `frontend.instructions.md` | **Stay** | `.github/instructions/` | Nomarr: `applyTo: frontend/**` |
| `helpers.instructions.md` | **Stay** | `.github/instructions/` | Nomarr: `applyTo: nomarr/helpers/**` |
| `instructions.instructions.md` | **Move** | `code-intel/instructions/` | Generic: applies to all `*.instructions.md` |
| `interfaces.instructions.md` | **Stay** | `.github/instructions/` | Nomarr: `applyTo: nomarr/interfaces/**` |
| `mcp-basics.instructions.md` | **Stay** | `.github/instructions/` | applyTo path is nomarr-specific (`scripts/mcp/**`) |
| `mcp-tools.instructions.md` | **Stay** | `.github/instructions/` | applyTo path is nomarr-specific (`scripts/mcp/tools/**`) |
| `persistence.instructions.md` | **Stay** | `.github/instructions/` | Nomarr: `applyTo: nomarr/persistence/**` |
| `prompt.instructions.md` | **Move** | `code-intel/instructions/` | Generic: applies to `**/*.prompt.md` |
| `services.instructions.md` | **Stay** | `.github/instructions/` | Nomarr: `applyTo: nomarr/services/**` |
| `task-plans.instructions.md` | **Move** | `code-intel/instructions/` | Generic: applies to `artifacts/plans/**` |
| `testing-backend.instructions.md` | **Stay** | `.github/instructions/` | Nomarr pytest patterns |
| `testing-e2e.instructions.md` | **Stay** | `.github/instructions/` | References Nomarr Docker environment |
| `testing-frontend.instructions.md` | **Stay** | `.github/instructions/` | Nomarr frontend test patterns |
| `use-cliche-data-in-docs.instructions.md` | **Move** | `code-intel/instructions/` | Generic: applies to `**/*.md` |
| `workflows.instructions.md` | **Stay** | `.github/instructions/` | Nomarr: `applyTo: nomarr/workflows/**` |

### `artifacts/` subdirectories

The `artifacts/` directory is the workspace for the MCP server tools. Artifact content is project-specific — nomarr's ADRs document nomarr design decisions, not code-intel design decisions. Artifact content does not move. Code-intel will get its own fresh `artifacts/` directory.

| Subdirectory | Move/Stay | Reason |
| ------------- | ----------- | -------- |
| `artifacts/decisions/` (ADR-001 to ADR-028) | **Stay in nomarr** | All ADRs document nomarr domain (ML inference, ArangoDB, FastAPI, music library). ADR-005 documents the agent system but was authored in the context of nomarr development. |
| `artifacts/designs/` | **Stay in nomarr** | All DDs document nomarr features or nomarr agent development. |
| `artifacts/logs/` | **Stay in nomarr** | Agent logs document nomarr development sessions; not generically reusable. |
| `artifacts/plans/` | **Stay in nomarr** | All plans target nomarr features. |
| `artifacts/requirements/` | **Stay in nomarr** | ASRs document nomarr architectural requirements. |
| `artifacts/scratch/` | **Stay in nomarr** | Working scratch area; project-specific. |

Code-intel gets a fresh `artifacts/` at its repo root, populated only as code-intel's own development progresses.

### `code-intel/` current contents

| Path | Move/Stay | Destination | Reason |
| ------ | ----------- | ------------- | -------- |
| `src/mcp_code_intel/` | **Stay** | `src/mcp_code_intel/` | Already in correct layout for standalone repo |
| `pyproject.toml` | **Stay** | repo root | Already at correct location |
| `config_schema.json` | **Stay** | repo root | Already in correct location |
| `mcp_config.example.json` | **Stay** | repo root | Already in correct location |
| `schemas/` | **Stay** | `schemas/` | Already in correct location |
| `docs/` | **Stay** | `docs/` | Already in correct location |
| `tests/` | **Stay** | `tests/` | Already in correct location |
| `README.md` | **Stay** (update content) | repo root | Remove "Embedded in Nomarr Monorepo" section |
| `plans/` | **Stay** (empty) | `plans/` | Becomes code-intel own plan directory |
| `instructions/` (existing) | **Stay** (merge with migrations) | `instructions/` | Already contains `task-plans.md` and `examples/` |

### `.github/copilot-instructions.md`

Does not move wholesale. Splits:
- **Generic sections** → `code-intel/instructions/copilot-base.md` (new file)
- **Nomarr-specific sections** → remain in `.github/copilot-instructions.md`

See Section 7 for the exact split.

---

## Section 3: VS Code Settings Changes

### Current `nomarr.code-workspace` (relevant keys)

```json
{
  "settings": {
    "chat.agentFilesLocations": {
      ".github/agents/Exec": true,
      ".github/agents/QA": true,
      ".github/agents/RnD": true,
      ".github/agents/Support": true
    }
  }
}
```

No `chat.hookFilesLocations` key — VS Code auto-discovers hook JSON files from `.github/hooks/` by default.
No explicit instruction or skill path settings — VS Code auto-discovers from `.github/instructions/` and `.github/skills/`.

### After migration

```json
{
  "settings": {
    "chat.agentFilesLocations": {
      "code-intel/agents": true,
      "code-intel/agents/Exec": true,
      "code-intel/agents/QA": true,
      "code-intel/agents/RnD": true,
      "code-intel/agents/Support": true
    },
    "chat.hookFilesLocations": {
      "code-intel/hooks": true
    },
    "chat.agentSkillsLocations": {
      "code-intel/skills": true
    },
    "chat.instructionsFilesLocations": {
      "code-intel/instructions/copilot": true
    },
    "chat.useCustomAgentHooks": true
  }
}
```

All paths are workspace-relative and resolve correctly because `code-intel` is a submodule at `code-intel/` within the nomarr workspace root.

### Hook JSON command paths — before and after

Every hook JSON file currently uses workspace-relative paths to the hooks directory. **Six JSON files** require command path updates:

**Before (example: `shared-context-pretooluse.json`):**
```json
{
  "hooks": {
    "PreToolUse": [{
      "type": "command",
      "command": "python .github/hooks/shared-context-pretooluse.py",
      "windows": "py -3 .github/hooks/shared-context-pretooluse.py",
      "timeout": 15
    }]
  }
}
```

**After (all `.json` hook configs — paths updated to `code-intel/hooks/`):**
```json
{
  "hooks": {
    "PreToolUse": [{
      "type": "command",
      "command": "python code-intel/hooks/shared-context-pretooluse.py",
      "windows": "py -3 code-intel/hooks/shared-context-pretooluse.py",
      "timeout": 15
    }]
  }
}
```

Affected files (update command path in each):
1. `shared-context-pretooluse.json` — `PreToolUse`
2. `shared-context-posttooluse-all.json` — `PostToolUse`
3. `shared-context-posttooluse-runsubagent.json` — `PostToolUse`
4. `shared-context-subagentstart.json` — `SubagentStart`
5. `shared-context-subagentstop.json` — `SubagentStop`
6. `validate-runsubagent-agent.json` — `PreToolUse`

### Skills and instructions discovery — confirmed settings

Research (4/24/2026) confirms all four discovery mechanisms have VS Code settings. No stubs needed.

| File type | Setting | Recursion | Default path |
| ----------- | --------- | ----------- | ------------- |
| Hooks | `chat.hookFilesLocations` | No | `.github/hooks` |
| Agents | `chat.agentFilesLocations` | No (enumerate subdirs) | `.github/agents` |
| Skills | `chat.agentSkillsLocations` | No (points to parent of skill dirs) | `.github/skills` |
| Instructions | `chat.instructionsFilesLocations` | **Yes** | `.github/instructions` |

All settings accept `{ [relativePath: string]: boolean }`. Submodule paths are transparently supported — VS Code resolves filesystem paths only, with no git-submodule awareness.

**`copilot-instructions.md` cannot be moved.** `.github/copilot-instructions.md` is hardcoded — there is no discovery setting for it. It must remain at that exact path in nomarr.

### Updated target workspace settings

```json
{
  "settings": {
    "chat.agentFilesLocations": {
      "code-intel/agents": true,
      "code-intel/agents/Exec": true,
      "code-intel/agents/QA": true,
      "code-intel/agents/RnD": true,
      "code-intel/agents/Support": true
    },
    "chat.hookFilesLocations": {
      "code-intel/hooks": true
    },
    "chat.agentSkillsLocations": {
      "code-intel/skills": true
    },
    "chat.instructionsFilesLocations": {
      "code-intel/instructions/copilot": true
    },
    "chat.useCustomAgentHooks": true
  }
}
```

Note: `chat.instructionsFilesLocations` points to `code-intel/instructions/copilot/` (a subfolder) to keep Copilot `.instructions.md` files separate from the MCP documentation files that already live in `code-intel/instructions/`. Instructions discovery is recursive so a subfolder works cleanly.

**Open question — prompt files:** No `chat.promptFilesLocations` setting was found in the docs. If `.github/prompts/` needs to migrate, a fallback (stub files or symlinks) will be needed. This is out of scope for the initial migration.

---

## Section 4: Submodule / Reference Pattern

### Current state

No `code-intel` submodule exists. Only one submodule is configured in `.gitmodules`:
```ini
[submodule "build_resources/essentia"]
    path = build_resources/essentia
    url = https://github.com/xiaden/essentia.git
    branch = nomarr
```

### Recommendation: Git submodule at `code-intel/`

**Decision:** Reference code-intel as a git submodule at path `code-intel/` inside nomarr.

**Rationale:**
- `code-intel/` already occupies exactly this path in the nomarr workspace. After extraction, the submodule replaces the embedded directory transparently.
- All VS Code workspace settings already use `code-intel/...` paths. No path remapping needed.
- Git submodule pins a specific commit of code-intel in nomarr's repository, enabling independent versioning.
- The MCP server's `pyproject.toml` and `mcp_config.json` references (e.g., `"nomarr"` and `"code-intel/src/mcp_code_intel"` in search paths) require no changes.

### Fresh clone requirement

Git submodules are not checked out by default on `git clone`. To satisfy the "zero manual setup" constraint:

1. Document `git clone --recurse-submodules` in nomarr's README as the canonical clone command.
2. For developers who cloned without `--recurse-submodules`, provide: `git submodule update --init`.
3. Consider adding a setup task (`Makefile` or `.vscode/tasks.json`) that runs `git submodule update --init`.

Note: VS Code shows a notification when submodules are not initialized if `git.detectSubmodules` is enabled (default: true), providing a visual cue.

---

## Section 5: `.gitignore` / `.gitmodules` Changes

### `.gitmodules` — add entry

**Add** the following entry to `d:\Github\nomarr\.gitmodules`:

```ini
[submodule "code-intel"]
    path = code-intel
    url = https://github.com/nomarr-dev/code-intel.git
    branch = main
```

The existing `build_resources/essentia` entry is unchanged.

### `.gitignore` — verify no blocking entries

Git submodules are tracked as special objects (a commit SHA reference), not as regular files. The current nomarr `.gitignore` does not need entries for `code-intel/`. However, **verify** that nomarr's root `.gitignore` does NOT contain any entry like `code-intel/` or `/code-intel` that would suppress the submodule. If such an entry exists, remove it.

### code-intel standalone `.gitignore`

Create `code-intel/.gitignore` at the repo root:

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
dist/
build/
.mypy_cache/
.ruff_cache/

# Hook runtime cache
hooks/__pycache__/

# MCP config (project-specific)
mcp_config.json

# IDE
.vscode/settings.json
```

### `artifacts/scratch/shared-context/` — check nomarr `.gitignore`

Hooks write runtime data to `artifacts/scratch/shared-context/` relative to the workspace root. After migration hooks live in code-intel but still write to the nomarr workspace `artifacts/scratch/`. Verify `artifacts/.gitignore` excludes this transient directory if it is not meant to be committed.

---

## Section 6: Migration Sequence

The invariant: **agents, skills, hooks, and instructions must be functional at every step.** No broken window state.

### Phase 1 — Preparation (no user-visible changes)

1. Create the `code-intel` GitHub repository at the public URL (e.g., `https://github.com/nomarr-dev/code-intel`).
2. Push the current `code-intel/` directory content as the initial commit (includes all existing `src/`, `tests/`, `docs/`, `schemas/`, `pyproject.toml`, `config_schema.json`, `mcp_config.example.json`, `README.md`, `plans/`, `instructions/`).
3. Update `code-intel/README.md`: remove the "Embedded in Nomarr Monorepo" status section; describe it as a standalone public tool.
4. Create empty target directories in the new code-intel repo: `hooks/`, `agents/`, `skills/`, `artifacts/` with subdirs.

### Phase 2 — Move files to code-intel (committed there before removing from nomarr)

**2a. Move hooks:**
- Copy all files from `nomarr/.github/hooks/` to `code-intel/hooks/`.
- In each of the 6 hook JSON files (now in `code-intel/hooks/`), update the `command` and `windows` paths from `.github/hooks/<file>.py` to `code-intel/hooks/<file>.py`.
- Commit to code-intel repo.

**2b. Move agents:**
- Copy all files from `nomarr/.github/agents/` to `code-intel/agents/`, preserving subdirectory structure (Exec/, QA/, RnD/, Support/).
- Commit to code-intel repo.

**2c. Move generic skills:**
- Copy all skill directories listed as "Move" in Section 2 from `nomarr/.github/skills/` to `code-intel/skills/`.
- Commit to code-intel repo.

**2d. Move generic instructions:**
- Copy the 7 instruction files listed as "Move" in Section 2 from `nomarr/.github/instructions/` to `code-intel/instructions/`.
- Commit to code-intel repo.

**2e. Create `code-intel/instructions/copilot-base.md`:**
- Extract the generic sections from `nomarr/.github/copilot-instructions.md` (see Section 7) into a new file at `code-intel/instructions/copilot-base.md`.
- Commit to code-intel repo.

### Phase 3 — Convert `code-intel/` subdirectory to submodule (atomic step)

Do not split this across sessions.

```bash
# Remove code-intel/ from nomarr's git tracking
git rm -r --cached code-intel/

# Add as submodule
git submodule add https://github.com/nomarr-dev/code-intel.git code-intel
git submodule update --remote code-intel

# Commit
git add .gitmodules code-intel
git commit -m "Convert code-intel subdirectory to git submodule"
```

Verify `code-intel/` is populated at the correct commit including all moved files.

### Phase 4 — Update VS Code settings (immediately after Phase 3)

- Update `nomarr.code-workspace` with new settings (see Section 3 "After migration" JSON).
- Reload VS Code window.
- Verify all 24 agents appear in the agent selector.
- Trigger a hook event; verify it executes without path errors.
- Confirm `copilot-base.md` instructions are applied in a chat session (open a file covered by a generic instruction and verify the instruction appears in context).

### Phase 5 — Clean up nomarr `.github/` and split copilot-instructions.md

**5a. Update `nomarr/.github/copilot-instructions.md`:** Remove generic sections that moved to `copilot-base.md`; add reference header (see Section 7).

**5b. Remove moved agents** from `nomarr/.github/agents/`: Delete Exec/, QA/, RnD/, Support/ subdirectories and top-level agent files. Keep `.github/agents/` as an empty directory for potential future nomarr-specific agents.

**5c. Remove moved hooks** from `nomarr/.github/hooks/`: Delete all `.py`, `.json`, `.jsonl`, and `shared_context/` content. VS Code will now find hooks via `chat.hookFilesLocations` pointing to `code-intel/hooks`.

**5d. Remove moved skills** from `nomarr/.github/skills/`: Delete the 16 generic skill directories. Keep `docker/` in place. Skills are discovered via `chat.agentSkillsLocations` pointing to `code-intel/skills/` — no stubs needed.

**5e. Remove moved instructions** from `nomarr/.github/instructions/`: Delete the 7 generic instruction files that moved to `code-intel/instructions/`.

**5f. Commit all nomarr cleanup changes.**

### Phase 6 — End-to-end verification

- All 24 agent files load in VS Code agent selector.
- Hook event triggers and executes; `artifacts/scratch/shared-context/` receives output.
- `docker` skill still appears for nomarr Docker work.
- `git submodule status` shows code-intel at expected commit.
- Simulate fresh clone: `git clone --recurse-submodules <nomarr-url>`; verify agents and hooks are immediately functional.

---

## Section 7: `copilot-instructions.md` Split

### What stays in `nomarr/.github/copilot-instructions.md`

Keep sections that directly reference nomarr domain, architecture, or technology:

1. **Alpha Development Policy** (entire section) — references nomarr migrations, `ensure_schema`, ArangoDB, FastAPI, `nomarr/migrations/`
2. **Dependency Direction** (entire section) — describes nomarr's specific layer hierarchy (interfaces → services → workflows → components → persistence/helpers) and import-linter enforcement
3. **Hard Rules — Nomarr-specific rules only:**
   - Import `essentia` restrictions (specific file paths in nomarr)
   - Rename `_id` or `_key` prohibition (ArangoDB-native identifiers)
   - Let workflows import services or interfaces (nomarr layer enforcement)
   - Let helpers import any `nomarr.*` modules (nomarr module guard)

After trimming, `nomarr/.github/copilot-instructions.md` opens with:

```markdown
# Copilot Instructions for Nomarr

> Generic agent policy (artifact logging, ADR workflow, hard rules for context
> management, dependency injection, typed code) is in
> `code-intel/instructions/copilot-base.md` and is loaded automatically via
> workspace settings. This file contains only Nomarr-specific rules.

---
```

### What moves to `code-intel/instructions/copilot-base.md`

Extract these sections verbatim:

1. **Hard Rules — generic rules:**
   - Read config or env vars at module import time
   - Create or mutate global state
   - Guess context or line counts in tool usage
   - Spawn built-in VS Code agents (`Explore`, `default`) via `runSubagent`
   - Assume context will be lost or "run out" (the context compaction explanation)
   - Use dependency injection for major resources
   - Write fully type-annotated code
   - Use MCP `read_module_api` before calling unfamiliar APIs
   - Check venv is active before running Python commands
   - Reread context if a tool errors
   - Write git commit messages as a single subject line

2. **Entire Artifact Logging & ADR Policy section** — 100% generic agent infrastructure policy applicable to any project using the code-intel toolchain.

### Loading mechanism

`copilot-base.md` is loaded via `github.copilot.chat.codeGeneration.instructions` in `nomarr.code-workspace`:

```json
"github.copilot.chat.codeGeneration.instructions": [
  {"file": "code-intel/instructions/copilot-base.md"}
]
```

This instructs VS Code Copilot to include `copilot-base.md` alongside the auto-discovered `.github/copilot-instructions.md`. Both files are active simultaneously in agent mode.

---

## Design Goals

1. Extract `code-intel` into a standalone public GitHub repository with no nomarr dependencies.
2. Move all generic agentic coding infrastructure (agents, skills, hooks, generic instructions, MCP server) into code-intel.
3. Nomarr retains only music-library-domain content in `.github/`.
4. Fresh clone of nomarr gives VS Code full agent/hook/skill functionality with one additional command (`git submodule update --init`).
5. Hooks continue to function without Python code changes after path migration.

---

## Constraints

- VS Code Copilot auto-discovers skills and instructions only from `.github/skills/` and `.github/instructions/`. There is no confirmed `chat.skillFilesLocations` or `chat.instructionsFilesLocations` setting.
- Hook Python scripts must not require code changes — only the hook JSON command paths change.
- No agent must be unavailable at any point during the migration sequence.
- `pyproject.toml` in code-intel must remain at the repo root (not moved to a subdirectory).
- `mcp_config.json` in the nomarr workspace root references `code-intel/src/mcp_code_intel` in search paths — this path is unchanged after the submodule conversion.

---

## Open Questions

1. **VS Code skill/instruction discovery from non-.github paths:** Does VS Code Copilot support `chat.skillFilesLocations` or `chat.instructionsFilesLocations` settings? If not, the stub-file approach must be used for moved skills/instructions. Verify against VS Code release notes or API docs before implementation.
2. **`github.copilot.chat.codeGeneration.instructions` in agent mode:** Does this workspace setting apply to agent sessions (not just code-gen)? If it only applies to code generation suggestions, a different mechanism is needed to load `copilot-base.md` in agent sessions.
3. **Submodule branch pinning strategy:** Should nomarr pin code-intel to a specific commit (default submodule behavior), or track `main` with `branch = main` in `.gitmodules`? Pinning is safer but requires manual updates; tracking main auto-updates but can introduce breaking changes.
4. **`validate-runsubagent-agent.py` agent list:** This hook validates agent names. If the list is hardcoded rather than dynamically discovered from the agents directory, it will need updating after agent files move. Verify before implementation.
5. **`artifacts/scratch/shared-context/` path for standalone code-intel:** When code-intel standalone developers use the hooks in their own workspace, the hooks still write to `artifacts/scratch/shared-context/` relative to the workspace root. Ensure the fresh `artifacts/scratch/` in the code-intel repo is included in `.gitignore` appropriately.

---
