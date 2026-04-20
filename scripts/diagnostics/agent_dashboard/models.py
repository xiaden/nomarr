"""Data structures and tool classification sets for agent metrics."""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Tool classification sets
#
# Seven categories mapping to the agent workflow cycle:
#   excluded    — meta-tools, noise (read_file), and terminal misuse signals
#   management  — spawning agents, approving ADRs, asking user questions, git ops
#   editing     — file creation, modification, deletion
#   exploration — unstructured searches, file reads, directory listing, find_symbol
#   qa          — linting, testing
#   logging     — log_write, plan_complete_step, adr_suggest, manage_todo_list, memory
#   research    — reading ADRs/ASRs/DDs, AST-assisted reads, structured code nav,
#                 external docs (context7, fetch_webpage)
# ---------------------------------------------------------------------------

# Tools excluded from category stats entirely — meta-tools, noise, and misuse signals.
# They still appear in the Tool Health table, just not in the stat block / ratios.
EXCLUDED_TOOLS = frozenset(
    {
        # Noise — read_file is 3x the next most-used tool and drowns signal
        "read_file",
        # Meta-tools — infrastructure, not agent behavior
        "tool_search",
        "vscode_listCodeUsages",
        # Terminal — misuse signal; a better MCP tool should have been used
        "run_in_terminal",
        "get_terminal_output",
        "send_to_terminal",
        "kill_terminal",
    }
)

MANAGEMENT_TOOLS = frozenset(
    {
        "runSubagent",
        "mcp_nomarr_dev_adr_commit",
        "vscode_askQuestions",
        # Git operations
        "mcp_gitkraken_git_add_or_commit",
        "mcp_gitkraken_git_push",
    }
)

EDITING_TOOLS = frozenset(
    {
        # VS Code standard edits
        "replace_string_in_file",
        "multi_replace_string_in_file",
        "create_file",
        "vscode_renameSymbol",
        "apply_patch",
        # Nomarr-dev file edits
        "mcp_nomarr_dev_edit_file_create",
        "mcp_nomarr_dev_edit_file_replace_string",
        "mcp_nomarr_dev_edit_file_replace_content",
        "mcp_nomarr_dev_edit_file_insert_at_boundary",
        "mcp_nomarr_dev_edit_file_insert_at_line",
        "mcp_nomarr_dev_edit_file_move",
        "mcp_nomarr_dev_edit_file_move_by_content",
        "mcp_nomarr_dev_edit_file_replace_by_content",
        "mcp_nomarr_dev_edit_file_copy_paste_text",
        # Serena edits
        "mcp_oraios_serena_replace_symbol_body",
        "mcp_oraios_serena_insert_after_symbol",
        "mcp_oraios_serena_insert_before_symbol",
        "mcp_oraios_serena_rename_symbol",
    }
)

EXPLORATION_TOOLS = frozenset(
    {
        # Unstructured file reads
        "view_image",
        "list_dir",
        "mcp_nomarr_dev_list_project_directory_tree",
        "mcp_nomarr_dev_read_file_line",
        "mcp_nomarr_dev_read_file_line_range",
        # Search / grep
        "grep_search",
        "semantic_search",
        "file_search",
        "mcp_nomarr_dev_search_file_text",
        # Git status
        "mcp_gitkraken_git_status",
        "mcp_gitkraken_git_blame",
        # Serena broad symbol search (exploration, not targeted research)
        "mcp_oraios_serena_find_symbol",
    }
)

QA_TOOLS = frozenset(
    {
        "mcp_nomarr_dev_lint_project_backend",
        "mcp_nomarr_dev_lint_project_frontend",
        "runTests",
    }
)

LOGGING_TOOLS = frozenset(
    {
        "manage_todo_list",
        "mcp_nomarr_dev_log_write",
        "mcp_nomarr_dev_adr_suggest",
        "mcp_nomarr_dev_asr_create",
        "mcp_nomarr_dev_dd_create",
        "mcp_nomarr_dev_dd_archive",
        "mcp_nomarr_dev_plan_complete_step",
        "mcp_nomarr_dev_plan_archive",
        # Memory
        "memory",
    }
)

RESEARCH_TOOLS = frozenset(
    {
        # Artifact reads
        "mcp_nomarr_dev_adr_search",
        "mcp_nomarr_dev_adr_read",
        "mcp_nomarr_dev_asr_search",
        "mcp_nomarr_dev_asr_read",
        "mcp_nomarr_dev_log_read",
        "mcp_nomarr_dev_dd_read",
        "mcp_nomarr_dev_plan_read",
        # AST-assisted code navigation
        "mcp_nomarr_dev_read_module_api",
        "mcp_nomarr_dev_read_module_source",
        "mcp_nomarr_dev_locate_module_symbol",
        "mcp_nomarr_dev_trace_module_calls",
        "mcp_nomarr_dev_trace_project_endpoint",
        "mcp_nomarr_dev_read_file_symbol_at_line",
        "mcp_nomarr_dev_py_introspect",
        # Serena targeted navigation
        "mcp_oraios_serena_get_symbols_overview",
        "mcp_oraios_serena_find_referencing_symbols",
        # External documentation
        "fetch_webpage",
        "mcp_context7_resolve-library-id",
        "mcp_context7_get-library-docs",
    }
)

