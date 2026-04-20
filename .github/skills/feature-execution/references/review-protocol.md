# Review Subagent Protocol

How to dispatch review subagents that catch drift, sloppy code, lazy patterns, and architectural violations. The review agent is the quality gate — it must be thorough.

---

## Prompt Structure

```
1. TASK          — What was just implemented (plan name, all phases)
2. PLAN          — Full plan content (so reviewer knows what was intended)
3. CONTRACTS     — CONTRACTS.md entries this plan should have created/used
4. REVIEW SCOPE  — Files and modules touched by this plan
5. CHECKLIST     — Explicit review categories (below)
6. OUTPUT FORMAT — Structured verdict
```

---

## Prompt Template

```
Review the implementation of:

## Task
Plan: {plan file path}
Round: {N}  ← Orchestrator fills this in. Round 1 = first review of this plan. Round 2 = after a fix cycle. Round 3+ = auto-flag DISCUSS regardless of issue severity.
All phases of this plan are complete. Review the full implementation for quality, correctness, and architectural compliance.

## Layer Docs
{Include ALL that apply to layers touched by this plan. Copy the relevant rows from the table below.}

 | Layer | File | Purpose | 
 | --- | --- | --- | 
 | Interfaces | `.github/instructions/interfaces.instructions.md` | Route handlers, auth, Pydantic-only-here rule | 
 | Services | `.github/instructions/services.instructions.md` | DI wiring, thinness, no business logic | 
 | Workflows | `.github/instructions/workflows.instructions.md` | Use-case orchestration, one public function per file | 
 | Components | `.github/instructions/components.instructions.md` | Domain logic, stateless functions, ML isolation | 
 | Persistence | `.github/instructions/persistence.instructions.md` | AQL queries, db.module.method() access pattern | 
 | Helpers | `.github/instructions/helpers.instructions.md` | Pure utilities, DTOs, no nomarr imports | 
 | Frontend | `.github/instructions/frontend.instructions.md` | React/TS conventions, MUI sx prop, no `any` | 

Also include:
- Target plan: `artifacts/plans/pending/TASK-{feature}-{letter}-*.md`
- Contracts ledger: `artifacts/designs/parts/{feature}/CONTRACTS.md`
- Feature parts README: `artifacts/designs/parts/{feature}/README.md`
- This review protocol: `.github/skills/feature-execution/references/review-protocol.md`

## Plan Content
{Paste the full plan file. The reviewer needs to verify that what was implemented
matches what was planned — not just that the code compiles.}

## Expected Contracts
{Paste CONTRACTS.md entries relevant to this plan:
- Methods this plan was supposed to CREATE
- Methods this plan CALLS from upstream plans
- DTOs defined or consumed
- API endpoints added}

## Files Changed
{List the files and modules touched by this plan. The reviewer should focus here.
Use git diff or plan step annotations to identify these.
Example:
- nomarr/persistence/database/play_history_aql.py (new)
- nomarr/workflows/scrobble_ingest_wf.py (new)
- nomarr/services/domain/scrobble_svc.py (new)
- nomarr/interfaces/api/v1/scrobble_if.py (new)
- nomarr/helpers/dto/scrobble_dto.py (new)}

## Review Checklist

Perform ALL of the following checks. Do not skip any category.

### 1. Lint Verification
- Run lint_project_backend() on all affected paths
- Run lint_project_frontend() if frontend files were touched
- ZERO errors is the only acceptable state

### 2. Layer Compliance
- Trace imports in every new/modified file using trace_module_calls or read_module_api
- Verify: no upward imports (persistence→components→workflows→services→interfaces)
- Verify: workflows take db: Database, never services
- Verify: no Pydantic models outside interfaces layer
- Verify: persistence accessed via db.module.method(), not direct imports

### 3. Contract Adherence
- For each method in CONTRACTS.md that this plan creates:
  - Use read_module_source to get the actual signature
  - Compare against CONTRACTS.md entry
  - Flag any differences (parameter names, types, return types)
- For each method this plan calls from upstream:
  - Verify the call site matches the contract signature
  - Check error handling around the call

### 4. Code Quality
- No # type: ignore or # noqa without inline justification
- No bare except clauses
- No print() statements (use logging)
- No time.time() or datetime.now() (use now_ms() / now_s())
- No global mutable state
- No config/env reads at module level
- Proper error handling — no swallowed exceptions
- No TODO, FIXME, HACK, or XXX comments left behind
- No placeholder/stub implementations ("pass" in non-abstract methods)
- No duplicated logic that should be extracted

### 5. Architecture Patterns
- TypedDicts or dataclasses for DTOs (in helpers/dto/), not Pydantic
- Dependency injection for db, config — not module-level singletons
- Functions fully type-annotated (params + return)
- Proper use of LibraryPath where file paths are involved
- _id and _key never renamed in ArangoDB documents
- Essentia imports only in ml_audio_comp.py / ml_preprocess_comp.py

### 6. Completeness
- Every plan step has a corresponding implementation (not just a checkbox)
- No methods declared but empty
- No "will implement later" patterns
- Tests created if the plan specified them
- Migrations created if schema changes were made

### 7. Drift Detection
- Does the implementation match the DESIGN INTENT, not just the plan letter?
- If the subagent deviated from the plan (check annotations), was the deviation justified?
- Are there any methods or files created that weren't in the plan? (scope creep)
- Are there methods from the plan that weren't created? (incomplete)

## Output Format

Return your review in this exact structure:

### Verdict: {PASS | ISSUES_FOUND}

### Scope Classification: {NO_PLAN_NEEDED | PLAN_NEEDED | DISCUSS}

**Rationale:** {1-2 sentences. Example:
- NO_PLAN_NEEDED: "Two minor issues in one file — a stale comment and an unused import. Single subagent fix."
- PLAN_NEEDED: "Contract drift across 3 layers and a missing migration require coordinated multi-step fix."
- DISCUSS: "Persistence schema change is incompatible with migration baseline. User must decide approach first."}

**Classification guide:**
- **NO_PLAN_NEEDED** — All issues are in already-identified files, no architectural decisions needed, a single subagent with file pointers can resolve them in one pass.
- **PLAN_NEEDED** — Issues span multiple layers/files, require coordinated changes, or involve architectural decisions (schema, contract drift, layer violations).
- **DISCUSS** — Fundamental problem: design is wrong, damage scope is unknown, requirements unclear, or this is the 3rd fix round.

### Summary
{2-3 sentence overview of implementation quality}

### Issues (if any)

For each issue:

#### Issue {N}: {short title}
- **Severity:** {critical | major | minor}
- **Category:** {lint | layer | contract | quality | architecture | completeness | drift}
- **Location:** {file path + line or symbol name}
- **Description:** {what's wrong}
- **Expected:** {what should be there instead}

### Contract Drift (if any)

 | Method/DTO | Planned Signature | Actual Signature | Difference | 
 | --- | --- | --- | --- | 

### Files Reviewed
{List every file you actually inspected}

## Constraints
- Do NOT fix issues yourself. Report them. The orchestrator handles fixes.
- Do NOT skip categories because "the code looks fine." Run the actual checks.
- Be specific. "Code quality could be better" is not a finding. "bare except on line 47 of scrobble_wf.py swallows ConnectionError" is.
- Severity guide:
  - critical: Breaks architecture rules, layer violation, missing implementation
  - major: Contract drift, missing error handling, type safety holes
  - minor: Style issues, suboptimal patterns, missing docstrings on public APIs
```

