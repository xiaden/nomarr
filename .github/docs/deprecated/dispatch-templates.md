# Dispatch Templates

Standard prompts for dispatching agents. Copy and fill in variables.

---

## Dispatch PlanManager

```
Execute Plan {letter} for {feature}.

Read these files FIRST before any work:
- plans/TASK-{feature}-{letter}-{title}.md
- plans/dev/{feature}-parts/CONTRACTS.md
- plans/dev/{feature}-parts/README.md
- plans/dev/design-{feature}.md
- .github/instructions/{layer1}.instructions.md
- .github/instructions/{layer2}.instructions.md
{... add all layers this plan touches}

Task:
- plan: TASK-{feature}-{letter}-{title}
- startPhase: 1
- reviewRequired: true

Report only: status (DONE/BLOCKED/ESCALATE), summary, blockers if any.
Do not report phase-by-phase details unless blocked.
```

---

## PlanManager → Executor

```
Execute Phase {N} of Plan {letter}.

Read these files FIRST:
- plans/TASK-{feature}-{letter}-{title}.md
- plans/dev/{feature}-parts/CONTRACTS.md
- .github/instructions/{layer}.instructions.md

Task:
- plan: TASK-{feature}-{letter}-{title}
- phase: {N}
- priorAnnotations:
  {paste annotations from prior phases, or "None — this is Phase 1"}

Implement ONLY Phase {N}. Mark each step complete with plan_complete_step.
Lint after each file change. Report: status, artifacts, annotations.
```

---

## PlanManager → Reviewer

```
Review Plan {letter} implementation.

Read these files FIRST:
- plans/TASK-{feature}-{letter}-{title}.md
- plans/dev/{feature}-parts/CONTRACTS.md
- .github/instructions/{layer1}.instructions.md
- .github/instructions/{layer2}.instructions.md

Task:
- plan: TASK-{feature}-{letter}-{title}
- round: {N}
- changedFiles:
  - {file1}
  - {file2}
  {...}

Perform full review: lint, layer compliance, contracts, code quality, completeness.
Report: status (PASS/ISSUES_FOUND), severity classification, recommended action.
```

---

## PlanManager → Fixer

```
Fix review issues for Plan {letter}.

Read these files FIRST:
- plans/TASK-{feature}-{letter}-{title}.md
- plans/dev/{feature}-parts/CONTRACTS.md
- .github/instructions/{layer}.instructions.md

Task:
- plan: TASK-{feature}-{letter}-{title}
- reviewRound: {N}
- issues:
  - file: "{path}"
    line: {N}
    category: {category}
    detail: "{issue description}"
    suggestedFix: "{how to fix}"
  {...}

Fix each listed issue. Lint after each fix. Report: status, fixes applied.
```

---

## PlanManager → Planner (Fix Plan)

```
Create fix plan for Plan {letter} review issues.

Read these files FIRST:
- plans/TASK-{feature}-{letter}-{title}.md
- plans/dev/{feature}-parts/CONTRACTS.md
- plans/dev/{feature}-parts/README.md

Task:
- type: FIX_PLAN
- plan: TASK-{feature}-{letter}-{title}
- reviewReport:
  {paste full review report with PLANNING_GAP issues}

Create TASK-{feature}-{letter}-fix.md with minimal scope to address gaps.
Update CONTRACTS.md if new methods needed.
Report: status, artifacts, contracts added.
```

---

## Director → Planner (New Plan)

```
Create implementation plan for {feature} Part {letter}.

Read these files FIRST:
- plans/dev/design-{feature}.md
- plans/dev/{feature}-parts/README.md
- plans/dev/{feature}-parts/CONTRACTS.md

Task:
- type: CREATE
- feature: {feature}
- letter: {letter}
- scope: "{what this plan covers}"
- dependencies: [{prior plans}]

Research the codebase to understand existing patterns.
Create plans/TASK-{feature}-{letter}-{title}.md.
Update CONTRACTS.md with methods this plan will create.
Update README.md if dependency graph changes.
Report: status, artifacts, contracts.
```

---

## Director → DDAuthor (Design Doc)

```
Create design document for {feature}.

Read these files FIRST:
- .github/copilot-instructions.md
- .github/instructions/{layer1}.instructions.md
- .github/instructions/{layer2}.instructions.md
{... add layers this feature will touch}

Task:
- type: CREATE
- title: "{feature title}"
- requirements:
  - "{requirement 1 from user}"
  - "{requirement 2 from user}"
  {...}
- researchFocus:
  - "existing patterns for {similar feature}"
  - "current {domain} implementation"

Research the codebase BEFORE designing.
Create plans/dev/design-{feature}.md.
Report: status, artifacts, design decisions, questions if any.
```

---

## Output Parsing

All agents return YAML-structured reports. Parse with:

```python
import yaml

# Agent returned this text
report_text = """
status: DONE
summary: "Plan B complete"
...
"""

report = yaml.safe_load(report_text)
if report["status"] == "DONE":
    proceed_to_next()
elif report["status"] == "BLOCKED":
    handle_blockers(report["blockers"])
elif report["status"] == "ESCALATE":
    ask_user(report["summary"])
```
