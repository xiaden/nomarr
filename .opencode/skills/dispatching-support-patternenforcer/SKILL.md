---
name: dispatching-support-patternenforcer
description: Template for dispatching Support-PatternEnforcer to check pattern coverage and consistency.
---

# Dispatching Support-PatternEnforcer

Use this skill when you need Support-PatternEnforcer to check whether a pattern is consistently applied across the codebase.

## When to Dispatch

- After a design document is created (validate DD coverage)
- After a plan is created (validate plan coverage)
- After a plan that introduces a new pattern is complete (check adoption)
- When QA-Reviewer flags inconsistent pattern adoption

## Dispatch Template

```
Check coverage for [DD or plan at PATH].

Pattern to enforce: [describe what should be touched — e.g., "all persistence modules that own X entity"]
Scope: [list modules or directories to scan]

Return gaps where the pattern should apply but is not mentioned.
```

## Required Fields

- `[DD or plan at PATH]`: Path to the design document or plan file
- `[describe what should be touched]`: The pattern to check (e.g., "all persistence modules that own X entity", "all services that use library scanning")
- `[list modules or directories to scan]`: Scope of the check (e.g., "nomarr/persistence/", "nomarr/services/")

## Expected Output

Support-PatternEnforcer returns:
- `high_confidence`: Files that definitely need the pattern
- `medium_confidence`: Files that might need the pattern
- `low_confidence`: Files that might not need the pattern
- `gaps`: Specific gaps where the pattern is missing

## Routing PatternEnforcer Output

### After DD or Plan Creation

If significant gaps found, route back to the authoring agent (RnD-DDAuthor or Exec-Planner) for amendment before proceeding.

### After Plan Execution (New Pattern Adoption)

If `high_confidence` candidates exist, spawn **Exec-Planner** (AMEND) to add a migration phase to the relevant plan.

## Pattern Adoption Check (After Plan Execution)

Use this variant when checking whether a new pattern introduced by a plan has been adopted everywhere it should be:

```
Find all files that should adopt the new pattern introduced by {plan name}.

pattern:
  name: "{descriptive name of the new pattern}"
  description: "{what it does and why it replaces the old approach}"
  uses_pattern:
    signatures:
      - "{new function/method signature}"
    imports:
      - "{new import path}"
  legacy_indicators:
    signatures:
      - "{old function/method signature}"
    imports:
      - "{old import path}"
scope:
  include:
    - "nomarr/"
  exclude:
    - "nomarr/migrations/"
    - "tests/"
```

Route the output: if `high_confidence` candidates exist, spawn **Exec-Planner** (AMEND) to add a migration phase to the relevant plan.
