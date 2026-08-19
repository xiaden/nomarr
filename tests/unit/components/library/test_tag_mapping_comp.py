"""Tests for the library-layer row-to-FileTag mapper.

Pins the CONTRACTS.md library ownership rule: ``tag_mapping_comp`` is the single
row-to-``FileTag`` projection, defining key/value, numeric-vs-string type
classification, and Nomarr-namespace classification in one place.
"""

from __future__ import annotations

import pytest

from nomarr.components.library.tag_mapping_comp import file_tag_from_tag_row, is_numeric_tag_value
from nomarr.helpers.dto.library_dto import FileTag


class TestFileTagFromTagRow:
    def test_string_value_maps_to_string(self) -> None:
        tag = file_tag_from_tag_row({"name": "mood", "value": "happy"})
        assert isinstance(tag, FileTag)
        assert tag.key == "mood"
        assert tag.value == "happy"
        assert tag.tag_type == "string"
        assert tag.is_nomarr is False

    def test_numeric_value_maps_to_float(self) -> None:
        tag = file_tag_from_tag_row({"name": "tempo", "value": 120})
        assert tag.value == "120"
        assert tag.tag_type == "float"
        assert tag.is_nomarr is False

    def test_float_value_maps_to_float(self) -> None:
        tag = file_tag_from_tag_row({"name": "bpm", "value": 98.5})
        assert tag.tag_type == "float"

    def test_boolean_value_maps_to_string(self) -> None:
        tag = file_tag_from_tag_row({"name": "explicit", "value": True})
        assert tag.value == "True"
        assert tag.tag_type == "string"

    def test_nomarr_namespace_marks_is_nomarr(self) -> None:
        tag = file_tag_from_tag_row({"name": "nom:mood", "value": "calm", "namespace": "nom"})
        assert tag.is_nomarr is True

    def test_missing_namespace_is_not_nomarr(self) -> None:
        tag = file_tag_from_tag_row({"name": "genre", "value": "rock"})
        assert tag.is_nomarr is False

    def test_missing_value_maps_to_none_string(self) -> None:
        tag = file_tag_from_tag_row({"name": "genre"})
        assert tag.value == "None"
        assert tag.tag_type == "string"

    def test_missing_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="name"):
            file_tag_from_tag_row({"value": "rock"})


class TestIsNumericTagValue:
    def test_int_and_float_are_numeric(self) -> None:
        assert is_numeric_tag_value(120)
        assert is_numeric_tag_value(98.5)

    def test_bool_is_not_numeric(self) -> None:
        assert not is_numeric_tag_value(True)
        assert not is_numeric_tag_value(False)

    def test_str_and_none_are_not_numeric(self) -> None:
        assert not is_numeric_tag_value("rock")
        assert not is_numeric_tag_value(None)
