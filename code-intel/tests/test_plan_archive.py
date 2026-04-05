"""Tests for plan_archive tool.

Covers:
- Happy path (all steps checked)
- Incomplete steps error
- Blocked steps warning
- ignore_blocked override
- Not found
- Path traversal rejection
- Parse error
"""

import textwrap
from pathlib import Path

from mcp_code_intel.tools.plan_archive import (
    PLANS_COMPLETED_DIR,
    PLANS_PENDING_DIR,
    plan_archive,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(tmp_path: Path, name: str, content: str) -> Path:
    pending = tmp_path / PLANS_PENDING_DIR
    pending.mkdir(parents=True, exist_ok=True)
    path = pending / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


ALL_DONE_PLAN = textwrap.dedent("""\
    # Task: All Done Plan

    ## Problem Statement
    Everything is complete.

    ## Phases

    ### Phase 1: Work
    - [x] Step one
    - [x] Step two

    ### Phase 2: Verify
    - [x] Step three

    ## Completion Criteria
    All done.
""")

INCOMPLETE_PLAN = textwrap.dedent("""\
    # Task: Incomplete Plan

    ## Phases

    ### Phase 1: Work
    - [x] Done step
    - [ ] Not done step

    ## Completion Criteria
    Pending.
""")

BLOCKED_PLAN = textwrap.dedent("""\
    # Task: Blocked Plan

    ## Phases

    ### Phase 1: Work
    - [x] Completed step
        **Blocked:** External API unavailable
    - [x] Another done step

    ## Completion Criteria
    Done with caveats.
""")


# ---------------------------------------------------------------------------
# plan_archive — happy path
# ---------------------------------------------------------------------------


def test_plan_archive_happy_path(tmp_path: Path) -> None:
    _make_plan(tmp_path, "TASK-test-A-work", ALL_DONE_PLAN)
    result = plan_archive(plan_name="TASK-test-A-work", workspace_root=tmp_path)
    assert result["archived"] is True
    assert result["steps_completed"] == 3
    assert PLANS_COMPLETED_DIR in result["path"]
    # Source gone, dest exists
    assert not (tmp_path / PLANS_PENDING_DIR / "TASK-test-A-work.md").exists()
    assert (tmp_path / PLANS_COMPLETED_DIR / "TASK-test-A-work.md").exists()


def test_plan_archive_with_md_extension(tmp_path: Path) -> None:
    _make_plan(tmp_path, "TASK-ext-A-work", ALL_DONE_PLAN)
    result = plan_archive(plan_name="TASK-ext-A-work.md", workspace_root=tmp_path)
    assert result["archived"] is True


# ---------------------------------------------------------------------------
# plan_archive — incomplete steps
# ---------------------------------------------------------------------------


def test_plan_archive_incomplete_steps(tmp_path: Path) -> None:
    _make_plan(tmp_path, "TASK-inc-A-work", INCOMPLETE_PLAN)
    result = plan_archive(plan_name="TASK-inc-A-work", workspace_root=tmp_path)
    assert result["error"] == "incomplete_steps"
    assert "P1-S2" in result["incomplete_steps"]


# ---------------------------------------------------------------------------
# plan_archive — blocked steps
# ---------------------------------------------------------------------------


def test_plan_archive_blocked_steps(tmp_path: Path) -> None:
    _make_plan(tmp_path, "TASK-blk-A-work", BLOCKED_PLAN)
    result = plan_archive(plan_name="TASK-blk-A-work", workspace_root=tmp_path)
    assert result["error"] == "blocked_steps"
    assert "P1-S1" in result["blocked_steps"]


def test_plan_archive_ignore_blocked(tmp_path: Path) -> None:
    _make_plan(tmp_path, "TASK-ign-A-work", BLOCKED_PLAN)
    result = plan_archive(plan_name="TASK-ign-A-work", ignore_blocked=True, workspace_root=tmp_path)
    assert result["archived"] is True


# ---------------------------------------------------------------------------
# plan_archive — error cases
# ---------------------------------------------------------------------------


def test_plan_archive_not_found(tmp_path: Path) -> None:
    result = plan_archive(plan_name="TASK-missing-A-work", workspace_root=tmp_path)
    assert result["error"] == "not_found"


def test_plan_archive_empty_name(tmp_path: Path) -> None:
    result = plan_archive(plan_name="", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_plan_archive_path_traversal(tmp_path: Path) -> None:
    result = plan_archive(plan_name="../../../etc/passwd", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_plan_archive_backslash_traversal(tmp_path: Path) -> None:
    result = plan_archive(plan_name="..\\..\\etc", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_plan_archive_parse_error(tmp_path: Path) -> None:
    """Truly malformed markdown (e.g. nested steps) triggers parse_error."""
    bad_plan = textwrap.dedent("""\
        # Task: Bad

        ## Phases

        ### Phase 1: X
        - [x] Parent step
            - [x] Nested child step

        ## Completion Criteria
        Done.
    """)
    _make_plan(tmp_path, "TASK-bad-A-work", bad_plan)
    result = plan_archive(plan_name="TASK-bad-A-work", workspace_root=tmp_path)
    assert result["error"] == "parse_error"
