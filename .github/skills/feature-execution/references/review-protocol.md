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
All phases of this plan are complete. Review the full implementation for quality, correctness, and architectural compliance.

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
|---|---|---|---|

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

### PASS

Proceed to ledger update (Phase 5 of main workflow).

### ISSUES_FOUND with only minor severity

Use judgment:
- If 1-2 minor issues → fix them directly (no fix plan needed), then update ledger
- If 3+ minor issues → generate a fix plan for consistency

### ISSUES_FOUND with major or critical severity

**Always generate a fix plan.** Dispatch the Plan subagent with:

```
Create a fix plan for:

## Review Findings
{Paste the full review output — all issues with their details}

## Original Plan
{Plan file path — the fix plan subagent can read it for context}

## Constraints
- Fix only the reported issues. Do not refactor beyond what's needed.
- Create the fix plan at: plans/TASK-{feature}-{letter}-fix.md
- Each issue should map to one or more fix steps
- Include a lint verification step at the end
- Critical issues first, then major, then minor
```

After the fix plan is created and validated, execute it using the standard execution protocol, then re-review.

---

## Fix Cycle Limits

| Round | Action |
|---|---|
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
