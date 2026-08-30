"""Contract tests for the library natural-name wire identity (mechanism A).

Covers the deterministic escaped natural task IDs, the URL-encoded library-name
round trip, and rejection of integer library scope across the domain/facade
boundary. These are the P4-S10 additions for
``TASK-library-domain-facades-A``.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.interfaces.api.id_codec import decode_library_name, encode_library_name
from nomarr.services.domain.library_svc.task_ids import library_task_id

# A spread of names exercising every URL reserved character class the contract
# calls out: spaces, slashes, Unicode, percent signs, and reserved characters.
ROUND_TRIP_NAMES = [
    "Test Library",  # space
    "Rock/Acoustic & Chill",  # slash, space, ampersand
    "École de Musique — Grands Succès",  # Unicode accented + em dash
    "100% Pure Rock",  # literal percent sign
    "a+b=c?d#e",  # reserved + = ? #
    "Loop & Remix (Deluxe) [2005]",  # parens, brackets, ampersand
    "Mixmaster's :D",  # apostrophe, colon
]


def _make_library(name: str) -> Library:
    return Library(name=name, root_path="/music")


class TestEncodeDecodeLibraryName:
    """URL-encoded natural names must round-trip through encode/decode."""

    @pytest.mark.parametrize("name", ROUND_TRIP_NAMES)
    def test_round_trip_preserves_name(self, name: str) -> None:
        """decode(encode(name)) == name for every reserved/Unicode class."""
        encoded = encode_library_name(name)
        assert decode_library_name(encoded) == name

    @pytest.mark.parametrize("name", ROUND_TRIP_NAMES)
    def test_encode_escapes_no_safe_characters(self, name: str) -> None:
        """Reserved characters must never survive encoding as raw bytes."""
        encoded = encode_library_name(name)
        for reserved in (" ", "/", "&", "+", "=", "?", "#", ":", "'", "(", ")", "[", "]", ","):
            assert reserved not in encoded

    @pytest.mark.parametrize("name", ROUND_TRIP_NAMES)
    def test_every_percent_is_a_valid_escape(self, name: str) -> None:
        """Percent signs in the encoded form are only ever valid %XX escapes."""
        encoded = encode_library_name(name)
        idx = 0
        while idx < len(encoded):
            if encoded[idx] == "%":
                assert idx + 2 < len(encoded)
                assert all(c in "0123456789abcdefABCDEF" for c in encoded[idx + 1 : idx + 3])
                idx += 3
            else:
                idx += 1

    def test_encode_known_value(self) -> None:
        """Encoding a known name produces the canonical UTF-8 quoted form."""
        assert encode_library_name("Rock/Acoustic & Chill") == "Rock%2FAcoustic%20%26%20Chill"

    def test_decode_known_value(self) -> None:
        """Decoding a known quoted value returns the original name."""
        assert decode_library_name("Rock%2FAcoustic%20%26%20Chill") == "Rock/Acoustic & Chill"

    def test_encode_unicode_is_utf8_quoted(self) -> None:
        """Unicode names encode as their UTF-8 percent-escaped bytes."""
        assert encode_library_name("École") == "%C3%89cole"

    def test_encode_percent_is_doubly_escaped(self) -> None:
        """A literal percent sign encodes to %25 so it round-trips exactly."""
        assert encode_library_name("100% Pure") == "100%25%20Pure"
        assert decode_library_name("100%25%20Pure") == "100% Pure"

    def test_rejects_integer_scope(self) -> None:
        """The codec must not accept a non-string library identifier."""
        with pytest.raises(TypeError):
            encode_library_name(1)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            decode_library_name(123)  # type: ignore[arg-type]


class TestLibraryTaskId:
    """Deterministic escaped natural task IDs (start/cancel/status/workflow)."""

    def test_known_task_id_format(self) -> None:
        """The task id is ``library-<op>-<escaped-name>`` with no safe chars."""
        assert (
            library_task_id(_make_library("Rock/Acoustic & Chill"), "scan")
            == "library-scan-Rock%2FAcoustic%20%26%20Chill"
        )

    def test_same_library_and_operation_produce_same_key(self) -> None:
        """start/cancel/status/workflow resolve the identical key."""
        lib = _make_library("Rock/Acoustic & Chill")
        assert library_task_id(lib, "scan") == library_task_id(lib, "scan")

    def test_equal_library_values_produce_equal_keys(self) -> None:
        """Two equal Library values (frozen dataclass) yield the same key."""
        a = _make_library("Rock Library")
        b = _make_library("Rock Library")
        assert library_task_id(a, "scan") == library_task_id(b, "scan")

    def test_different_operations_produce_different_keys(self) -> None:
        """Different operations prefix different keys."""
        lib = _make_library("Rock Library")
        assert library_task_id(lib, "scan") != library_task_id(lib, "write_tags")

    def test_escaped_name_is_deterministic_across_operations(self) -> None:
        """The escaped name segment is identical across all operation keys."""
        lib = _make_library("École de Musique")
        escaped = encode_library_name(lib.name)
        assert library_task_id(lib, "scan") == f"library-scan-{escaped}"
        assert library_task_id(lib, "write_tags") == f"library-write_tags-{escaped}"

    def test_rejects_integer_library_scope(self) -> None:
        """An integer library id must be rejected as task scope (no .name)."""
        with pytest.raises(AttributeError):
            library_task_id(1, "scan")  # type: ignore[arg-type]


class TestLibraryNaturalIdentityContract:
    """The frozen/slotted Library value must expose natural identity only."""

    def test_library_has_no_storage_primary_key_attribute(self) -> None:
        """The domain Library exposes no generated-ID storage attributes."""
        lib = _make_library("Rock Library")
        assert not hasattr(lib, "id")
        assert not hasattr(lib, "_id")
        assert not hasattr(lib, "_key")
        assert not hasattr(lib, "_rev")

    def test_library_is_frozen_and_slotted(self) -> None:
        """Natural identity is immutable and slot-based (no __dict__)."""
        lib = _make_library("Rock Library")
        with pytest.raises(AttributeError):
            lib.name = "Renamed"  # type: ignore[misc]  # frozen: intentional
        assert not hasattr(lib, "__dict__")  # slotted
