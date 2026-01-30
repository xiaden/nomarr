"""Unit tests for arango_client JSON serialization boundary.

Tests the _jsonify_for_arango function which ensures all data passed to
ArangoDB is JSON-serializable, unwrapping wrapper types like Milliseconds.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from nomarr.persistence.arango_client import _jsonify_for_arango

# =============================================================================
# Test Fixtures - Mock wrapper types
# =============================================================================


@dataclass(frozen=True)
class MockMilliseconds:
    """Mock of Milliseconds wrapper type."""

    value: int


@dataclass(frozen=True)
class MockSeconds:
    """Mock of Seconds wrapper type."""

    value: int


@dataclass(frozen=True)
class BadWrapper:
    """Wrapper whose .value is not a JSON primitive."""

    value: list  # list is not a primitive


@dataclass(frozen=True)
class ComplexDTO:
    """Complex DTO without .value - should NOT be auto-converted."""

    relative: str
    absolute: Path
    library_id: str


class ArbitraryObject:
    """Plain object with no .value - should be rejected."""

    def __init__(self, x: int) -> None:
        self.x = x


# =============================================================================
# Tests: Primitives pass through
# =============================================================================


class TestPrimitives:
    """Test that JSON primitives pass through unchanged."""

    def test_string_passthrough(self) -> None:
        assert _jsonify_for_arango("hello") == "hello"

    def test_int_passthrough(self) -> None:
        assert _jsonify_for_arango(42) == 42

    def test_float_passthrough(self) -> None:
        assert _jsonify_for_arango(3.14) == 3.14

    def test_bool_passthrough(self) -> None:
        assert _jsonify_for_arango(True) is True
        assert _jsonify_for_arango(False) is False

    def test_none_passthrough(self) -> None:
        assert _jsonify_for_arango(None) is None


# =============================================================================
# Tests: Containers recurse correctly
# =============================================================================


class TestContainers:
    """Test that containers are recursed properly."""

    def test_empty_dict(self) -> None:
        assert _jsonify_for_arango({}) == {}

    def test_empty_list(self) -> None:
        assert _jsonify_for_arango([]) == []

    def test_nested_dict(self) -> None:
        result = _jsonify_for_arango({"a": {"b": {"c": 1}}})
        assert result == {"a": {"b": {"c": 1}}}

    def test_nested_list(self) -> None:
        result = _jsonify_for_arango([[[1, 2], [3, 4]], [[5, 6]]])
        assert result == [[[1, 2], [3, 4]], [[5, 6]]]

    def test_mixed_containers(self) -> None:
        result = _jsonify_for_arango({"items": [{"name": "a"}, {"name": "b"}]})
        assert result == {"items": [{"name": "a"}, {"name": "b"}]}

    def test_tuple_converted_to_list(self) -> None:
        result = _jsonify_for_arango((1, 2, 3))
        assert result == [1, 2, 3]


# =============================================================================
# Tests: Wrapper types with .value unwrap correctly
# =============================================================================


class TestWrapperUnwrap:
    """Test that wrapper types with .value are unwrapped."""

    def test_milliseconds_unwraps(self) -> None:
        ms = MockMilliseconds(value=1705881600000)
        assert _jsonify_for_arango(ms) == 1705881600000

    def test_seconds_unwraps(self) -> None:
        s = MockSeconds(value=1705881600)
        assert _jsonify_for_arango(s) == 1705881600

    def test_nested_milliseconds_in_dict(self) -> None:
        data = {"scanned_at": MockMilliseconds(12345), "name": "test"}
        result = _jsonify_for_arango(data)
        assert result == {"scanned_at": 12345, "name": "test"}

    def test_nested_milliseconds_in_list(self) -> None:
        data = [MockMilliseconds(100), MockMilliseconds(200)]
        result = _jsonify_for_arango(data)
        assert result == [100, 200]

    def test_deeply_nested_wrapper(self) -> None:
        data = {
            "docs": [
                {"path": "/a", "ts": MockMilliseconds(111)},
                {"path": "/b", "ts": MockMilliseconds(222)},
            ],
        }
        result = _jsonify_for_arango(data)
        assert result == {
            "docs": [
                {"path": "/a", "ts": 111},
                {"path": "/b", "ts": 222},
            ],
        }


# =============================================================================
# Tests: Non-primitive .value raises clearly
# =============================================================================


class TestBadValueRaises:
    """Test that .value which is not a primitive raises TypeError."""

    def test_list_value_raises(self) -> None:
        bad = BadWrapper(value=[1, 2, 3])
        with pytest.raises(TypeError) as exc_info:
            _jsonify_for_arango(bad)
        assert "Non-primitive .value" in str(exc_info.value)
        assert "BadWrapper" in str(exc_info.value)
        assert "list" in str(exc_info.value)

    def test_nested_bad_value_shows_path(self) -> None:
        data = {"outer": {"inner": BadWrapper(value=[1])}}
        with pytest.raises(TypeError) as exc_info:
            _jsonify_for_arango(data)
        assert "$.outer.inner" in str(exc_info.value)


# =============================================================================
# Tests: Unknown objects raise with path
# =============================================================================


class TestUnknownObjectRaises:
    """Test that unknown objects raise TypeError with path context."""

    def test_arbitrary_object_raises(self) -> None:
        obj = ArbitraryObject(x=42)
        with pytest.raises(TypeError) as exc_info:
            _jsonify_for_arango(obj)
        assert "ArbitraryObject" in str(exc_info.value)
        assert "not JSON-serializable" in str(exc_info.value)

    def test_complex_dto_raises(self) -> None:
        """Complex DTOs should NOT be auto-converted to dict."""
        dto = ComplexDTO(relative="music/song.mp3", absolute=Path("/lib/music/song.mp3"), library_id="lib123")
        with pytest.raises(TypeError) as exc_info:
            _jsonify_for_arango(dto)
        assert "ComplexDTO" in str(exc_info.value)

    def test_path_object_raises(self) -> None:
        """pathlib.Path should not be auto-converted."""
        with pytest.raises(TypeError) as exc_info:
            _jsonify_for_arango(Path("/some/path"))
        assert "Path" in str(exc_info.value)

    def test_nested_unknown_shows_path(self) -> None:
        data = {"files": [{"path": "/a"}, {"path": ArbitraryObject(1)}]}
        with pytest.raises(TypeError) as exc_info:
            _jsonify_for_arango(data)
        assert "$.files[1].path" in str(exc_info.value)

    def test_list_index_in_path(self) -> None:
        data = [1, 2, ArbitraryObject(3)]
        with pytest.raises(TypeError) as exc_info:
            _jsonify_for_arango(data)
        assert "$[2]" in str(exc_info.value)


# =============================================================================
# Tests: Real wrapper types from codebase
# =============================================================================


class TestRealWrapperTypes:
    """Test with actual wrapper types from nomarr.helpers.time_helper."""

    def test_real_milliseconds(self) -> None:
        from nomarr.helpers.time_helper import Milliseconds

        ms = Milliseconds(value=1705881600000)
        assert _jsonify_for_arango(ms) == 1705881600000

    def test_real_seconds(self) -> None:
        from nomarr.helpers.time_helper import Seconds

        s = Seconds(value=1705881600)
        assert _jsonify_for_arango(s) == 1705881600

    def test_real_internal_milliseconds(self) -> None:
        from nomarr.helpers.time_helper import InternalMilliseconds

        ms = InternalMilliseconds(value=123456)
        assert _jsonify_for_arango(ms) == 123456

    def test_real_internal_seconds(self) -> None:
        from nomarr.helpers.time_helper import InternalSeconds

        s = InternalSeconds(value=1234)
        assert _jsonify_for_arango(s) == 1234

    def test_now_ms_result(self) -> None:
        from nomarr.helpers.time_helper import now_ms

        ms = now_ms()
        result = _jsonify_for_arango(ms)
        assert isinstance(result, int)
        assert result > 0

    def test_library_path_rejected(self) -> None:
        """LibraryPath is a complex DTO and should NOT be auto-converted."""
        from nomarr.helpers.dto import LibraryPath

        lp = LibraryPath(
            relative="music/song.mp3",
            absolute=Path("/lib/music/song.mp3"),
            library_id="libraries/123",
            status="valid",
        )
        with pytest.raises(TypeError) as exc_info:
            _jsonify_for_arango(lp)
        assert "LibraryPath" in str(exc_info.value)
