"""Golden tests for plan_md parser - captures exact behavior before tree-sitter migration.

These tests document the expected outputs for the plan parser to ensure that the
tree-sitter implementation produces identical results to the regex-based implementation.
"""

from pathlib import Path

import pytest

from mcp_code_intel.helpers.plan_md import Phase, Step, parse_plan

# Golden test cases - expected behaviors documented
VALID_SIMPLE_PLAN = """# Task: Simple Test Plan

## Problem Statement

This is a test.

## Phases

### Phase 1: First Phase

- [ ] First step
- [x] Second step completed
- [ ] Third step

### Phase 2: Second Phase

- [ ] Another step

## Completion Criteria

- Success is obvious
"""

NESTED_CHECKBOX_PLAN = """# Task: Nested Steps (Should Error)

## Phases

### Phase 1: Test

- [ ] Top level step
  - [ ] Nested step (invalid)
"""

MALFORMED_CHECKBOXES = {
    "no_space_after": """# Task: Test

## Phases

### Phase 1: Test

- [ ]No space after checkbox
""",
    "no_space_before": """# Task: Test

## Phases

### Phase 1: Test

-[ ] No space before bracket
""",
    "empty_brackets": """# Task: Test

## Phases

### Phase 1: Test

- [] Empty brackets
""",
    "numbered_list": """# Task: Test

## Phases

### Phase 1: Test

1. Numbered item instead of checkbox
""",
    "wrong_bullet": """# Task: Test

## Phases

### Phase 1: Test

* [ ] Wrong bullet marker
""",
    "bare_bullet": """# Task: Test

## Phases

### Phase 1: Test

- Bare bullet at step level
""",
}

STEP_WITH_ANNOTATIONS = """# Task: Complex Step Test

## Problem Statement

Test annotations under steps.

## Phases

### Phase 1: Test Phase

- [ ] Step with notes
    **Notes:** This is a note
    continuation line
- [x] Step with warning
    **Warning:** Be careful here
- [ ] Step with bullets
    - bullet one
    - bullet two
- [ ] Multi-line step text
    continued on next line
    and another

## Completion Criteria

- All annotations parsed
"""


