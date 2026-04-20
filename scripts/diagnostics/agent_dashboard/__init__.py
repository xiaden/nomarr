"""Agent Performance Dashboard — parses VS Code Copilot debug logs into a JSON report + static HTML viewer."""

from __future__ import annotations

from .models import AgentAggregate, AgentInvocation, LLMCall, Session, ToolCall
from .parser import parse_session
from .serializer import write_json

__all__ = [
    "AgentAggregate",
    "AgentInvocation",
    "LLMCall",
    "Session",
    "ToolCall",
    "parse_session",
    "write_json",
]
