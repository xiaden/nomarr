"""Unit tests for filter_engine_wf module.

Tests filter execution with nested rule groups:
- Set operations (intersection for AND, union for OR) produce correct results
- Nested group execution works recursively
"""

from unittest.mock import patch

import pytest

from nomarr.helpers.dto.navidrome_dto import RuleGroup, TagCondition
from nomarr.workflows.navidrome.filter_engine_wf import _execute_rule_group


class TestFilterExecutionWithNestedGroups:
    """P1-S5: Test filter execution with nested groups."""

    @pytest.mark.unit
    def test_and_logic_intersection(self) -> None:
        """AND logic should produce set intersection."""
        # Condition A matches files 1, 2, 3
        # Condition B matches files 2, 3, 4
        # AND should produce {2, 3}
        condition_a = TagCondition(tag_key="nom:mood", operator=">", value=0.5)
        condition_b = TagCondition(tag_key="nom:energy", operator=">", value=0.5)
        group = RuleGroup(logic="AND", conditions=[condition_a, condition_b], groups=[])

        # Mock _execute_single_condition to return predetermined sets
        def mock_condition(db, cond):
            if cond.tag_key == "nom:mood":
                return {"file1", "file2", "file3"}
            if cond.tag_key == "nom:energy":
                return {"file2", "file3", "file4"}
            return set()

        with patch(
            "nomarr.workflows.navidrome.filter_engine_wf._execute_single_condition",
            side_effect=mock_condition,
        ):
            result = _execute_rule_group(None, group)  # type: ignore[arg-type]

        assert result == {"file2", "file3"}

    @pytest.mark.unit
    def test_or_logic_union(self) -> None:
        """OR logic should produce set union."""
        # Condition A matches {1, 2}
        # Condition B matches {3, 4}
        # OR should produce {1, 2, 3, 4}
        condition_a = TagCondition(tag_key="nom:mood", operator=">", value=0.5)
        condition_b = TagCondition(tag_key="nom:energy", operator=">", value=0.5)
        group = RuleGroup(logic="OR", conditions=[condition_a, condition_b], groups=[])

        def mock_condition(db, cond):
            if cond.tag_key == "nom:mood":
                return {"file1", "file2"}
            if cond.tag_key == "nom:energy":
                return {"file3", "file4"}
            return set()

        with patch(
            "nomarr.workflows.navidrome.filter_engine_wf._execute_single_condition",
            side_effect=mock_condition,
        ):
            result = _execute_rule_group(None, group)  # type: ignore[arg-type]

        assert result == {"file1", "file2", "file3", "file4"}

    @pytest.mark.unit
    def test_nested_groups_and_or(self) -> None:
        """Nested (A AND B) OR C should compute correctly."""
        # (mood > 0.5 AND energy > 0.5) OR calm > 0.5
        # mood matches {1, 2, 3}, energy matches {2, 3, 4}
        # AND produces {2, 3}
        # calm matches {5, 6}
        # OR of {2, 3} and {5, 6} produces {2, 3, 5, 6}

        inner_group = RuleGroup(
            logic="AND",
            conditions=[
                TagCondition(tag_key="nom:mood", operator=">", value=0.5),
                TagCondition(tag_key="nom:energy", operator=">", value=0.5),
            ],
            groups=[],
        )
        outer_group = RuleGroup(
            logic="OR",
            conditions=[TagCondition(tag_key="nom:calm", operator=">", value=0.5)],
            groups=[inner_group],
        )

        def mock_condition(db, cond):
            if cond.tag_key == "nom:mood":
                return {"file1", "file2", "file3"}
            if cond.tag_key == "nom:energy":
                return {"file2", "file3", "file4"}
            if cond.tag_key == "nom:calm":
                return {"file5", "file6"}
            return set()

        with patch(
            "nomarr.workflows.navidrome.filter_engine_wf._execute_single_condition",
            side_effect=mock_condition,
        ):
            result = _execute_rule_group(None, outer_group)  # type: ignore[arg-type]

        # (mood intersect energy) union calm = {2,3} union {5,6} = {2,3,5,6}
        assert result == {"file2", "file3", "file5", "file6"}

    @pytest.mark.unit
    def test_nested_groups_or_and(self) -> None:
        """Nested (A OR B) AND C should compute correctly."""
        # (mood > 0.5 OR energy > 0.5) AND calm > 0.5
        # mood matches {1, 2}, energy matches {3, 4}
        # OR produces {1, 2, 3, 4}
        # calm matches {2, 4, 6}
        # AND of {1,2,3,4} and {2,4,6} produces {2, 4}

        inner_group = RuleGroup(
            logic="OR",
            conditions=[
                TagCondition(tag_key="nom:mood", operator=">", value=0.5),
                TagCondition(tag_key="nom:energy", operator=">", value=0.5),
            ],
            groups=[],
        )
        outer_group = RuleGroup(
            logic="AND",
            conditions=[TagCondition(tag_key="nom:calm", operator=">", value=0.5)],
            groups=[inner_group],
        )

        def mock_condition(db, cond):
            if cond.tag_key == "nom:mood":
                return {"file1", "file2"}
            if cond.tag_key == "nom:energy":
                return {"file3", "file4"}
            if cond.tag_key == "nom:calm":
                return {"file2", "file4", "file6"}
            return set()

        with patch(
            "nomarr.workflows.navidrome.filter_engine_wf._execute_single_condition",
            side_effect=mock_condition,
        ):
            result = _execute_rule_group(None, outer_group)  # type: ignore[arg-type]

        # (mood union energy) intersect calm = {1,2,3,4} intersect {2,4,6} = {2, 4}
        assert result == {"file2", "file4"}

    @pytest.mark.unit
    def test_deeply_nested_three_levels(self) -> None:
        """Three levels of nesting should compute correctly."""
        # ((A AND B) OR C) AND D
        # A={1,2,3}, B={2,3,4} -> A AND B = {2,3}
        # C={5,6} -> (A AND B) OR C = {2,3,5,6}
        # D={2,5,7} -> result AND D = {2,5}

        inner_most = RuleGroup(
            logic="AND",
            conditions=[
                TagCondition(tag_key="nom:a", operator=">", value=0.5),
                TagCondition(tag_key="nom:b", operator=">", value=0.5),
            ],
            groups=[],
        )
        middle = RuleGroup(
            logic="OR",
            conditions=[TagCondition(tag_key="nom:c", operator=">", value=0.5)],
            groups=[inner_most],
        )
        outer = RuleGroup(
            logic="AND",
            conditions=[TagCondition(tag_key="nom:d", operator=">", value=0.5)],
            groups=[middle],
        )

        def mock_condition(db, cond):
            if cond.tag_key == "nom:a":
                return {"file1", "file2", "file3"}
            if cond.tag_key == "nom:b":
                return {"file2", "file3", "file4"}
            if cond.tag_key == "nom:c":
                return {"file5", "file6"}
            if cond.tag_key == "nom:d":
                return {"file2", "file5", "file7"}
            return set()

        with patch(
            "nomarr.workflows.navidrome.filter_engine_wf._execute_single_condition",
            side_effect=mock_condition,
        ):
            result = _execute_rule_group(None, outer)  # type: ignore[arg-type]

        # ((A intersect B) union C) intersect D = ({2,3} union {5,6}) intersect {2,5,7} = {2,3,5,6} intersect {2,5,7} = {2,5}
        assert result == {"file2", "file5"}

    @pytest.mark.unit
    def test_empty_group_returns_empty_set(self) -> None:
        """Empty group (no conditions or subgroups) should return empty set."""
        group = RuleGroup(logic="AND", conditions=[], groups=[])
        result = _execute_rule_group(None, group)  # type: ignore[arg-type]
        assert result == set()

    @pytest.mark.unit
    def test_multiple_sibling_groups(self) -> None:
        """Multiple sibling groups at same level should combine correctly."""
        # (A AND B) OR (C AND D)
        # A={1,2}, B={2,3} -> AND={2}
        # C={4,5}, D={5,6} -> AND={5}
        # OR of {2} and {5} = {2,5}

        group1 = RuleGroup(
            logic="AND",
            conditions=[
                TagCondition(tag_key="nom:a", operator=">", value=0.5),
                TagCondition(tag_key="nom:b", operator=">", value=0.5),
            ],
            groups=[],
        )
        group2 = RuleGroup(
            logic="AND",
            conditions=[
                TagCondition(tag_key="nom:c", operator=">", value=0.5),
                TagCondition(tag_key="nom:d", operator=">", value=0.5),
            ],
            groups=[],
        )
        outer = RuleGroup(logic="OR", conditions=[], groups=[group1, group2])

        def mock_condition(db, cond):
            if cond.tag_key == "nom:a":
                return {"file1", "file2"}
            if cond.tag_key == "nom:b":
                return {"file2", "file3"}
            if cond.tag_key == "nom:c":
                return {"file4", "file5"}
            if cond.tag_key == "nom:d":
                return {"file5", "file6"}
            return set()

        with patch(
            "nomarr.workflows.navidrome.filter_engine_wf._execute_single_condition",
            side_effect=mock_condition,
        ):
            result = _execute_rule_group(None, outer)  # type: ignore[arg-type]

        assert result == {"file2", "file5"}