ALL_CLASSIFIED = EXCLUDED_TOOLS | MANAGEMENT_TOOLS | EDITING_TOOLS | EXPLORATION_TOOLS | QA_TOOLS | LOGGING_TOOLS | RESEARCH_TOOLS


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------


@dataclass
class LLMCall:
    model: str
    input_tokens: int
    output_tokens: int
    ttft_ms: int
    duration_ms: int
    timestamp: int


@dataclass
class ToolCall:
    name: str
    duration_ms: int
    status: str
    timestamp: int
    args_summary: str = ""


@dataclass
class AgentInvocation:
    """One invocation of an agent (root or subagent)."""

    agent_name: str
    session_id: str
    log_file: str
    timestamp: int = 0
    spawn_prompt: str = ""

    llm_calls: list[LLMCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    children: list[AgentInvocation] = field(default_factory=list)
    turn_count: int = 0
    wall_time_ms: int = 0

    # --- Token metrics ---

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.llm_calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.llm_calls)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def tree_tokens(self) -> int:
        return self.total_tokens + sum(c.tree_tokens for c in self.children)

    # --- Tool counts by category ---

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    @property
    def classified_tool_count(self) -> int:
        """Tool calls excluding noise/meta tools — denominator for ratios."""
        return sum(1 for t in self.tool_calls if t.name not in EXCLUDED_TOOLS)

    @property
    def management_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.name in MANAGEMENT_TOOLS)

    @property
    def editing_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.name in EDITING_TOOLS)

    @property
    def exploration_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.name in EXPLORATION_TOOLS)

    @property
    def qa_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.name in QA_TOOLS)

    @property
    def logging_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.name in LOGGING_TOOLS)

    @property
    def research_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.name in RESEARCH_TOOLS)

    @property
    def unclassified_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.name not in ALL_CLASSIFIED)

    # --- Efficiency metrics ---

    @property
    def failed_tool_calls(self) -> list[ToolCall]:
        return [t for t in self.tool_calls if t.status == "error"]

    @property
    def failure_count(self) -> int:
        return len(self.failed_tool_calls)

    @property
    def failure_rate(self) -> float:
        if not self.tool_calls:
            return 0.0
        return self.failure_count / len(self.tool_calls)

    @property
    def repeated_tool_calls(self) -> int:
        """Count consecutive same-tool calls (e.g. read_file followed by read_file)."""
        count = 0
        for i in range(1, len(self.tool_calls)):
            if self.tool_calls[i].name == self.tool_calls[i - 1].name:
                count += 1
        return count

    @property
    def tokens_per_mutation(self) -> float:
        """Token cost per edit — lower is more efficient."""
        mc = self.editing_count
        return self.total_tokens / mc if mc else 0.0

    @property
    def calls_before_first_dispatch(self) -> int | None:
        """Number of tool calls before first runSubagent. None if no dispatches."""
        for i, t in enumerate(self.tool_calls):
            if t.name in MANAGEMENT_TOOLS and t.name == "runSubagent":
                return i
        return None

    # --- Ratios ---

    @property
    def management_ratio(self) -> float:
        d = self.classified_tool_count
        return self.management_count / d if d else 0.0

    @property
    def editing_ratio(self) -> float:
        d = self.classified_tool_count
        return self.editing_count / d if d else 0.0

    @property
    def exploration_ratio(self) -> float:
        d = self.classified_tool_count
        return self.exploration_count / d if d else 0.0

    @property
    def qa_ratio(self) -> float:
        d = self.classified_tool_count
        return self.qa_count / d if d else 0.0

    @property
    def logging_ratio(self) -> float:
        d = self.classified_tool_count
        return self.logging_count / d if d else 0.0

    @property
    def research_ratio(self) -> float:
        d = self.classified_tool_count
        return self.research_count / d if d else 0.0

    @property
    def models_used(self) -> set[str]:
        return {c.model for c in self.llm_calls}

    @property
    def avg_ttft_ms(self) -> float:
        if not self.llm_calls:
            return 0.0
        return sum(c.ttft_ms for c in self.llm_calls) / len(self.llm_calls)


@dataclass
class Session:
    """A top-level chat session."""

    session_id: str
    session_dir: str  # str instead of Path for serialization simplicity
    timestamp: int = 0
    root: AgentInvocation | None = None


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


