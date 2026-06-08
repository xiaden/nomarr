---
name: dispatching-support-librarian
description: Template for dispatching Support-Librarian to gather artifact context before R&D or Planning work.
---

# Dispatching Support-Librarian

Use this skill when you need to gather artifact context before beginning R&D or Planning work.

## When to Dispatch

- Before any R&D or Planning dispatch
- When entering an unfamiliar area
- When you need to avoid contradicting prior decisions

## Dispatch Template

```
Gather artifact context before we begin work on [TOPIC].

Search for:
- ADRs relevant to: [list key architectural areas]
- Logs from prior work on related modules: [module names]
- Design docs that constrain this area

Return a structured briefing: relevant decisions, prior observations, dead-ends to avoid.
```

## Required Fields

- `[TOPIC]`: The feature or area you're about to work on
- `[list key architectural areas]`: Specific domains (e.g., "tagging system", "library scanning", "ML inference")
- `[module names]`: Code modules that might have relevant logs (e.g., "nomarr/components/tagging", "nomarr/workflows/scan")

## Expected Output

Support-Librarian returns a structured briefing with:
- Relevant ADRs and their key decisions
- Prior observations from logs
- Dead-ends to avoid
- Constraints from existing design docs

## After Receiving Briefing

Pass the briefing to downstream agents (RnD-Manager, Exec-Planner) in their dispatch prompt. This prevents contradicting prior decisions.
