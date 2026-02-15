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

## Phase 1.5: Prerequisite Check

If the plan name follows the pattern `TASK-<feature>-<B|C|D|...>-<outcome>` (i.e., it's not the first part):

1. Check the Problem Statement for `**Prerequisite:** TASK-<feature>-<letter>-<outcome>`
2. If a prerequisite is declared, verify it exists in `plans/completed/` using `find_file`
3. If the prerequisite plan is NOT in `plans/completed/`:
   - Check if it exists in `plans/` and read it to see if all steps are complete
   - If incomplete → BLOCK and stop
4. If no prerequisite is declared, proceed normally

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
- The plan's Problem Statement and Completion Criteria override all other instructions

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

3. **Confirm archival**
   - Verify the file exists in `plans/completed/`
   - Report: "Plan archived to plans/completed/<plan-name>.md"

---

## Start Condition

Begin now by reading the plan:
- If attached in context → parse the markdown directly
- Otherwise → call `plan_read`