@dataclass
class AgentAggregate:
    agent_name: str
    invocations: list[AgentInvocation] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.invocations)

    @property
    def total_tokens(self) -> int:
        return sum(i.total_tokens for i in self.invocations)

    @property
    def avg_tokens(self) -> float:
        return self.total_tokens / self.count if self.count else 0

    @property
    def total_tree_tokens(self) -> int:
        return sum(i.tree_tokens for i in self.invocations)

    @property
    def avg_tool_calls(self) -> float:
        return sum(i.tool_call_count for i in self.invocations) / self.count if self.count else 0

    @property
    def avg_management_ratio(self) -> float:
        ratios = [i.management_ratio for i in self.invocations if i.tool_calls]
        return sum(ratios) / len(ratios) if ratios else 0

    @property
    def avg_editing_ratio(self) -> float:
        ratios = [i.editing_ratio for i in self.invocations if i.tool_calls]
        return sum(ratios) / len(ratios) if ratios else 0

    @property
    def avg_exploration_ratio(self) -> float:
        ratios = [i.exploration_ratio for i in self.invocations if i.tool_calls]
        return sum(ratios) / len(ratios) if ratios else 0

    @property
    def avg_qa_ratio(self) -> float:
        ratios = [i.qa_ratio for i in self.invocations if i.tool_calls]
        return sum(ratios) / len(ratios) if ratios else 0

    @property
    def avg_logging_ratio(self) -> float:
        ratios = [i.logging_ratio for i in self.invocations if i.tool_calls]
        return sum(ratios) / len(ratios) if ratios else 0

    @property
    def avg_research_ratio(self) -> float:
        ratios = [i.research_ratio for i in self.invocations if i.tool_calls]
        return sum(ratios) / len(ratios) if ratios else 0

    @property
    def avg_calls_before_dispatch(self) -> float | None:
        vals = [i.calls_before_first_dispatch for i in self.invocations if i.calls_before_first_dispatch is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def avg_turns(self) -> float:
        return sum(i.turn_count for i in self.invocations) / self.count if self.count else 0

    @property
    def avg_failure_rate(self) -> float:
        rates = [i.failure_rate for i in self.invocations if i.tool_calls]
        return sum(rates) / len(rates) if rates else 0

    @property
    def total_failures(self) -> int:
        return sum(i.failure_count for i in self.invocations)

    @property
    def avg_tokens_per_mutation(self) -> float:
        vals = [i.tokens_per_mutation for i in self.invocations if i.tokens_per_mutation > 0]
        return sum(vals) / len(vals) if vals else 0

    @property
    def models_used(self) -> set[str]:
        models: set[str] = set()
        for i in self.invocations:
            models.update(i.models_used)
        return models


# ---------------------------------------------------------------------------
# Tool-level aggregate
# ---------------------------------------------------------------------------


@dataclass
class ToolAggregate:
    """Per-tool metrics across all agents."""

    name: str
    total_calls: int = 0
    failures: int = 0
    repeats: int = 0
    total_duration_ms: int = 0
    agents: set[str] = field(default_factory=set)

    @property
    def failure_rate(self) -> float:
        return self.failures / self.total_calls if self.total_calls else 0.0

    @property
    def repeat_rate(self) -> float:
        return self.repeats / self.total_calls if self.total_calls else 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.total_calls if self.total_calls else 0.0

    @property
    def category(self) -> str:
        if self.name in EXCLUDED_TOOLS:
            return "excluded"
        if self.name in MANAGEMENT_TOOLS:
            return "management"
        if self.name in EDITING_TOOLS:
            return "editing"
        if self.name in EXPLORATION_TOOLS:
            return "exploration"
        if self.name in QA_TOOLS:
            return "qa"
        if self.name in LOGGING_TOOLS:
            return "logging"
        if self.name in RESEARCH_TOOLS:
            return "research"
        return "other"


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def collect_all_invocations(inv: AgentInvocation) -> list[AgentInvocation]:
    """Flatten the invocation tree."""
    result = [inv]
    for child in inv.children:
        result.extend(collect_all_invocations(child))
    return result


def compute_aggregates(sessions: list[Session]) -> dict[str, AgentAggregate]:
    aggregates: dict[str, AgentAggregate] = {}
    for session in sessions:
        if not session.root:
            continue
        for inv in collect_all_invocations(session.root):
            if inv.agent_name not in aggregates:
                aggregates[inv.agent_name] = AgentAggregate(agent_name=inv.agent_name)
            aggregates[inv.agent_name].invocations.append(inv)
    return aggregates


def compute_tool_aggregates(sessions: list[Session]) -> dict[str, ToolAggregate]:
    """Compute per-tool metrics across all sessions."""
    tools: dict[str, ToolAggregate] = {}
    for session in sessions:
        if not session.root:
            continue
        for inv in collect_all_invocations(session.root):
            prev_name: str | None = None
            for tc in inv.tool_calls:
                if tc.name not in tools:
                    tools[tc.name] = ToolAggregate(name=tc.name)
                ta = tools[tc.name]
                ta.total_calls += 1
                ta.total_duration_ms += tc.duration_ms
                ta.agents.add(inv.agent_name)
                if tc.status == "error":
                    ta.failures += 1
                if tc.name == prev_name:
                    ta.repeats += 1
                prev_name = tc.name
    return tools