class TestGoldenBehavior:
    """Tests that capture current parser behavior as golden standard."""

    def test_simple_plan_structure(self):
        """Verify basic plan structure parsing."""
        plan = parse_plan(VALID_SIMPLE_PLAN)

        assert plan.title == "Simple Test Plan"
        assert len(plan.phases) == 2

        # Phase 1
        phase1 = plan.phases[0]
        assert phase1.number == 1
        assert phase1.title == "First Phase"
        assert len(phase1.steps) == 3

        # Verify step details
        assert phase1.steps[0].text == "First step"
        assert phase1.steps[0].checked is False
        assert phase1.steps[0].depth == 0

        assert phase1.steps[1].text == "Second step completed"
        assert phase1.steps[1].checked is True
        assert phase1.steps[1].depth == 0

        assert phase1.steps[2].text == "Third step"
        assert phase1.steps[2].checked is False

        # Phase 2
        phase2 = plan.phases[1]
        assert phase2.number == 2
        assert phase2.title == "Second Phase"
        assert len(phase2.steps) == 1
        assert phase2.steps[0].text == "Another step"

        # Verify sections
        assert "Problem Statement" in plan.sections
        assert plan.sections["Problem Statement"] == "This is a test."
        assert "Completion Criteria" in plan.sections

    def test_nested_steps_raise_error(self):
        """Nested checkboxes must raise ValueError."""
        with pytest.raises(ValueError, match="nested steps"):
            parse_plan(NESTED_CHECKBOX_PLAN)

    def test_malformed_no_space_after(self):
        """Checkbox without space after ] must be caught."""
        with pytest.raises(ValueError, match="malformed"):
            parse_plan(MALFORMED_CHECKBOXES["no_space_after"])

    def test_malformed_no_space_before(self):
        """Checkbox without space before [ must be caught."""
        with pytest.raises(ValueError, match="malformed"):
            parse_plan(MALFORMED_CHECKBOXES["no_space_before"])

    def test_malformed_empty_brackets(self):
        """Empty checkbox brackets must be caught."""
        with pytest.raises(ValueError, match="malformed"):
            parse_plan(MALFORMED_CHECKBOXES["empty_brackets"])

    def test_malformed_numbered_list(self):
        """Numbered lists in phase must be caught."""
        with pytest.raises(ValueError, match="numbered list"):
            parse_plan(MALFORMED_CHECKBOXES["numbered_list"])

    def test_malformed_wrong_bullet(self):
        """Wrong bullet marker (* or +) must be caught."""
        with pytest.raises(ValueError, match="wrong bullet marker"):
            parse_plan(MALFORMED_CHECKBOXES["wrong_bullet"])

    def test_malformed_bare_bullet(self):
        """Bare bullet at step level must be caught."""
        with pytest.raises(ValueError, match="bare bullet"):
            parse_plan(MALFORMED_CHECKBOXES["bare_bullet"])

    def test_step_annotations(self):
        """Verify step annotations are captured correctly."""
        plan = parse_plan(STEP_WITH_ANNOTATIONS)

        phase = plan.phases[0]
        assert len(phase.steps) == 4

        # Step 1: Notes annotation
        step1 = phase.steps[0]
        assert step1.text == "Step with notes"
        assert "Notes" in step1.properties
        assert "This is a note" in step1.properties["Notes"]
        assert "continuation line" in step1.properties["Notes"]

        # Step 2: Warning annotation
        step2 = phase.steps[1]
        assert step2.text == "Step with warning"
        assert step2.checked is True
        assert "Warning" in step2.properties
        assert "Be careful here" in step2.properties["Warning"]

        # Step 3: Bullet annotations
        step3 = phase.steps[2]
        assert step3.text == "Step with bullets"
        assert "bullets" in step3.properties
        bullets_text = step3.properties["bullets"]
        assert "bullet one" in bullets_text
        assert "bullet two" in bullets_text

        # Step 4: Multi-line step text
        step4 = phase.steps[3]
        assert "Multi-line step text" in step4.text
        assert "continued on next line" in step4.text
        assert "and another" in step4.text

    def test_line_numbers_preserved(self):
        """Verify line numbers are correctly tracked (0-indexed)."""
        plan = parse_plan(VALID_SIMPLE_PLAN)

        # Find line number for first step "- [ ] First step"
        lines = VALID_SIMPLE_PLAN.splitlines()
        expected_line = next(i for i, line in enumerate(lines) if "First step" in line)

        assert plan.phases[0].steps[0].line_number == expected_line

    def test_whitespace_trimming(self):
        """Verify consistent whitespace handling in step text."""
        plan_with_spaces = """# Task: Whitespace Test

## Phases

### Phase 1: Test

- [ ]   Multiple   spaces   in   text
- [x] Trailing spaces
"""
        plan = parse_plan(plan_with_spaces)

        # Step text should be stripped
        assert plan.phases[0].steps[0].text == "Multiple   spaces   in   text"
        assert plan.phases[0].steps[1].text == "Trailing spaces"

    def test_case_insensitive_checkbox(self):
        """Verify [X] and [x] both mark as checked."""
        plan_upper = """# Task: Test

## Phases

### Phase 1: Test

- [X] Upper case checked
- [x] Lower case checked
"""
        plan = parse_plan(plan_upper)

        assert plan.phases[0].steps[0].checked is True
        assert plan.phases[0].steps[1].checked is True

    def test_empty_phases_allowed(self):
        """Phases without steps should be allowed."""
        plan_empty = """# Task: Test

## Phases

### Phase 1: Empty Phase

### Phase 2: Has Steps

- [ ] A step
"""
        plan = parse_plan(plan_empty)

        assert len(plan.phases) == 2
        assert len(plan.phases[0].steps) == 0
        assert len(plan.phases[1].steps) == 1


class TestRealWorldPlans:
    """Test against actual plan files from the codebase."""

    def test_parse_example_comprehensive(self):
        """Parse TASK-example-comprehensive.md without errors."""
        plan_path = (
            Path(__file__).parent.parent.parent.parent.parent
            / "plans"
            / "TASK-example-comprehensive.md"
        )
        if not plan_path.exists():
            pytest.skip("Example plan not found")

        content = plan_path.read_text(encoding="utf-8")
        plan = parse_plan(content)

        # Basic structure checks
        assert plan.title is not None
        assert len(plan.phases) > 0
        assert all(isinstance(p, Phase) for p in plan.phases)
        assert all(isinstance(s, Step) for s in plan.phases[0].steps)

    def test_parse_example_nested_content(self):
        """Parse TASK-example-nested-content.md with annotations."""
        plan_path = (
            Path(__file__).parent.parent.parent.parent.parent
            / "plans"
            / "TASK-example-nested-content.md"
        )
        if not plan_path.exists():
            pytest.skip("Example plan not found")

        content = plan_path.read_text(encoding="utf-8")
        plan = parse_plan(content)

        # Should have step with annotations
        assert len(plan.phases) > 0
        if len(plan.phases[0].steps) > 0:
            # At least one step should have properties (annotations)
            has_properties = any(step.properties for step in plan.phases[0].steps)
            assert has_properties

    def test_malformed_plan_errors(self):
        """TASK-example-malformed.md should parse (it's intentionally not a plan format)."""
        plan_path = (
            Path(__file__).parent.parent.parent.parent.parent
            / "plans"
            / "TASK-example-malformed.md"
        )
        if not plan_path.exists():
            pytest.skip("Example plan not found")

        content = plan_path.read_text(encoding="utf-8")
        # This file has no phases, should parse without error (just unusual structure)
        plan = parse_plan(content)
        assert len(plan.phases) == 0  # No valid phase headers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
