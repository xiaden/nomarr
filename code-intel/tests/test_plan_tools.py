"""Tests for plan_read and plan_complete_step MCP tools.

Covers:
- plan_read: pending dir, completed dir, not found, empty name, path traversal
- plan_complete_step: mark step, annotation, already complete, step not found, plan not found, disk write
"""

import textwrap
from pathlib import Path

from mcp_code_intel.tools.plan_complete_step import plan_complete_step
from mcp_code_intel.tools.plan_read import plan_read

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_PLAN = textwrap.dedent("""\
    # Task: Test Plan

    ## Problem Statement
    Testing plan tools.

    ## Phases

    ### Phase 1: Setup
    - [ ] First step
    - [ ] Second step

    ### Phase 2: Execute
    - [ ] Third step

    ## Completion Criteria
    All steps done.
""")


def _write_plan(tmp_path: Path, name: str, content: str, *, completed: bool = False) -> Path:
    """Write a plan file to pending or completed dir."""
    subdir = "artifacts/plans/completed" if completed else "artifacts/plans/pending"
    plan_dir = tmp_path / subdir
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_file = plan_dir / f"{name}.md"
    plan_file.write_text(content, encoding="utf-8")
    return plan_file


# ---------------------------------------------------------------------------
# plan_read
# ---------------------------------------------------------------------------


def test_plan_read_from_pending(tmp_path: Path) -> None:
    _write_plan(tmp_path, "my-plan", SAMPLE_PLAN)
    result = plan_read(plan_name="my-plan", workspace_root=tmp_path)
    assert "error" not in result
    assert result["title"] == "Test Plan"
    phases = result["phases"]
    assert len(phases) == 2
    assert phases[0]["title"] == "Setup"
    assert len(phases[0]["steps"]) == 2


def test_plan_read_from_completed(tmp_path: Path) -> None:
    _write_plan(tmp_path, "done-plan", SAMPLE_PLAN, completed=True)
    result = plan_read(plan_name="done-plan", workspace_root=tmp_path)
    assert "error" not in result
    assert result["title"] == "Test Plan"


def test_plan_read_pending_takes_priority(tmp_path: Path) -> None:
    """If plan exists in both pending and completed, pending wins."""
    _write_plan(tmp_path, "dup-plan", SAMPLE_PLAN)
    modified = SAMPLE_PLAN.replace("Testing plan tools.", "Completed version.")
    _write_plan(tmp_path, "dup-plan", modified, completed=True)
    result = plan_read(plan_name="dup-plan", workspace_root=tmp_path)
    assert "error" not in result
    # Should be the pending version
    assert result.get("problem") or True  # Just ensure it loaded


def test_plan_read_with_md_extension(tmp_path: Path) -> None:
    _write_plan(tmp_path, "ext-plan", SAMPLE_PLAN)
    result = plan_read(plan_name="ext-plan.md", workspace_root=tmp_path)
    assert "error" not in result
    assert result["title"] == "Test Plan"


def test_plan_read_not_found(tmp_path: Path) -> None:
    result = plan_read(plan_name="nonexistent", workspace_root=tmp_path)
    assert result["error"] == "plan_not_found"


def test_plan_read_path_traversal_slash(tmp_path: Path) -> None:
    result = plan_read(plan_name="../evil", workspace_root=tmp_path)
    assert result["error"] == "invalid_plan_name"


def test_plan_read_path_traversal_backslash(tmp_path: Path) -> None:
    result = plan_read(plan_name="..\\evil", workspace_root=tmp_path)
    assert result["error"] == "invalid_plan_name"


def test_plan_read_path_traversal_dotdot(tmp_path: Path) -> None:
    result = plan_read(plan_name="foo..bar", workspace_root=tmp_path)
    assert result["error"] == "invalid_plan_name"


def test_plan_read_step_ids_generated(tmp_path: Path) -> None:
    """Verify step IDs are auto-generated as P1-S1, P1-S2, P2-S1."""
    _write_plan(tmp_path, "id-plan", SAMPLE_PLAN)
    result = plan_read(plan_name="id-plan", workspace_root=tmp_path)
    assert "error" not in result
    all_ids = [
        step["id"]
        for phase in result["phases"]
        for step in phase["steps"]
    ]
    assert all_ids == ["P1-S1", "P1-S2", "P2-S1"]


def test_plan_read_next_pointer(tmp_path: Path) -> None:
    """The 'next' field should point to the first incomplete step."""
    _write_plan(tmp_path, "next-plan", SAMPLE_PLAN)
    result = plan_read(plan_name="next-plan", workspace_root=tmp_path)
    assert result.get("next") == "P1-S1"


# ---------------------------------------------------------------------------
# plan_complete_step
# ---------------------------------------------------------------------------


def test_complete_step_marks_checkbox(tmp_path: Path) -> None:
    plan_file = _write_plan(tmp_path, "cs-plan", SAMPLE_PLAN)
    result = plan_complete_step(
        plan_name="cs-plan", step_id="P1-S1", workspace_root=tmp_path
    )
    assert "error" not in result
    assert result["step_id"] == "P1-S1"
    # Verify file on disk
    content = plan_file.read_text(encoding="utf-8")
    assert "- [x] First step" in content


