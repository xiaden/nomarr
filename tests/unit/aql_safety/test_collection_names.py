"""Tests for static AQL collection name validation."""

from __future__ import annotations

import ast

import pytest

from .conftest import (
    _INTERPOLATION_PLACEHOLDER,
    _PERSISTENCE_DATABASE_ROOT,
    _RE_DYNAMIC_COLLECTION,
    _REPO_ROOT,
    _VALID_COLLECTIONS,
    _extract_bind_var_collection_names,
    _extract_collection_references,
    _extract_module_string_constants,
    _find_bind_var_aql_calls,
    _format_collection_name_violations,
    _scan_all_aql_strings,
)


class TestExtractCollectionReferences:
    """Unit tests for the _extract_collection_references helper."""

    @pytest.mark.unit
    def test_for_loop_returns_collection_not_loop_var(self) -> None:
        """FOR loop extraction includes the iterated collection and excludes the loop variable."""
        result = _extract_collection_references("FOR doc IN my_coll RETURN doc")
        assert result == ["my_coll"]

    @pytest.mark.unit
    def test_insert_into_returns_target_collection(self) -> None:
        """INSERT INTO returns the target collection name."""
        result = _extract_collection_references("INSERT {_key: 'x'} INTO tags")
        assert result == ["tags"]

    @pytest.mark.unit
    def test_bind_var_prefixed_collection_excluded(self) -> None:
        """Bind-var-prefixed (@@) collection references are not included."""
        result = _extract_collection_references("FOR d IN @@coll RETURN d")
        assert result == []

    @pytest.mark.unit
    def test_traversal_edge_collection_included(self) -> None:
        """OUTBOUND traversal edge collection name is extracted."""
        result = _extract_collection_references("FOR v, e IN OUTBOUND @start song_has_tags RETURN v")
        assert "song_has_tags" in result

    @pytest.mark.unit
    def test_interpolation_placeholder_excluded(self) -> None:
        """The f-string interpolation placeholder is not treated as a collection name."""
        result = _extract_collection_references(f"FOR d IN {_INTERPOLATION_PLACEHOLDER} RETURN d")
        assert result == []

    @pytest.mark.unit
    def test_line_comment_collection_not_extracted(self) -> None:
        """Collection names inside AQL line comments are ignored."""
        result = _extract_collection_references("// FOR d IN fake_coll\nRETURN 1")
        assert "fake_coll" not in result


class TestExtractBindVarCollectionNames:
    """Unit tests for the _extract_bind_var_collection_names helper."""

    @pytest.mark.unit
    def test_at_prefixed_key_extracts_collection(self) -> None:
        """@-prefixed key resolves the collection name from a string literal."""
        node = ast.parse('{"@collection": "tags"}', mode="eval").body
        assert _extract_bind_var_collection_names(node, {}) == ["tags"]

    @pytest.mark.unit
    def test_non_at_prefixed_key_is_skipped(self) -> None:
        """Key without @ prefix is not treated as a collection bind var."""
        node = ast.parse('{"collection": "tags"}', mode="eval").body
        assert _extract_bind_var_collection_names(node, {}) == []

    @pytest.mark.unit
    def test_none_input_returns_empty(self) -> None:
        """None input returns an empty list."""
        assert _extract_bind_var_collection_names(None, {}) == []

    @pytest.mark.unit
    def test_non_dict_returns_empty(self) -> None:
        """Non-dict AST node returns an empty list."""
        assert _extract_bind_var_collection_names(ast.Constant(value="x"), {}) == []

    @pytest.mark.unit
    def test_module_constant_resolution(self) -> None:
        """Collection name referenced through a module constant is resolved."""
        node = ast.parse('{"@collection": TAGS_COLL}', mode="eval").body
        assert _extract_bind_var_collection_names(node, {"TAGS_COLL": "tags"}) == ["tags"]


@pytest.mark.unit
def test_aql_collection_names_are_valid() -> None:
    """Persistence AQL should reference only whitelisted collection names."""
    violations: list[tuple[str, int, str]] = []

    for file_path, line_number, aql in _scan_all_aql_strings(_PERSISTENCE_DATABASE_ROOT):
        for collection_name in _extract_collection_references(aql):
            normalized_name = collection_name.lower()
            if _RE_DYNAMIC_COLLECTION.match(normalized_name):
                continue
            if normalized_name not in _VALID_COLLECTIONS:
                violations.append((file_path, line_number, collection_name))

    for persistence_file_path in sorted(_PERSISTENCE_DATABASE_ROOT.rglob("*.py")):
        module = ast.parse(
            persistence_file_path.read_text(encoding="utf-8"),
            filename=str(persistence_file_path),
        )
        module_constants = _extract_module_string_constants(module)
        for display_path, line_number, bind_vars_node in _find_bind_var_aql_calls(
            file_path=persistence_file_path,
            repo_root=_REPO_ROOT,
        ):
            for collection_name in _extract_bind_var_collection_names(
                bind_vars_node,
                module_constants,
            ):
                normalized_name = collection_name.lower()
                if _RE_DYNAMIC_COLLECTION.match(normalized_name):
                    continue
                if normalized_name not in _VALID_COLLECTIONS:
                    violations.append((display_path, line_number, collection_name))

    if violations:
        pytest.fail(_format_collection_name_violations(sorted(violations)))
