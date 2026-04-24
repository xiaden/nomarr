"""JSON serializer — converts parsed sessions into a JSON data file for the static dashboard."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    EDITING_TOOLS,
    EXCLUDED_TOOLS,
    EXPLORATION_TOOLS,
    LOGGING_TOOLS,
    MANAGEMENT_TOOLS,
    QA_TOOLS,
    RESEARCH_TOOLS,
    AgentInvocation,
    Session,
    collect_all_invocations,
    compute_aggregates,
    compute_tool_aggregates,
)


def _tool_category(tool_name: str) -> str:
    if tool_name in EXCLUDED_TOOLS:
        return "excluded"
    if tool_name in MANAGEMENT_TOOLS:
        return "management"
    if tool_name in EDITING_TOOLS:
        return "editing"
    if tool_name in EXPLORATION_TOOLS:
        return "exploration"
    if tool_name in QA_TOOLS:
        return "qa"
    if tool_name in LOGGING_TOOLS:
        return "logging"
    if tool_name in RESEARCH_TOOLS:
        return "research"
    return "other"


def _build_agent_tool_profiles(sessions: list[Session]) -> dict[str, dict]:
    """Build per-agent tool usage profile and inferred tool schema from observed calls."""
    profiles: dict[str, dict[str, int]] = {}
    failures: dict[str, dict[str, int]] = {}

    for session in sessions:
        if not session.root:
            continue
        for inv in collect_all_invocations(session.root):
            profiles.setdefault(inv.agent_name, {})
            failures.setdefault(inv.agent_name, {})
            for tc in inv.tool_calls:
                profiles[inv.agent_name][tc.name] = profiles[inv.agent_name].get(tc.name, 0) + 1
                if tc.status == "error":
                    failures[inv.agent_name][tc.name] = failures[inv.agent_name].get(tc.name, 0) + 1

    result: dict[str, dict] = {}
    for agent_name, counts in profiles.items():
        total_calls = sum(counts.values())
        tools = []
        for tool_name, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
            category = _tool_category(tool_name)
            fail_count = failures[agent_name].get(tool_name, 0)
            tools.append(
                {
                    "name": tool_name,
                    "category": category,
                    "count": count,
                    "ratio": round(count / total_calls, 4) if total_calls else 0.0,
                    "failures": fail_count,
                    "failure_rate": round(fail_count / count, 4) if count else 0.0,
                }
            )

        result[agent_name] = {
            "total_calls": total_calls,
            "tools": tools,
            # Inferred schema from observed behavior in logs.
            "schema": {
                "allowed_tools": [t["name"] for t in tools],
                "allowed_categories": sorted({t["category"] for t in tools}),
            },
        }
    return result


def _invocation_to_dict(inv: AgentInvocation) -> dict:
    return {
        "agent_name": inv.agent_name,
        "log_file": inv.log_file,
        "timestamp": inv.timestamp,
        "spawn_prompt": inv.spawn_prompt,
        "turn_count": inv.turn_count,
        "wall_time_ms": inv.wall_time_ms,
        "total_input_tokens": inv.total_input_tokens,
        "total_output_tokens": inv.total_output_tokens,
        "total_tokens": inv.total_tokens,
        "tree_tokens": inv.tree_tokens,
        "tool_call_count": inv.tool_call_count,
        "management_count": inv.management_count,
        "editing_count": inv.editing_count,
        "exploration_count": inv.exploration_count,
        "qa_count": inv.qa_count,
        "logging_count": inv.logging_count,
        "research_count": inv.research_count,
        "management_ratio": round(inv.management_ratio, 4),
        "editing_ratio": round(inv.editing_ratio, 4),
        "exploration_ratio": round(inv.exploration_ratio, 4),
        "qa_ratio": round(inv.qa_ratio, 4),
        "logging_ratio": round(inv.logging_ratio, 4),
        "research_ratio": round(inv.research_ratio, 4),
        "failure_count": inv.failure_count,
        "failure_rate": round(inv.failure_rate, 4),
        "repeated_tool_calls": inv.repeated_tool_calls,
        "tokens_per_mutation": round(inv.tokens_per_mutation, 1),
        "calls_before_first_dispatch": inv.calls_before_first_dispatch,
        "models_used": sorted(inv.models_used),
        "avg_ttft_ms": round(inv.avg_ttft_ms, 1),
        "final_response": inv.final_response,
        "tool_calls": [
            {
                "name": tc.name,
                "duration_ms": tc.duration_ms,
                "status": tc.status,
                "timestamp": tc.timestamp,
                "args_summary": tc.args_summary,
                "args_preview": tc.args_preview,
                "result_preview": tc.result_preview,
            }
            for tc in inv.tool_calls
        ],
        "children": [_invocation_to_dict(c) for c in inv.children],
    }


def _session_to_dict(session: Session) -> dict:
    return {
        "session_id": session.session_id,
        "timestamp": session.timestamp,
        "root": _invocation_to_dict(session.root) if session.root else None,
    }


def serialize_dashboard_data(sessions: list[Session]) -> dict:
    """Convert all session data into a JSON-serializable dict for the static dashboard."""
    aggregates = compute_aggregates(sessions)
    tool_aggs = compute_tool_aggregates(sessions)
    agent_tool_profiles = _build_agent_tool_profiles(sessions)

    # Global stats
    total_tokens_all = sum(s.root.tree_tokens for s in sessions if s.root)
    total_tool_calls = sum(
        sum(i.tool_call_count for i in collect_all_invocations(s.root))
        for s in sessions
        if s.root
    )
    total_failures = sum(
        sum(i.failure_count for i in collect_all_invocations(s.root))
        for s in sessions
        if s.root
    )

    # Agent aggregates
    agent_aggs = {}
    for name in sorted(aggregates.keys(), key=lambda n: aggregates[n].total_tokens, reverse=True):
        agg = aggregates[name]
        agent_aggs[name] = {
            "count": agg.count,
            "total_tokens": agg.total_tokens,
            "avg_tokens": round(agg.avg_tokens),
            "total_tree_tokens": agg.total_tree_tokens,
            "avg_tool_calls": round(agg.avg_tool_calls, 1),
            "total_management_calls": sum(i.management_count for i in agg.invocations),
            "total_editing_calls": sum(i.editing_count for i in agg.invocations),
            "total_exploration_calls": sum(i.exploration_count for i in agg.invocations),
            "total_qa_calls": sum(i.qa_count for i in agg.invocations),
            "total_logging_calls": sum(i.logging_count for i in agg.invocations),
            "total_research_calls": sum(i.research_count for i in agg.invocations),
            "avg_management_ratio": round(agg.avg_management_ratio, 4),
            "avg_editing_ratio": round(agg.avg_editing_ratio, 4),
            "avg_exploration_ratio": round(agg.avg_exploration_ratio, 4),
            "avg_qa_ratio": round(agg.avg_qa_ratio, 4),
            "avg_logging_ratio": round(agg.avg_logging_ratio, 4),
            "avg_research_ratio": round(agg.avg_research_ratio, 4),
            "avg_failure_rate": round(agg.avg_failure_rate, 4),
            "total_failures": agg.total_failures,
            "avg_tokens_per_mutation": round(agg.avg_tokens_per_mutation, 1),
            "avg_calls_before_dispatch": (
                round(agg.avg_calls_before_dispatch, 1)
                if agg.avg_calls_before_dispatch is not None
                else None
            ),
            "avg_turns": round(agg.avg_turns, 1),
            "models_used": sorted(agg.models_used),
        }

    # Tool aggregates
    tool_agg_list = []
    for ta in sorted(tool_aggs.values(), key=lambda t: t.total_calls, reverse=True):
        if ta.total_calls < 1:
            continue
        tool_agg_list.append(
            {
                "name": ta.name,
                "category": ta.category,
                "total_calls": ta.total_calls,
                "failures": ta.failures,
                "failure_rate": round(ta.failure_rate, 4),
                "repeats": ta.repeats,
                "repeat_rate": round(ta.repeat_rate, 4),
                "avg_duration_ms": round(ta.avg_duration_ms, 1),
                "agent_count": len(ta.agents),
                "agents": sorted(ta.agents),
            }
        )

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_sessions": len(sessions),
            "unique_agents": len(aggregates),
            "total_tokens": total_tokens_all,
            "total_tool_calls": total_tool_calls,
            "total_failures": total_failures,
            "failure_rate": round(total_failures / total_tool_calls, 4) if total_tool_calls else 0,
        },
        "agent_aggregates": agent_aggs,
        "agent_tool_profiles": agent_tool_profiles,
        "tool_aggregates": tool_agg_list,
        "sessions": [
            _session_to_dict(s)
            for s in sorted(sessions, key=lambda s: s.timestamp, reverse=True)
            if s.root
        ],
    }


def write_json(sessions: list[Session], output_path: Path) -> None:
    """Serialize session data and write to a JSON file."""
    data = serialize_dashboard_data(sessions)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")

    summary = data["summary"]
    print(f"JSON data written to: {output_path}")
    print(f"  Sessions: {summary['total_sessions']}")
    print(f"  Agents: {summary['unique_agents']}")
    print(f"  Total tokens: {summary['total_tokens']:,}")
    print(f"  Tool calls: {summary['total_tool_calls']:,} ({summary['total_failures']} failures)")