---

## Review Scope Discovery

The orchestrator must tell the review agent which files to inspect. Methods to determine scope:

1. **Plan step annotations** — Completed steps often mention files created/modified
2. **Plan content** — Steps reference specific modules and file paths
3. **Git diff** — `git diff --name-only HEAD~N` if commits were made during execution
4. **Module tracing** — `trace_module_calls` on new entry points to find the full call chain

**Provide the file list explicitly.** Don't ask the review agent to "find what changed" — that wastes its context on discovery instead of review.

---

## Interpreting Review Results

The review agent outputs a **Scope Classification** alongside its verdict. Route on it directly — no additional judgment needed.

### PASS

Proceed to ledger update (Phase 5 of main workflow).

### ISSUES_FOUND + NO_PLAN_NEEDED

Dispatch a single subagent. No research required — the review report is the full brief:

```
Fix the following issues found during review:

## Issues
{Paste the issues section verbatim from the review report}

## Files to Edit
{List the file paths from "Location" fields above}

## Constraints
- Fix only the reported issues — no scope creep
- Run lint_project_{backend|frontend}() after fixing and confirm zero errors
```

After the fix subagent completes, dispatch a full re-review (Round N+1) using this same protocol. Do not skip to ledger update — re-review is the gate regardless of fix size.

### ISSUES_FOUND + PLAN_NEEDED

Dispatch the Plan subagent with the full review report as input. Execute and re-review per the fix cycle protocol below.

### ISSUES_FOUND + DISCUSS

Stop. Surface the review findings directly to the user. Do not generate a fix plan. The user must make a decision before work continues.

After the fix plan is created and validated (PLAN_NEEDED path), execute it using the standard execution protocol, then re-review.

---

## Fix Cycle Limits

 | Round | Action |
 | --- | --- |
 | Review 1 → Issues found | Generate fix plan, execute, review again |
 | Review 2 → Issues found | Generate fix-2 plan, execute, review again |
 | Review 3 → Still issues | **STOP.** Escalate to user. Something systemic is wrong. |

More than 2 fix rounds means the original plan or the architecture understanding is flawed. The orchestrator should present all remaining issues to the user and discuss before continuing.

---

## What the Review Agent Must NOT Do

- **Do not fix code.** The review agent reports. The fix cycle handles corrections.
- **Do not suggest alternative architectures.** Review against the existing rules, not hypothetical improvements.
- **Do not skip checks because they seem redundant.** Lint, layer tracing, and contract verification are mandatory every time.
- **Do not approve with caveats.** Either PASS or ISSUES_FOUND. "PASS but you should probably fix X" is ISSUES_FOUND.
