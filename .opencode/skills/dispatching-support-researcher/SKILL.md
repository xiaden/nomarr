---
name: dispatching-support-researcher
description: Template for dispatching Support-Researcher to investigate codebase or external documentation.
---

# Dispatching Support-Researcher

Use this skill when you need Support-Researcher to investigate a topic in the codebase or external documentation.

## When to Dispatch

- When you need to understand how something works
- When you need to trace call chains or dependencies
- When you need external library documentation
- When you need to compare patterns across modules
- When Director lacks information to route (spawn first, don't guess)

## Dispatch Template

```
Investigate [TOPIC] in the codebase.

Questions to answer:
1. [specific question]
2. [specific question]

Return findings with file paths and code locations. Depth: [quick / standard / thorough].
```

## Required Fields

- `[TOPIC]`: What to investigate (e.g., "how library scanning works", "tag calibration flow")
- `[specific question]`: Concrete questions to answer (2-5 questions)
- `[quick / standard / thorough]`: How deep to go
  - **quick**: Surface-level, file locations only
  - **standard**: Moderate depth, key code paths
  - **thorough**: Deep dive, all relevant code, edge cases

## Expected Output

Support-Researcher returns:
- Findings organized by question
- File paths and line numbers for all code references
- Code snippets where relevant
- Summary of key insights

## Routing Researcher Output

- Use findings to make routing decisions
- Pass relevant findings to downstream agents
- Log significant discoveries if they reveal architectural patterns or dead-ends
