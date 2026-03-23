---
name: feature-execution
description: Use when executing implementation plans produced by the feature-planning skill. Orchestrates execution subagents (one plan phase at a time), dispatches review subagents for thorough quality enforcement after each plan, and manages fix cycles when review finds issues. Trigger when user says "execute the plans", "implement the feature", "work through the plans", or when validated plans exist in plans/TASK-*-{A..Z}-*.md and need implementation. Not for single-plan execution — use plan_complete_step directly for those.
---

# Feature Execution

Pipeline for implementing a set of feature plans produced by `feature-planning`. Manages context injection, phase-scoped execution dispatch, post-plan review, and fix cycles.

```
Plans + Ledger → Execute Phase → Track Steps → Review Plan → Fix Cycle? → Update Ledger → Next Plan → Archive
                     ↓                ↓             ↓              ↓                                    ↓
              Execution Agent   plan_complete  Review Agent   Plan Agent                          COMPLETION.md
              (one phase)        _step          (thorough)    (fix plan)                       → plans/completed/
```

---

## Hard Rules

1. **Never execute a full plan in one subagent call.** Dispatch one phase at a time. Phases are the natural context boundary — a subagent doing two phases has too much scope and produces sloppy implementations.
2. **Never skip review.** Every completed plan gets a review subagent dispatch. "It looks fine" is not review.
3. **Never ignore review findings.** If the review agent reports issues, generate a fix plan and execute it. No manual hand-waving.
4. **Never execute out of dependency order.** Follow the execution rounds from the feature README. A plan that depends on Plan A's outputs cannot run before Plan A passes review.
5. **Update the ledger with actuals, not plans.** After review passes, update CONTRACTS.md with *implemented* signatures, which may differ from what was planned.
6. **If context budget is exhausted, stop at a plan boundary.** The ledger and plan step checkboxes preserve all progress. A new session resumes cleanly.
7. **Never leave completed features unarchived.** After the last plan passes review plus ledger update, execute the archival protocol. Completed artifacts in `plans/` and `plans/dev/` rot into confusion.

---

## Prerequisites

Before starting execution:

1. Feature plans exist: `plans/TASK-{feature}-{A..Z}-*.md`
2. Parts README exists: `plans/dev/{feature}-parts/README.md`
3. Contracts ledger exists: `plans/dev/{feature}-parts/CONTRACTS.md`
4. All plans pass `plan_read` (schema-valid)

If any are missing, run `feature-planning` first.

---

## Phase 1: Prepare

1. Read the parts README — get execution rounds and dependency order
2. Read CONTRACTS.md — current state of implemented contracts
3. Check which plans have all steps completed (via `plan_read` or checkbox inspection)
4. Identify the next incomplete plan in dependency order

**Resuming a session:** Steps 1-4 are the full resume protocol. The ledger + plan checkboxes contain all state.

---

## Phase 2: Execute Plan

For each plan, execute one phase at a time.

### 2a. Dispatch Execution Subagent

Dispatch a subagent per phase. See [references/execution-protocol.md](references/execution-protocol.md) for the full prompt template and context injection rules.

**Context to inject:**
- The plan file content (full — the subagent needs all phases for orientation, but only implements the target phase)
- Relevant CONTRACTS.md sections (methods this phase calls or creates)
- Prior phase annotations from `plan_complete_step` (if continuing a partially-executed plan)
- Scope boundaries: what this phase covers, what it does NOT

**After subagent completes:**
1. Verify each step was completed — check via `plan_read` that steps are marked done
2. If the subagent couldn't complete a step, investigate why before proceeding
3. Do NOT mark steps complete on behalf of the subagent — if it didn't do the work, the step isn't done

### 2b. Repeat for Each Phase

Continue dispatching phase-by-phase until all phases in the plan are complete.

**Between phases:** Check annotations from the just-completed phase. If the subagent flagged concerns or deviations, address them before the next phase.

---

## Phase 3: Review Plan

After all phases of a plan complete, dispatch a review subagent. This is the quality gate.

See [references/review-protocol.md](references/review-protocol.md) for the full prompt template and review checklist.

The review agent performs **thorough** inspection:

| Category | What it checks |
|---|---|
| **Lint** | `lint_project_backend` / `lint_project_frontend` — zero errors |
| **Layer compliance** | No upward imports, proper DI, correct persistence access patterns |
| **Contract adherence** | Implemented signatures match CONTRACTS.md; new methods documented |
| **Code quality** | No lazy shortcuts, proper error handling, no `# type: ignore` without justification |
| **Architecture patterns** | TypedDicts (not Pydantic) in services/workflows, `db.module.method()` for persistence, `now_ms()` for timestamps |
| **Completeness** | All plan steps actually implemented — no stubs, no TODOs, no placeholder logic |
| **Drift detection** | Implementation matches design intent, not just plan letter |

The review agent returns a structured report: **PASS** or **ISSUES_FOUND** with specifics.

---

## Phase 4: Fix Cycle

