---
name: execute-plan
description: Execute the linked task plan sequentially using MCP plan tools
agent: agent
tools:
  ['execute/runInTerminal', 'context7/*', 'nomarr_dev/*', 'oraios/serena/activate_project', 'oraios/serena/find_file', 'oraios/serena/find_symbol', 'oraios/serena/rename_symbol', 'todo']
---

# Execute Task Plan

Execute the task plan file already provided in context.  
Do not infer, rename, or substitute the plan name.

You are executing a plan, not interpreting one.

---

## Phase 1: Load the Plan

**Check if the plan file is already attached in context.**

- If the plan markdown is visible in attachments → read it directly, skip `plan_read`
- If NOT attached → use `plan_read` with the plan name: ${fileBasenameNoExtension}

Do not modify the plan. Do not summarize it. Treat the plan as authoritative.

---


## Phase 1.5: Split Plan Detection

After loading the plan, check if it's part of a split plan set:

### Detection Criteria

A plan is split if:
- The plan name follows pattern `TASK-<feature>-<A|B|C|...>-<outcome>`, OR
- The `References` section lists other plan files with the same prefix

### Execution Strategy

**Default: Execute ONLY the current plan** (the one explicitly loaded).

Do NOT automatically execute all related split plans unless:
1. The user explicitly requests execution of all parts, OR
2. The current plan's `Completion Criteria` lists other split plans as "completed (prerequisite)"

### Prerequisite Checking

Before starting Phase 2 execution:

1. **Parse Completion Criteria** for prerequisite declarations like:
   - `TASK-<name>-A-<outcome> completed (prerequisite)`
   - `TASK-<name> completed (prerequisite)`

2. **Check each prerequisite** using `plan_read`:
   - If prerequisite plan doesn't exist → BLOCK with error
   - If prerequisite has incomplete steps → BLOCK with warning
   - If all prerequisites completed → proceed to Phase 2

3. **If blocked**, add annotation and stop:
   ```
   annotation:
     marker: Blocked
     text: |
       Prerequisite not met: TASK-feature-A-backend must be completed first.
       Found 3 incomplete steps in prerequisite plan.
   ```

### Cross-Plan References

When a step references "components from TASK-X-Y":
- Use `locate_module_symbol` or `find_symbol` to verify the referenced code exists
- If missing → check if the prerequisite plan completed successfully
- If completed but symbol missing → prerequisite plan failed its validation

---
## Phase 2: Step Execution Loop

Process steps strictly in order.

For each step:

1. Read the step
   - Identify the concrete outcome required.
   - Identify any invariants or constraints referenced by the plan.

2. Perform the work
   - Use the minimum tools required.
   - Prefer architecture-aware tools over raw file reads.
   - Do not speculate or narrate.

3. Verify
   - Verification must be objective:
     - lint results
     - test output
     - file diffs
     - concrete inspection
     - for split plans: imported symbols from prerequisite plans exist
   - If verification fails, the step is not complete.

4. Record completion
   - Call `plan_complete_step` with:
     - the exact plan name
     - the exact step ID
     - an annotation that records evidence, not intent

Example annotation payload:
```
  plan_complete_step
    plan_name: ${fileBasenameNoExtension}
    step_id: P2-S1
    annotation:
      marker: Notes
      text: |
        Modified helpers/log_suppressor.py lines 41–63.
        Refactored suppression logic into detect_eol().
        Ran lint_project_backend — 0 errors.
```

---

## Phase 3: Failure Protocol

If any of the following occur:
- an error is encountered
- required context is missing
- behavior is ambiguous
- verification fails

You must:

1. Stop immediately
2. Mark the step as FAILED via `plan_complete_step`

Failure annotation payload:
```
  annotation:
    marker: Blocked
    text: |
      Error: <exact error message>
      Location: <file:line>
      Unable to proceed without clarification.
```

3. Do not continue to later steps.

No recovery. No skipping. No assumptions.

---

## Mandatory Rules (Non-Negotiable)

- Execute steps in order
- One step at a time
- No partial completion
- Every annotation must contain concrete evidence
- After any Python edit:
  - run lint_project_backend
  - record the result
- Do not optimize the plan
- Do not invent follow-up tasks
- Do not proceed past failure
- The plan’s Problem Statement and Completion Criteria override all other instructions

- **For split plans:**
  - Check prerequisites before execution (Phase 1.5)
  - Execute ONLY the current plan by default
  - When Completion Criteria references other plans, verify their status
  - Cross-plan symbols must exist or prerequisite validation failed

---

## Phase 4: Plan Archival

After ALL steps in the plan are marked complete:

1. **Verify completion**
   - Confirm `plan_read` shows no remaining incomplete steps
   - All phases have been executed

2. **Move to completed directory**
   ```
   mkdir -p plans/completed
   mv plans/<plan-name>.md plans/completed/
   ```

3. **Handle split plans**
   - Only move the current plan file (the one you executed)
   - Do NOT move sibling plans (A, B, C parts) unless you executed them too
   - Parent plans stay in `plans/` until all children are complete

4. **Confirm archival**
   - Verify the file exists in `plans/completed/`
   - Report: "Plan archived to plans/completed/<plan-name>.md"

---

## Start Condition

Begin now by reading the plan:
- If attached in context → parse the markdown directly
- Otherwise → call `plan_read`
