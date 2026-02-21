"""Tests for plan_md parser and mutation functions.

Covers:
- parse_plan: title, phases, steps, annotations, multibyte chars
- plan_to_dict: output shape, step IDs, next pointer
- find_step: lookup by ID
- get_next_step_info: first incomplete step
- mark_step_complete: checkbox mutation, annotation insertion, idempotency
- _add_annotation_to_step: new markers, append to existing, dedup
- get_phase_notes: phase property lookup
- Validation: malformed syntax raises ValueError
"""

import textwrap

import pytest

from mcp_code_intel.helpers.plan_md import (
    _add_annotation_to_step,
    find_step,
    get_next_step_info,
    get_phase_notes,
    mark_step_complete,
    parse_plan,
    plan_to_dict,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


MINIMAL_PLAN = textwrap.dedent("""\
    # Task: Minimal Plan

    ## Problem Statement
    Short description.

    ## Phases

    ### Phase 1: Only Phase
    - [ ] First step
    - [x] Second step already done

    ## Completion Criteria
    It works.
""")


MULTI_PHASE_PLAN = textwrap.dedent("""\
    # Task: Multi Phase Plan

    ## Problem Statement
    Does things across phases.

    ## Phases

    ### Phase 1: Discovery
    - [ ] Find the code
    - [x] Read the code

    ### Phase 2: Implementation
    - [ ] Write the code
    - [ ] Test the code

    ## Completion Criteria
    All green.
""")


ANNOTATED_PLAN = textwrap.dedent("""\
    # Task: Annotated Plan

    ## Phases

    ### Phase 1: Work
    - [x] Completed step
        **Notes:** some detail about the step
        **Warning:** watch out
    - [ ] Pending step
        **Blocked:** waiting on external API

    ## Completion Criteria
    Done.
""")


MULTIBYTE_PLAN = textwrap.dedent("""\
    # Task: Multibyte Plan

    ## Phases

    ### Phase 1: Répertoire — Setup
    - [ ] Créer le dossier de configuration — étape initiale
    - [ ] Add UTF-8 string: \u4e2d\u6587\u5185\u5bb9 (Chinese chars)
    - [ ] Em\u2014dash in the middle of step text

    ## Completion Criteria
    Works with unicode.
""")


# ---------------------------------------------------------------------------
# parse_plan — basic structure
# ---------------------------------------------------------------------------


def test_parse_plan_title() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    assert plan.title == "Minimal Plan"


def test_parse_plan_title_with_task_prefix() -> None:
    md = "# Task: Explicit Prefix\n\n## Phases\n\n### Phase 1: X\n- [ ] step\n"
    plan = parse_plan(md)
    assert plan.title == "Explicit Prefix"


def test_parse_plan_sections() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    assert "Problem Statement" in plan.sections
    assert "Completion Criteria" in plan.sections


def test_parse_plan_phase_count() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    assert len(plan.phases) == 2


def test_parse_plan_phase_numbers_and_titles() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    assert plan.phases[0].number == 1
    assert plan.phases[0].title == "Discovery"
    assert plan.phases[1].number == 2
    assert plan.phases[1].title == "Implementation"


def test_parse_plan_step_count_per_phase() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    assert len(plan.phases[0].steps) == 2
    assert len(plan.phases[1].steps) == 2


def test_parse_plan_step_checked_state() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    steps = plan.phases[0].steps
    assert steps[0].checked is False
    assert steps[1].checked is True


def test_parse_plan_step_text() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    steps = plan.phases[0].steps
    assert steps[0].text == "First step"
    assert steps[1].text == "Second step already done"


def test_parse_plan_raw_lines_preserved() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    reconstructed = "".join(plan.raw_lines)
    assert reconstructed == MINIMAL_PLAN


# ---------------------------------------------------------------------------
# parse_plan — step annotations
# ---------------------------------------------------------------------------


def test_parse_plan_step_notes_annotation() -> None:
    plan = parse_plan(ANNOTATED_PLAN)
    step = plan.phases[0].steps[0]  # Completed step
    assert "Notes" in step.properties
    assert step.properties["Notes"] == "some detail about the step"


def test_parse_plan_step_warning_annotation() -> None:
    plan = parse_plan(ANNOTATED_PLAN)
    step = plan.phases[0].steps[0]
    assert step.properties["Warning"] == "watch out"


def test_parse_plan_step_blocked_annotation() -> None:
    plan = parse_plan(ANNOTATED_PLAN)
    step = plan.phases[0].steps[1]  # Pending step
    assert step.properties["Blocked"] == "waiting on external API"


def test_parse_plan_unannotated_step_has_empty_properties() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    for phase in plan.phases:
        for step in phase.steps:
            assert step.properties == {}


# ---------------------------------------------------------------------------
# parse_plan — multibyte / unicode
# ---------------------------------------------------------------------------


def test_parse_plan_multibyte_step_text_not_truncated() -> None:
    """Byte-offset vs char-offset bug: step text must not be truncated."""
    plan = parse_plan(MULTIBYTE_PLAN)
    steps = plan.phases[0].steps
    assert steps[0].text == "Cr\u00e9er le dossier de configuration \u2014 \u00e9tape initiale"
    assert steps[1].text == "Add UTF-8 string: \u4e2d\u6587\u5185\u5bb9 (Chinese chars)"
    assert steps[2].text == "Em\u2014dash in the middle of step text"


def test_parse_plan_multibyte_phase_title() -> None:
    plan = parse_plan(MULTIBYTE_PLAN)
    assert plan.phases[0].title == "R\u00e9pertoire \u2014 Setup"


def test_parse_plan_multibyte_step_count() -> None:
    """Byte-offset bug should not cause steps to be merged or lost."""
    plan = parse_plan(MULTIBYTE_PLAN)
    assert len(plan.phases[0].steps) == 3


# ---------------------------------------------------------------------------
# parse_plan — validation errors
# ---------------------------------------------------------------------------


def test_parse_plan_rejects_nested_steps() -> None:
    md = textwrap.dedent("""\
        # Task: Bad

        ## Phases

        ### Phase 1: X
        - [ ] Parent step
            - [ ] Nested child step

        ## Completion Criteria
        Done.
    """)
    with pytest.raises(ValueError, match="nested steps"):
        parse_plan(md)


def test_parse_plan_rejects_malformed_checkbox() -> None:
    md = textwrap.dedent("""\
        # Task: Bad

        ## Phases

        ### Phase 1: X
        - []Missing space

        ## Completion Criteria
        Done.
    """)
    with pytest.raises(ValueError, match="malformed"):
        parse_plan(md)


def test_parse_plan_rejects_numbered_list() -> None:
    md = textwrap.dedent("""\
        # Task: Bad

        ## Phases

        ### Phase 1: X
        1. A numbered step

        ## Completion Criteria
        Done.
    """)
    with pytest.raises(ValueError, match="malformed"):
        parse_plan(md)


def test_parse_plan_rejects_non_integer_phase_number() -> None:
    md = textwrap.dedent("""\
        # Task: Bad

        ## Phases

        ### Phase 1a: Bad
        - [ ] step

        ## Completion Criteria
        Done.
    """)
    with pytest.raises(ValueError, match="Invalid phase number"):
        parse_plan(md)


# ---------------------------------------------------------------------------
# plan_to_dict
# ---------------------------------------------------------------------------


def test_plan_to_dict_title() -> None:
    d = plan_to_dict(parse_plan(MINIMAL_PLAN))
    assert d["title"] == "Minimal Plan"


def test_plan_to_dict_phases_present() -> None:
    d = plan_to_dict(parse_plan(MULTI_PHASE_PLAN))
    assert "phases" in d
    assert len(d["phases"]) == 2


def test_plan_to_dict_step_ids() -> None:
    d = plan_to_dict(parse_plan(MULTI_PHASE_PLAN))
    p1_steps = d["phases"][0]["steps"]
    assert p1_steps[0]["id"] == "P1-S1"
    assert p1_steps[1]["id"] == "P1-S2"
    p2_steps = d["phases"][1]["steps"]
    assert p2_steps[0]["id"] == "P2-S1"
    assert p2_steps[1]["id"] == "P2-S2"


def test_plan_to_dict_next_points_to_first_incomplete() -> None:
    d = plan_to_dict(parse_plan(MULTI_PHASE_PLAN))
    # P1-S1 is unchecked; P1-S2 is checked
    assert d["next"] == "P1-S1"


def test_plan_to_dict_next_skips_completed_phases() -> None:
    md = textwrap.dedent("""\
        # Task: Skip

        ## Phases

        ### Phase 1: Done
        - [x] Step A
        - [x] Step B

        ### Phase 2: Remaining
        - [ ] Step C

        ## Completion Criteria
        Done.
    """)
    d = plan_to_dict(parse_plan(md))
    assert d["next"] == "P2-S1"


def test_plan_to_dict_no_next_when_all_complete() -> None:
    md = textwrap.dedent("""\
        # Task: All Done

        ## Phases

        ### Phase 1: X
        - [x] Step one
        - [x] Step two

        ## Completion Criteria
        Done.
    """)
    d = plan_to_dict(parse_plan(md))
    assert "next" not in d


def test_plan_to_dict_step_done_field() -> None:
    d = plan_to_dict(parse_plan(MINIMAL_PLAN))
    steps = d["phases"][0]["steps"]
    assert steps[0]["done"] is False
    assert steps[1]["done"] is True


def test_plan_to_dict_step_annotations_present() -> None:
    d = plan_to_dict(parse_plan(ANNOTATED_PLAN))
    steps = d["phases"][0]["steps"]
    assert "annotations" in steps[0]
    assert steps[0]["annotations"]["Notes"] == "some detail about the step"


# ---------------------------------------------------------------------------
# find_step
# ---------------------------------------------------------------------------


def test_find_step_returns_correct_phase_and_step() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    result = find_step(plan, "P2-S1")
    assert result is not None
    phase, step, phase_num, step_idx = result
    assert phase_num == 2
    assert step_idx == 1
    assert step.text == "Write the code"


def test_find_step_returns_none_for_missing_step() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    assert find_step(plan, "P1-S99") is None


def test_find_step_returns_none_for_missing_phase() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    assert find_step(plan, "P9-S1") is None


def test_find_step_returns_none_for_invalid_id() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    assert find_step(plan, "not-an-id") is None


def test_find_step_case_insensitive() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    assert find_step(plan, "p1-s1") is not None


# ---------------------------------------------------------------------------
# get_next_step_info
# ---------------------------------------------------------------------------


def test_get_next_step_info_returns_first_incomplete() -> None:
    plan = parse_plan(MULTI_PHASE_PLAN)
    phase_title, step_id, step_dict = get_next_step_info(plan)
    assert step_id == "P1-S1"
    assert phase_title == "Discovery"
    assert step_dict is not None
    assert step_dict["text"] == "Find the code"


def test_get_next_step_info_skips_completed() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    # steps[0] is unchecked, steps[1] is checked
    _, step_id, _ = get_next_step_info(plan)
    assert step_id == "P1-S1"


def test_get_next_step_info_returns_none_when_all_done() -> None:
    md = textwrap.dedent("""\
        # Task: Done

        ## Phases

        ### Phase 1: X
        - [x] All done

        ## Completion Criteria
        Done.
    """)
    plan = parse_plan(md)
    phase_title, step_id, step_dict = get_next_step_info(plan)
    assert step_id is None
    assert phase_title is None
    assert step_dict is None


# ---------------------------------------------------------------------------
# mark_step_complete
# ---------------------------------------------------------------------------


def test_mark_step_complete_updates_checkbox_in_markdown() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    updated_md, was_done, _ = mark_step_complete(plan, "P1-S1")
    assert "- [x] First step" in updated_md
    assert was_done is False


def test_mark_step_complete_idempotent_on_already_done() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    _, was_done, _ = mark_step_complete(plan, "P1-S2")  # already [x]
    assert was_done is True


def test_mark_step_complete_raises_on_unknown_step() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    with pytest.raises(ValueError, match="not found"):
        mark_step_complete(plan, "P1-S99")


def test_mark_step_complete_with_annotation() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    updated_md, _, annotation_written = mark_step_complete(
        plan, "P1-S1", annotation={"marker": "Notes", "text": "finished cleanly"}
    )
    assert annotation_written is True
    assert "**Notes:** finished cleanly" in updated_md


def test_mark_step_complete_annotation_idempotent() -> None:
    """Calling with same annotation twice should not duplicate."""
    plan = parse_plan(MINIMAL_PLAN)
    mark_step_complete(plan, "P1-S1", annotation={"marker": "Notes", "text": "done"})
    # Re-parse from updated raw_lines and do it again
    updated_md = "".join(plan.raw_lines)
    plan2 = parse_plan(updated_md)
    _, _, written_again = mark_step_complete(
        plan2, "P1-S1", annotation={"marker": "Notes", "text": "done"}
    )
    assert written_again is False


# ---------------------------------------------------------------------------
# _add_annotation_to_step
# ---------------------------------------------------------------------------


def test_add_annotation_new_marker() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    step = plan.phases[0].steps[0]
    result = _add_annotation_to_step(plan, step, "Notes", "important context")
    assert result is True
    md = "".join(plan.raw_lines)
    assert "**Notes:** important context" in md


def test_add_annotation_appends_to_existing_marker() -> None:
    plan = parse_plan(ANNOTATED_PLAN)
    step = plan.phases[0].steps[0]  # Already has Notes + Warning
    result = _add_annotation_to_step(plan, step, "Notes", "second note")
    assert result is True
    md = "".join(plan.raw_lines)
    assert "second note" in md


def test_add_annotation_deduplicates_identical_text() -> None:
    plan = parse_plan(ANNOTATED_PLAN)
    step = plan.phases[0].steps[0]  # Has Notes: "some detail about the step"
    result = _add_annotation_to_step(plan, step, "Notes", "some detail about the step")
    assert result is False  # Already present


def test_add_annotation_multiple_distinct_markers() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    step = plan.phases[0].steps[0]
    _add_annotation_to_step(plan, step, "Notes", "note text")
    _add_annotation_to_step(plan, step, "Warning", "warning text")
    md = "".join(plan.raw_lines)
    assert "**Notes:** note text" in md
    assert "**Warning:** warning text" in md


# ---------------------------------------------------------------------------
# get_phase_notes
# ---------------------------------------------------------------------------


def test_get_phase_notes_returns_none_for_missing_phase() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    assert get_phase_notes(plan, "Nonexistent Phase") is None


def test_get_phase_notes_returns_none_when_no_notes() -> None:
    plan = parse_plan(MINIMAL_PLAN)
    assert get_phase_notes(plan, "Only Phase") is None


def test_get_phase_notes_returns_value_when_present() -> None:
    md = textwrap.dedent("""\
        # Task: With Notes

        ## Phases

        ### Phase 1: Prep
        **Notes:** This phase requires root access.
        - [ ] Do the thing

        ## Completion Criteria
        Done.
    """)
    plan = parse_plan(md)
    notes = get_phase_notes(plan, "Prep")
    assert notes == "This phase requires root access."


def test_get_phase_notes_case_insensitive_title() -> None:
    md = textwrap.dedent("""\
        # Task: CI

        ## Phases

        ### Phase 1: Setup
        **Notes:** something
        - [ ] step

        ## Completion Criteria
        Done.
    """)
    plan = parse_plan(md)
    assert get_phase_notes(plan, "SETUP") == "something"
    assert get_phase_notes(plan, "setup") == "something"


# ---------------------------------------------------------------------------
# Round-trip: real plan file
# ---------------------------------------------------------------------------


_REAL_PLAN = textwrap.dedent("""\
    # Task: Navidrome Integration A \u2014 Subsonic API Client & Playlist Push

    ## Problem Statement
    Nomarr\u2019s current Navidrome integration is entirely one-way.

    ## Phases

    ### Phase 1: Config & Subsonic Client Infrastructure
    - [x] Extend NavidromeConfig dataclass \u2014 add api_url, api_user, api_password
    - [ ] Create nomarr/components/navidrome/subsonic_client_comp.py \u2014 thin async HTTP client

    ### Phase 2: Direct Playlist Push
    - [ ] Create playlist_sync_comp.py

    ## Completion Criteria
    Lint passes.
""")


def test_real_plan_parses_without_error() -> None:
    plan = parse_plan(_REAL_PLAN)
    assert plan.title is not None
    assert len(plan.phases) == 2


def test_real_plan_multibyte_step_text_complete() -> None:
    """Em-dash and curly quote must not truncate step text."""
    plan = parse_plan(_REAL_PLAN)
    steps = plan.phases[0].steps
    assert "api_url, api_user, api_password" in steps[0].text
    assert steps[0].text.startswith("Extend NavidromeConfig")


def test_real_plan_to_dict_round_trip() -> None:
    plan = parse_plan(_REAL_PLAN)
    d = plan_to_dict(plan)
    assert d["next"] == "P1-S2"  # P1-S1 is done
    assert d["phases"][0]["steps"][0]["done"] is True
    assert d["phases"][0]["steps"][1]["done"] is False
