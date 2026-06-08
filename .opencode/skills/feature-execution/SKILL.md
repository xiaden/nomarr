---
name: feature-execution
description: Use when executing implementation plans produced by the feature-planning skill. Orchestrates execution subagents (one plan phase at a time), dispatches review subagents for thorough quality enforcement after each plan, and manages fix cycles when review finds issues. Trigger when: (1) the user explicitly says "execute the plans", "implement the feature", or "work through the plans"; OR (2) the user asks to start implementation and every plan for the single feature being executed (all lettered plans A–Z for that specific feature slug, covering its full scope) exists and is schema-valid in artifacts/plans/pending/TASK-*-{A..Z}-*.md. Not for single-plan execution — use plan_complete_step directly for those.
---

# Feature Execution

Pipeline for implementing a set of feature plans produced by `feature-planning`. Uses hierarchical agent dispatch: Director → Exec-Manager → Executor/Reviewer/Fixer.

```
Plans + Ledger → Dispatch Exec-Manager → [internal: phases/review/fix] → Update Ledger → Next Plan → Archive
                        ↓                              ↓                      ↓                         ↓
                 One per plan              Exec-Manager handles           Director updates         COMPLETION.md
                                           execution lifecycle            CONTRACTS.md          → artifacts/plans/completed/
```

### Execution Decision Flowchart

**1. Check prerequisites:**
   - All plans present and schema-valid → proceed to step 2
   - Any missing or invalid → stop; run `feature-planning` or fix the plan first

**2. For each plan in dependency order, dispatch one Exec-Manager and handle the response:**
   - `DONE` → update the ledger (Phase 3), then return to step 2 for the next plan
   - `BLOCKED` → investigate the blocker; if resolvable provide guidance and re-dispatch; if not, stop and notify the user
   - `ESCALATE` → stop immediately; present the blocker to the user; do not retry

**3. When all plans have returned `DONE`:**
   - Archive the feature (Phase 5)

---

## Agent Hierarchy

The Director (you, executing this skill) dispatches **Exec-Manager** agents. Each Exec-Manager owns its plan's full lifecycle:

```
Director (you)
├── Exec-Manager A
│   ├── Executor (per phase)
│   ├── Reviewer (after all phases)
│   └── Fixer (if review finds issues)
├── Exec-Manager B
│   └── ... same structure
└── Handles: escalations, ledger updates, archival
```

**Key principle:** Exec-Managers own execution details. Director receives `DONE | BLOCKED | ESCALATE` — not phase-by-phase progress.

See [.opencode/agents/](.opencode/agents/) for agent specifications.

---

## Hard Rules

| Category | Rules | Purpose |
| --- | --- | --- |
| Dispatch Rules | 1–3 | Control how and when agents are invoked |
| Ledger & Session Rules | 4–5 | Ensure ledger accuracy and session continuity |
| Archival Rules | 6 | Keep working directories clean after completion |

### Dispatch Rules
_(Govern how agents are invoked and when to stop)_

