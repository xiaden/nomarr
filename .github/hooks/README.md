# Copilot Hooks (VS Code Preview)

This repository uses VS Code Copilot hooks from `.github/hooks`.

## Enablement

Enable hook discovery for this folder:

- `chat.hookFilesLocations[".github/hooks"] = true`

If using custom agent-level hooks in agent markdown, also enable:

- `chat.useCustomAgentHooks = true`

## Hook inventory

### `validate-runsubagent-agent`

- Config: `validate-runsubagent-agent.json`
- Script: `validate-runsubagent-agent.py`
- Event: `PreToolUse`
- Target tool: `runSubagent`
- Role: validation / policy enforcement

This hook denies `runSubagent` when:

1. `tool_input.agentName` is missing or empty
2. `agentName` is not a valid custom agent name from `.github/agents/**/*.agent.md` frontmatter

### `shared-context-pretooluse`

- Config: `shared-context-pretooluse.json`
- Script: `shared-context-pretooluse.py`
- Event: `PreToolUse`
- Target tool: all `PreToolUse` events, with internal filtering for `runSubagent`
- Role: observational capture only

This hook normalizes incoming payloads, mirrors the named-agent validity check defensively, and for eligible `runSubagent` calls freezes pending inheritance state for the next child spawn. It never denies a tool call.

### `shared-context-subagentstart`

- Config: `shared-context-subagentstart.json`
- Script: `shared-context-subagentstart.py`
- Event: `SubagentStart`
- Target tool: all `SubagentStart` events
- Role: observational activation only

This hook correlates a child start with its pending spawn envelope and activates the authoritative inherited context for that child. It never denies a hook event.

## Shared-context storage boundary

The only authoritative storage for shared-context runtime state is:

- `artifacts/scratch/shared-context/v1/sessions/{session_id}/`

Within that session root:

- `journal.jsonl` is the append-only authoritative journal
- `envelopes/pending/{correlation_id}.json` stores immutable pending spawn envelopes
- `envelopes/active/{agent_id}.json` stores immutable active child envelopes

No authoritative shared-context state is stored under `artifacts/logs/`, transcripts, or other human-editable artifacts.

## Ordering and ownership

For `PreToolUse(runSubagent)`, the intended ordering is:

1. `validate-runsubagent-agent.py` validates the target agent and may deny the call
2. `shared-context-pretooluse.py` captures shared-context state only for allowed, valid calls

That means shared-context capture is observational and should only see calls that were not denied by the validator. The capture script also mirrors the validator's named-agent check defensively so it will not author pending envelopes for invalid `runSubagent` requests even if hook ordering is changed during local experimentation.

For `SubagentStart`, `shared-context-subagentstart.py` is the authoritative activation path for shared-context inheritance. It correlates strictly on session and child identity, then writes active envelopes and activation journal records.

## stdin/stdout contract

All hook scripts in this folder follow the same basic pattern:

- read hook event JSON from `stdin`
- write hook response JSON to `stdout`
- handle malformed input defensively

The shared-context hooks are observational only:

- they always emit an `allow` decision
- they never gate execution or deny a request
- unexpected input results in a best-effort journal anomaly record when a session can be identified

## Journal and envelope contents

At a high level:

- the journal records lifecycle events such as malformed payloads, `next_child` reservation, pending spawn capture, activation, and one-time consumption
- pending envelopes freeze the exact eligible context items and bounded tool metadata at spawn time
- active envelopes freeze the exact effective inherited item set for the child after strict correlation

The shared-context hooks persist bounded metadata only. They intentionally avoid storing full subagent prompt text and treat transcripts as debugging evidence, not authoritative runtime state.