If review returns **ISSUES_FOUND**, route on the **Scope Classification** from the review report:

- **NO_PLAN_NEEDED** → Dispatch a single targeted subagent with the issue list and file paths. No research, no plan file. See [references/review-protocol.md](references/review-protocol.md) for the prompt template. After the fix subagent completes, dispatch a full re-review (Round N+1) — not just lint. Re-review is always the gate.
- **PLAN_NEEDED** → Dispatch the Plan subagent with the full review report. Execute the resulting fix plan phase-by-phase. Re-review after execution.
- **DISCUSS** → Stop. Present the review findings to the user. Do not proceed until they respond.

After any fix (NO_PLAN_NEEDED or PLAN_NEEDED path), re-review using the Phase 3 protocol.

**Fix plan naming** (PLAN_NEEDED path): `TASK-{feature}-{letter}-fix.md`, or `-fix2.md` for a second round. More than 2 fix rounds on the same plan triggers DISCUSS classification — execution stops until the user decides.

---

## Phase 5: Update Ledger

After review passes for a plan:

1. **Update CONTRACTS.md** with *actual* implementations, not planned signatures
2. Use `read_module_api` / `read_module_source` to get real signatures from the codebase
3. Note any deviations from the original plan in the Decisions table
4. Date-stamp the update with the plan letter

**This is critical for downstream plans.** The next plan's execution subagent receives the ledger. Stale planned signatures cause cascading errors.

---

## Phase 6: Next Plan

Proceed to the next plan in dependency order. Return to Phase 2.

**Round boundaries:** When finishing the last plan in an execution round, all plans in that round should be reviewed and their ledger entries updated before starting the next round.

---

## Phase 7: Archive Feature

After all plans pass review, the ledger is updated, and the user is informed of any deviations — archive the feature.

See [references/archival-protocol.md](references/archival-protocol.md) for the full completion manifest template and move protocol.

### 7a. Generate Completion Manifest

Create `plans/dev/{feature}-parts/COMPLETION.md`:

1. **Execution Summary** — table of all plans with review round counts and fix plan references
2. **Design Deviations** — extracted from CONTRACTS.md Decisions table
3. **Key Decisions** — architectural decisions from plan annotations not in the design doc
4. **Files Created/Modified** — deduplicated from review reports, grouped by layer
5. **Final Lint Status** — run `lint_project_backend()` (and `lint_project_frontend()` if applicable) one final time

**Sources:** `plan_read` for completion status, CONTRACTS.md for deviations, plan step annotations for decisions, review reports for file lists.

### 7b. Move Artifacts to `plans/completed/`

Use `edit_file_move` for each artifact:

| Source | Destination |
|---|---|
| `plans/TASK-{feature}-*.md` | `plans/completed/TASK-{feature}-*.md` |
| `plans/dev/design-{feature}.md` | `plans/completed/design-{feature}.md` |
| `plans/dev/{feature}-parts/` | `plans/completed/{feature}-parts/` |

Move plans and design doc first, parts directory last (it contains the manifest you just wrote).

### 7c. Verify Clean State

After moving:
- No `TASK-{feature}-*.md` files remain in `plans/`
- No `{feature}-parts/` directory remains in `plans/dev/`
- No `design-{feature}.md` remains in `plans/dev/`
- `plans/completed/{feature}-parts/COMPLETION.md` exists

**Standalone plans** (no letter suffix, no parts directory): just move the plan file. No manifest needed — the plan's own checkboxes and annotations are sufficient.

---

## Session Continuity

When starting a new session mid-feature:

1. Read `plans/dev/{feature}-parts/README.md` — execution rounds
2. Read `plans/dev/{feature}-parts/CONTRACTS.md` — implemented contracts
3. For each plan, run `plan_read` to check completion status
4. Identify state:
   - **Plan fully complete + reviewed** → ledger should have entries, skip it
   - **Plan partially complete** → resume at next incomplete phase
   - **Plan complete but not reviewed** → dispatch review (Phase 3)
   - **Plan not started** → check if all dependencies are reviewed, then start
5. Resume at the appropriate phase

**The ledger is the source of truth for what's done.** If CONTRACTS.md has entries for Plan C's methods, Plan C was implemented and reviewed.

---

## Validation Checklist

Before declaring feature execution complete:

- [ ] All plans have all steps marked complete **→ Full implementation**
- [ ] All plans passed review (or fix cycle resolved issues) **→ Quality gate**
- [ ] CONTRACTS.md reflects actual implementations **→ No plan-vs-code drift**
- [ ] `lint_project_backend` passes on full workspace **→ Zero errors**
- [ ] No orphaned fix plans with incomplete steps **→ Clean state**
- [ ] User informed of any design deviations **→ Alignment**
- [ ] COMPLETION.md generated in `{feature}-parts/` **→ Audit trail**
- [ ] All artifacts moved to `plans/completed/` **→ Clean working directory**
- [ ] No feature files remain in `plans/` or `plans/dev/` **→ Verified clean state**