1. **Never bypass Exec-Manager.** Dispatch one Exec-Manager per plan. Exec-Manager handles phases, review, and fix cycles internally. Don't dispatch Executors or Reviewers directly. *(Example: for Plan B, dispatch one Exec-Manager for Plan B — not separate Executor + Reviewer calls.)*
2. **Never ignore Exec-Manager escalations.** If Exec-Manager returns `ESCALATE`, stop and address the blocker. These are real problems, not optional. *(Example: 3+ failed fix rounds → stop, present to user, do not retry.)*
3. **Never execute out of dependency order.** Follow the execution rounds from the feature README. A plan that depends on Plan A's outputs cannot run before Plan A's Exec-Manager returns DONE. *(Example: if Plan B depends on Plan A, Plan B's Exec-Manager cannot be dispatched until Plan A is fully DONE.)*

### Ledger & Session Rules
_(Govern continuity and correctness of recorded contracts)_

4. **Update the ledger with actuals, not plans.** After Exec-Manager returns DONE, update CONTRACTS.md with *implemented* signatures from the codebase — which may differ from what was planned. *(Example: if the plan specified `create_item(id: int)` but the implementation used `create_item(item_id: str)`, record the latter.)*
5. **If context budget is exhausted, stop at a plan boundary.** The ledger and plan step checkboxes preserve all progress. A new session resumes cleanly. *(Example: finish Plan C's ledger update, then stop — do not start Plan D mid-session.)*

### Archival Rules
_(Govern clean-up after feature completion)_

6. **Never leave completed features unarchived.** After the last plan's Exec-Manager returns DONE plus ledger update, execute the archival protocol. *(Example: move all TASK-{feature}-*.md files and the DD to `completed/` as described in Phase 5.)*

---

## Prerequisites

Before starting execution:

1. Feature plans exist: `artifacts/plans/pending/TASK-{feature}-{A..Z}-*.md`
2. Parts README exists: `artifacts/designs/parts/{feature}/README.md`
3. Contracts ledger exists: `artifacts/designs/parts/{feature}/CONTRACTS.md`
4. All plans pass `plan_read` (schema-valid)

If any are missing, run `feature-planning` first.

**If a plan file is invalid or corrupted** (i.e., `plan_read` returns a parse error): log the error, notify the user, and ask them to regenerate the affected plan via `feature-planning` before proceeding. Do not attempt to execute a plan that cannot be parsed.

**If CONTRACTS.md is missing or corrupted:** notify the user and halt execution. Do not attempt to run any Exec-Manager until CONTRACTS.md is present and readable. Ask the user to regenerate it via `feature-planning` (Phase 2: Initialize Contracts Ledger) before proceeding.

---

## Phase 1: Prepare

1. Read the parts README — get execution rounds and dependency order
2. Read CONTRACTS.md — current state of implemented contracts
3. Check which plans have all steps completed (via `plan_read` or checkbox inspection)
4. Identify the next incomplete plan in dependency order

**Resuming a session:** Steps 1-4 are the full resume protocol. The ledger + plan checkboxes contain all state.

---

## Phase 2: Execute Plan

For each plan in dependency order, dispatch a Exec-Manager.

### 2a. Dispatch Exec-Manager

```yaml
# Dispatch to Exec-Manager agent
contextFiles:
  - artifacts/plans/pending/TASK-{feature}-{letter}-{title}.md    # The plan
  - artifacts/designs/parts/{feature}/CONTRACTS.md      # Current contracts
  - artifacts/designs/parts/{feature}/README.md         # Feature structure
  - artifacts/designs/pending/DD-{feature}.md               # Design doc
  - .github/instructions/{layers}.instructions.md  # Per layer in this plan

task:
  plan: "TASK-{feature}-{letter}-{title}"
  startPhase: 1         # Or resume from incomplete
  reviewRequired: true
```

**Exec-Manager handles internally:**

- Dispatching Executor per phase
- Running Reviewer after all phases complete
- Dispatching Fixer if review finds issues
- Fix cycles (up to 2 rounds, then escalates)

### 2b. Handle Exec-Manager Response

 | Status | Action |
 | -------- | -------- |
 | `DONE` | Proceed to Phase 3 (Update Ledger) |
 | `BLOCKED` | Investigate blocker. If resolvable, provide guidance and re-dispatch. If not, stop execution. |
 | `ESCALATE` | Stop. Present to user. Common causes: 3+ fix rounds, fundamental design issue, missing requirements. |

**Do NOT re-run Exec-Manager for DONE.** The plan is complete. Proceed to ledger update.

---

## Phase 3: Update Ledger

After Exec-Manager returns DONE:

1. **Update CONTRACTS.md** with *actual* implementations, not planned signatures
2. Use `read_module_api` / `read_module_source` to get real signatures from the codebase
3. Note any deviations from the original plan in the Decisions table
4. Date-stamp the update with the plan letter

**This is critical for downstream plans.** The next plan's Exec-Manager receives the ledger. Stale planned signatures cause cascading errors.

---

## Phase 4: Next Plan

Proceed to the next plan in dependency order. Return to Phase 2.

**Round boundaries:** When finishing the last plan in an execution round, all plans in that round should have their ledger entries updated before starting the next round.

---

## Phase 5: Archive Feature

After all plans' Exec-Managers return DONE, the ledger is updated, and the user is informed of any deviations — archive the feature.

See [references/archival-protocol.md](references/archival-protocol.md) for the full completion manifest template and move protocol.

### 5a. Generate Completion Manifest

Create `artifacts/designs/parts/{feature}/COMPLETION.md`:

1. **Execution Summary** — table of all plans with review round counts and fix plan references
2. **Design Deviations** — extracted from CONTRACTS.md Decisions table
3. **Key Decisions** — architectural decisions from plan annotations not in the design doc
4. **Files Created/Modified** — deduplicated from review reports, grouped by layer
5. **Final Lint Status** — run `lint_project_backend()` (and `lint_project_frontend()` if applicable) one final time

**Sources:** `plan_read` for completion status, CONTRACTS.md for deviations, plan step annotations for decisions, Exec-Manager artifacts for file lists.

### 5b. Move Artifacts to `artifacts/plans/completed/`

Use `edit_file_move` for each artifact:

 | Source | Destination |
 | --- | --- |
 | `artifacts/plans/pending/TASK-{feature}-*.md` | `artifacts/plans/completed/TASK-{feature}-*.md` |
 | `artifacts/designs/pending/DD-{feature}.md` | `artifacts/designs/completed/DD-{feature}.md` |
 | `artifacts/designs/parts/{feature}/` | `artifacts/designs/completed/{feature}/` |

Move plans and design doc first, parts directory last (it contains the manifest you just wrote).

### 5c. Verify Clean State

After moving:

- No `TASK-{feature}-*.md` files remain in `artifacts/plans/pending/`
- No `{feature}/` directory remains in `artifacts/designs/parts/`
- No `DD-{feature}.md` remains in `artifacts/designs/pending/`
- `artifacts/designs/completed/{feature}/COMPLETION.md` exists

**Standalone plans** (no letter suffix, no parts directory): just move the plan file. No manifest needed — the plan's own checkboxes and annotations are sufficient.

---

## Session Continuity

When starting a new session mid-feature:

1. Read `artifacts/designs/parts/{feature}/README.md` — execution rounds
2. Read `artifacts/designs/parts/{feature}/CONTRACTS.md` — implemented contracts
3. For each plan, run `plan_read` to check completion status
4. Identify state:
   - **Plan fully complete + ledger updated** → skip it (CONTRACTS.md has entries)
   - **Plan partially complete** → dispatch Exec-Manager with `startPhase: {next incomplete}`
   - **Plan not started** → check if all dependencies complete, then dispatch Exec-Manager
5. Resume at the appropriate phase

**The ledger is the source of truth for what's done.** If CONTRACTS.md has entries for Plan C's methods, Plan C's Exec-Manager returned DONE.

---

## Validation Checklist

Before declaring feature execution complete:

- [ ] All Exec-Managers returned DONE **→ Full implementation + review**
- [ ] CONTRACTS.md reflects actual implementations **→ No plan-vs-code drift**
- [ ] `lint_project_backend` passes on full workspace **→ Zero errors**
- [ ] No orphaned fix plans with incomplete steps **→ Clean state**
- [ ] User informed of any design deviations **→ Alignment**
- [ ] COMPLETION.md generated in `{feature}/` **→ Audit trail**
- [ ] All artifacts moved to `artifacts/plans/completed/` **→ Clean working directory**
- [ ] No feature files remain in `artifacts/plans/pending/` or `artifacts/designs/parts/` **→ Verified clean state**
