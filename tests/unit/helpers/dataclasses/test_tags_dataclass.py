"""Unit tests for the canonical strict Tag/Tags value objects.

The canonical implementation lives in ``nomarr.helpers.dataclasses.tags_dataclass``
and is re-exported unchanged by ``nomarr.helpers.dto.tags_dto``. All tests import
from the canonical module.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags


class TestTagConstruction:
    """Tests for the strict ``Tag`` value object invariants."""

    @pytest.mark.unit
    def test_accepts_valid_name_and_values(self) -> None:
        tag = Tag(name="genre", values=("rock",))
        assert tag.name == "genre"
        assert tag.values == ("rock",)

    @pytest.mark.unit
    def test_normalizes_list_values_to_tuple(self) -> None:
        tag = Tag(name="genre", values=["rock", "pop"])
        assert tag.values == ("rock", "pop")
        assert isinstance(tag.values, tuple)

    @pytest.mark.unit
    def test_empty_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Tag(name="", values=("rock",))

    @pytest.mark.unit
    def test_blank_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="blank"):
            Tag(name="   ", values=("rock",))

    @pytest.mark.unit
    def test_none_values_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="non-scalar"):
            Tag(name="genre", values=None)

    @pytest.mark.unit
    def test_scalar_string_values_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="non-scalar"):
            Tag(name="genre", values="rock")

    @pytest.mark.unit
    def test_scalar_int_values_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="non-scalar"):
            Tag(name="genre", values=42)

    @pytest.mark.unit
    def test_empty_values_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            Tag(name="genre", values=())

    @pytest.mark.unit
    def test_non_tag_value_element_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="Invalid TagValue type: object"):
            Tag(name="genre", values=(object(),))

    @pytest.mark.unit
    def test_none_element_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="Invalid TagValue type: NoneType"):
            Tag(name="genre", values=(None,))


class TestTagsConstruction:
    """Tests for the strict ``Tags`` collection invariants and canonicalization."""

    @pytest.mark.unit
    def test_empty_items_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one tag"):
            Tags(items=())

    @pytest.mark.unit
    def test_rejects_non_tag_items(self) -> None:
        with pytest.raises(TypeError, match="must contain Tag objects"):
            Tags(items=("not-a-tag",))

    @pytest.mark.unit
    def test_sorts_by_name_casefold_then_name(self) -> None:
        tags = Tags(
            items=(
                Tag(name="Zebra", values=("a",)),
                Tag(name="apple", values=("b",)),
                Tag(name="Apple", values=("c",)),
            )
        )
        assert [tag.name for tag in tags.items] == ["Apple", "apple", "Zebra"]

    @pytest.mark.unit
    def test_merges_duplicate_names(self) -> None:
        tags = Tags(
            items=(
                Tag(name="genre", values=("rock",)),
                Tag(name="genre", values=("pop",)),
                Tag(name="artist", values=("x",)),
            )
        )
        assert tags.to_dict() == {
            "artist": ("x",),
            "genre": ("rock", "pop"),
        }

    @pytest.mark.unit
    def test_dedupes_values_per_name(self) -> None:
        tags = Tags(
            items=(
                Tag(name="genre", values=("rock", "rock", "pop")),
                Tag(name="genre", values=("rock",)),
            )
        )
        assert tags.get_values("genre") == ("rock", "pop")

    @pytest.mark.unit
    def test_type_aware_dedupe_keeps_true_1_and_1_0_distinct(self) -> None:
        tags = Tags(items=(Tag(name="t", values=(True, 1, 1.0)),))
        assert tags.get_values("t") == (True, 1, 1.0)

    @pytest.mark.unit
    def test_type_aware_dedupe_across_duplicate_names(self) -> None:
        tags = Tags(
            items=(
                Tag(name="t", values=(True,)),
                Tag(name="t", values=(1,)),
            )
        )
        assert tags.get_values("t") == (True, 1)


class TestTagsMethods:
    """Tests for ``Tags`` lookup and conversion methods."""

    @pytest.mark.unit
    def test_has_name_returns_true_when_present(self) -> None:
        tags = Tags(items=(Tag(name="genre", values=("rock",)),))
        assert tags.has_name("genre") is True

    @pytest.mark.unit
    def test_has_name_returns_false_when_missing(self) -> None:
        tags = Tags(items=(Tag(name="genre", values=("rock",)),))
        assert tags.has_name("artist") is False

    @pytest.mark.unit
    def test_get_values_returns_tuple_on_hit(self) -> None:
        tags = Tags(items=(Tag(name="genre", values=("rock", "pop")),))
        assert tags.get_values("genre") == ("rock", "pop")

    @pytest.mark.unit
    def test_get_values_raises_key_error_on_miss(self) -> None:
        tags = Tags(items=(Tag(name="genre", values=("rock",)),))
        with pytest.raises(KeyError, match="artist"):
            tags.get_values("artist")

    @pytest.mark.unit
    def test_len_iter_getitem(self) -> None:
        tags = Tags(
            items=(
                Tag(name="genre", values=("rock",)),
                Tag(name="artist", values=("x",)),
            )
        )
        assert len(tags) == 2
        assert [tag.name for tag in tags] == ["artist", "genre"]
        assert tags[0].name == "artist"
        assert tags[1].name == "genre"

    @pytest.mark.unit
    def test_to_dict_returns_name_to_values_mapping(self) -> None:
        tags = Tags(items=(Tag(name="genre", values=("rock", "pop")),))
        assert tags.to_dict() == {"genre": ("rock", "pop")}

    @pytest.mark.unit
    def test_from_dict_normalizes_scalar_to_tuple(self) -> None:
        tags = Tags.from_dict({"genre": "rock"})
        assert tags.to_dict() == {"genre": ("rock",)}

    @pytest.mark.unit
    def test_from_dict_accepts_list_and_tuple_values(self) -> None:
        tags = Tags.from_dict({"genre": ["rock", "pop"], "artist": ("x",)})
        assert tags.to_dict() == {"artist": ("x",), "genre": ("rock", "pop")}

    @pytest.mark.unit
    def test_from_dict_empty_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one tag"):
            Tags.from_dict({})

    @pytest.mark.unit
    def test_from_dict_rejects_non_tag_value_element(self) -> None:
        with pytest.raises(TypeError, match="Invalid TagValue type: object"):
            Tags.from_dict({"genre": (object(),)})

    @pytest.mark.unit
    def test_from_dict_rejects_none_element(self) -> None:
        with pytest.raises(TypeError, match="Invalid TagValue type: NoneType"):
            Tags.from_dict({"genre": (None,)})

    @pytest.mark.unit
    def test_from_db_rows_groups_rows_by_name(self) -> None:
        tags = Tags.from_db_rows(
            [
                {"name": "genre", "value": "rock"},
                {"name": "genre", "value": "pop"},
                {"name": "artist", "value": "x"},
            ]
        )
        assert tags.to_dict() == {"artist": ("x",), "genre": ("rock", "pop")}

    @pytest.mark.unit
    def test_from_db_rows_preserves_value_order(self) -> None:
        tags = Tags.from_db_rows(
            [
                {"name": "genre", "value": "pop"},
                {"name": "genre", "value": "rock"},
            ]
        )
        assert tags.get_values("genre") == ("pop", "rock")

    @pytest.mark.unit
    def test_from_db_rows_empty_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one tag"):
            Tags.from_db_rows([])
