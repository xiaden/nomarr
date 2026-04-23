---
name: copilot-hooks
description: Use when creating or updating VS Code Copilot hook files in .github/hooks, especially PreToolUse validators that enforce subagent naming and tool safety policies.
---

# Copilot Hooks

Use this skill when adding or modifying VS Code Copilot hooks for this repository.

## When to Use

- Enforce policy before tool execution (`PreToolUse`)
- Add post-execution guards (`PostToolUse`)
- Inject context at session/subagent boundaries (`SessionStart`, `SubagentStart`)

## Repository Conventions

- Store hook configuration JSON files in `.github/hooks/`
- Store hook scripts in `.github/hooks/` (or `.github/hooks/scripts/` for larger setups)
- Prefer Python for non-trivial validation logic
- Hook scripts read event JSON from `stdin` and write JSON decision payload to `stdout`

## Minimal PreToolUse Hook Shape

A hook config file should define:

- `hooks.PreToolUse` as an array
- command entries with:
  - `type: command`
  - `command` (default shell)
  - `windows` override when needed
  - `timeout`

## Validator Script Contract

For policy checks:

1. Parse JSON input from `stdin`
2. Detect target event/tool (`tool_name`)
3. For violations, return:
   - `hookSpecificOutput.hookEventName = "PreToolUse"`
   - `hookSpecificOutput.permissionDecision = "deny"`
   - `hookSpecificOutput.permissionDecisionReason = "..."`
4. Otherwise return allow decision

## Example in This Repo

- `.github/hooks/validate-runsubagent-agent.json`
- `.github/hooks/validate-runsubagent-agent.py`

This guard denies `runSubagent` calls when:

- `agentName` is missing/empty
- `agentName` is not one of the declared agent names from `.github/agents/**/*.agent.md`

## Authoring Checklist

- Keep scripts deterministic and side-effect free
- Use actionable deny reasons (what failed + what to do)
- Keep timeouts short (e.g., 5-15s)
- Add/refresh docs where agent workflows are described
- Validate in VS Code with repository hook locations enabled