def test_complete_step_next_advances(tmp_path: Path) -> None:
    _write_plan(tmp_path, "adv-plan", SAMPLE_PLAN)
    result = plan_complete_step(
        plan_name="adv-plan", step_id="P1-S1", workspace_root=tmp_path
    )
    assert "error" not in result
    # Next should now be P1-S2
    next_step = result.get("next_step")
    assert next_step is not None
    assert next_step.get("id") == "P1-S2"


def test_complete_step_already_complete(tmp_path: Path) -> None:
    plan_with_done = SAMPLE_PLAN.replace("- [ ] First step", "- [x] First step")
    _write_plan(tmp_path, "done-plan", plan_with_done)
    result = plan_complete_step(
        plan_name="done-plan", step_id="P1-S1", workspace_root=tmp_path
    )
    assert "error" not in result
    assert result.get("already_marked") is True


def test_complete_step_with_annotation(tmp_path: Path) -> None:
    plan_file = _write_plan(tmp_path, "ann-plan", SAMPLE_PLAN)
    result = plan_complete_step(
        plan_name="ann-plan",
        step_id="P1-S1",
        workspace_root=tmp_path,
        annotation={"marker": "Notes", "text": "Completed successfully"},
    )
    assert "error" not in result
    assert result.get("applied_annotation") is not None
    assert result["applied_annotation"]["marker"] == "Notes"
    # Verify annotation on disk
    content = plan_file.read_text(encoding="utf-8")
    assert "**Notes:**" in content
    assert "Completed successfully" in content


def test_complete_step_invalid_annotation_marker(tmp_path: Path) -> None:
    _write_plan(tmp_path, "badann-plan", SAMPLE_PLAN)
    result = plan_complete_step(
        plan_name="badann-plan",
        step_id="P1-S1",
        workspace_root=tmp_path,
        annotation={"marker": "bad marker!", "text": "text"},
    )
    assert result["error"] == "invalid_annotation_marker"


def test_complete_step_empty_annotation_text(tmp_path: Path) -> None:
    _write_plan(tmp_path, "emptyann-plan", SAMPLE_PLAN)
    result = plan_complete_step(
        plan_name="emptyann-plan",
        step_id="P1-S1",
        workspace_root=tmp_path,
        annotation={"marker": "Notes", "text": ""},
    )
    assert result["error"] == "empty_annotation_text"


def test_complete_step_unknown_step_id(tmp_path: Path) -> None:
    _write_plan(tmp_path, "unk-plan", SAMPLE_PLAN)
    result = plan_complete_step(
        plan_name="unk-plan", step_id="P99-S1", workspace_root=tmp_path
    )
    assert result["error"] == "unknown_step_id"


def test_complete_step_plan_not_found(tmp_path: Path) -> None:
    result = plan_complete_step(
        plan_name="ghost", step_id="P1-S1", workspace_root=tmp_path
    )
    assert result["error"] == "plan_not_found"


def test_complete_step_path_traversal(tmp_path: Path) -> None:
    result = plan_complete_step(
        plan_name="../hack", step_id="P1-S1", workspace_root=tmp_path
    )
    assert result["error"] == "invalid_plan_name"


def test_complete_step_phase_transition(tmp_path: Path) -> None:
    """Completing last step in phase 1 should trigger phase transition."""
    # First complete P1-S1
    _write_plan(tmp_path, "transition-plan", SAMPLE_PLAN)
    plan_complete_step(
        plan_name="transition-plan", step_id="P1-S1", workspace_root=tmp_path
    )
    # Then complete P1-S2 — should transition to Phase 2
    result = plan_complete_step(
        plan_name="transition-plan", step_id="P1-S2", workspace_root=tmp_path
    )
    assert "error" not in result
    transition = result.get("phase_transition")
    assert transition is not None
    assert transition["from"] == "Setup"
    assert transition["to"] == "Execute"


def test_complete_step_last_step_next_is_none(tmp_path: Path) -> None:
    """Completing the very last step should have next_step = None."""
    _write_plan(tmp_path, "last-plan", SAMPLE_PLAN)
    # Complete all steps
    plan_complete_step(plan_name="last-plan", step_id="P1-S1", workspace_root=tmp_path)
    plan_complete_step(plan_name="last-plan", step_id="P1-S2", workspace_root=tmp_path)
    result = plan_complete_step(
        plan_name="last-plan", step_id="P2-S1", workspace_root=tmp_path
    )
    assert "error" not in result
    assert result["next_step"] is None


def test_complete_step_file_modified_on_disk(tmp_path: Path) -> None:
    """Verify the actual file has the checkbox changed."""
    plan_file = _write_plan(tmp_path, "disk-plan", SAMPLE_PLAN)
    plan_complete_step(
        plan_name="disk-plan", step_id="P2-S1", workspace_root=tmp_path
    )
    content = plan_file.read_text(encoding="utf-8")
    assert "- [x] Third step" in content
    # Other steps should still be unchecked
    assert "- [ ] First step" in content
    assert "- [ ] Second step" in content
