"""JSONL log parser — extracts agent invocations and sessions from VS Code Copilot debug logs."""

from __future__ import annotations

import json
from pathlib import Path

from .models import AgentInvocation, LLMCall, Session, ToolCall


def _parse_jsonl(path: Path) -> list[dict]:
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _extract_agent_name_from_filename(filename: str) -> str:
    """Extract agent name from 'runSubagent-AgentName-toolCallId.jsonl'."""
    if filename.startswith("runSubagent-"):
        parts = filename[len("runSubagent-") :].rsplit("-toolu_", 1)
        if parts:
            return parts[0]
    return "Unknown"


def _parse_single_file(
    agent_name: str,
    session_id: str,
    log_file: Path,
) -> tuple[AgentInvocation, list[tuple[str, int, int]]]:
    """Parse one JSONL file into an AgentInvocation and a list of (child_agent_name, ts, ts+dur) for runSubagent calls.

    Returns:
        (invocation, child_spawns) where child_spawns are (agent_name, start_ts, end_ts) tuples.
    """
    events = _parse_jsonl(log_file)
    inv = AgentInvocation(
        agent_name=agent_name,
        session_id=session_id,
        log_file=log_file.name,
    )

    child_spawns: list[tuple[str, int, int]] = []  # (agent_name, start_ts, end_ts)
    # Also track spawn prompts keyed by (agent_name, start_ts) for later assignment
    spawn_prompts: dict[tuple[str, int], str] = {}

    for ev in events:
        ev_type = ev.get("type", "")
        ev_name = ev.get("name", "")
        attrs = ev.get("attrs", {})
        ts = ev.get("ts", 0)
        dur = ev.get("dur", 0)

        if not inv.timestamp and ts:
            inv.timestamp = ts

        if ev_type == "llm_request":
            inv.llm_calls.append(
                LLMCall(
                    model=attrs.get("model", "unknown"),
                    input_tokens=attrs.get("inputTokens", 0),
                    output_tokens=attrs.get("outputTokens", 0),
                    ttft_ms=attrs.get("ttft", 0),
                    duration_ms=dur,
                    timestamp=ts,
                )
            )

        elif ev_type == "tool_call":
            args_raw = attrs.get("args", "{}")
            args_summary = ""
            spawn_prompt = ""
            if ev_name == "runSubagent":
                try:
                    parsed = json.loads(args_raw)
                    child_agent = parsed.get("agentName", "")
                    args_summary = child_agent
                    spawn_prompt = parsed.get("prompt", "")
                    if child_agent:
                        child_spawns.append((child_agent, ts, ts + dur))
                        spawn_prompts[(child_agent, ts)] = spawn_prompt
                except (json.JSONDecodeError, TypeError):
                    pass
            inv.tool_calls.append(
                ToolCall(
                    name=ev_name,
                    duration_ms=dur,
                    status=ev.get("status", ""),
                    timestamp=ts,
                    args_summary=args_summary,
                )
            )

        elif ev_name.startswith("turn_start:"):
            inv.turn_count += 1

    # Compute wall time from first to last event
    timestamps = [ev.get("ts", 0) for ev in events if ev.get("ts", 0) > 0]
    if timestamps:
        inv.wall_time_ms = max(timestamps) - min(timestamps)

    # Stash spawn_prompts on invocation for later tree assembly
    inv._spawn_prompts = spawn_prompts  # type: ignore[attr-defined]

    return inv, child_spawns


def _build_tree(
    parent: AgentInvocation,
    parent_spawns: list[tuple[str, int, int]],
    file_map: dict[str, tuple[AgentInvocation, list[tuple[str, int, int]]]],
    claimed: set[str],
) -> None:
    """Recursively attach child invocations to parent based on runSubagent tool_calls.

    Uses agent name + timestamp overlap to match parent's runSubagent calls to child files.
    """
    for child_agent_name, spawn_start, spawn_end in parent_spawns:
        # Find matching unclaimed child files
        best_file: str | None = None
        best_ts_diff = float("inf")

        for filename, (child_inv, _child_spawns) in file_map.items():
            if filename in claimed:
                continue
            if child_inv.agent_name != child_agent_name:
                continue
            # Match by timestamp: child's first event should be within the spawn window
            if child_inv.timestamp and spawn_start <= child_inv.timestamp <= spawn_end:
                ts_diff = child_inv.timestamp - spawn_start
                if ts_diff < best_ts_diff:
                    best_ts_diff = ts_diff
                    best_file = filename
            elif child_inv.timestamp and not best_file:
                # Fallback: just match by name if no timestamp match (loose)
                best_file = filename

        if best_file and best_file not in claimed:
            claimed.add(best_file)
            child_inv, child_spawns = file_map[best_file]

            # Assign spawn prompt from parent
            prompts = getattr(parent, "_spawn_prompts", {})
            child_inv.spawn_prompt = prompts.get((child_agent_name, spawn_start), "")

            parent.children.append(child_inv)

            # Recurse into child's own spawns
            _build_tree(child_inv, child_spawns, file_map, claimed)

    # Sort children by timestamp
    parent.children.sort(key=lambda c: c.timestamp)


def parse_session(session_dir: Path) -> Session | None:
    """Parse a single session directory into a Session object with proper agent tree."""
    main_log = session_dir / "main.jsonl"
    if not main_log.exists():
        return None

    session_id = session_dir.name
    session = Session(session_id=session_id, session_dir=str(session_dir))

    # Determine root agent name from events
    events = _parse_jsonl(main_log)
    root_agent = "Agent"  # default

    for ev in events:
        ev_name = ev.get("name", "")
        if (
            ev.get("type")
            not in (
                "llm_request",
                "tool_call",
                "generic",
                "session_start",
                "user_message",
                "turn_start",
                "turn_end",
                "child_session_ref",
                "discovery",
            )
            and ev_name
            and not ev_name.startswith("turn_")
            and not ev_name.startswith("chat:")
            and not ev_name.startswith("runSubagent")
            and ev_name not in ("session_start", "user_message", "agent_response", "title")
            and ev_name
            not in (
                "Resolve Customizations",
                "Agent Discovery",
                "Skill Discovery",
                "Slash Commands Discovery",
                "Instructions Discovery",
                "Hook Discovery",
            )
        ):
            root_agent = ev_name
            break

    # Get session timestamp
    for ev in events:
        if ev.get("ts", 0) > 0:
            session.timestamp = ev["ts"]
            break

    # Parse ALL subagent files
    subagent_files = [
        f for f in session_dir.glob("runSubagent-*.jsonl") if f.is_file() and not f.name.startswith("title-")
    ]

    # Parse each file into invocations
    file_map: dict[str, tuple[AgentInvocation, list[tuple[str, int, int]]]] = {}
    for f in subagent_files:
        agent_name = _extract_agent_name_from_filename(f.name)
        inv, spawns = _parse_single_file(agent_name, session_id, f)
        file_map[f.name] = (inv, spawns)

    # Parse root
    root_inv, root_spawns = _parse_single_file(root_agent, session_id, main_log)

    # Build tree starting from root
    claimed: set[str] = set()
    _build_tree(root_inv, root_spawns, file_map, claimed)

    # Any unclaimed files are orphans — attach to root as fallback
    for filename in sorted(file_map.keys()):
        if filename not in claimed:
            child_inv, child_spawns = file_map[filename]
            root_inv.children.append(child_inv)
            # Recurse into orphan's children too
            _build_tree(child_inv, child_spawns, file_map, claimed)

    root_inv.children.sort(key=lambda c: c.timestamp)
    session.root = root_inv
    return session
