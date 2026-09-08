"""Unit tests for nomarr/helpers/tag_handle_codec.py — the tag wire-handle codec.

Covers the wire-handle contract (CONTRACTS.md): opaque ``t1.`` + canonical
URL-safe base64url JSON carrying exactly ``name``/``value``/``namespace``;
deterministic, unambiguous, storage-ID-free; exact round-trip of JSON value
types (int/float/str/bool/None); and deterministic rejection of malformed,
non-canonical, ambiguous, and oversized handles.
"""

from __future__ import annotations

import base64
import json

import pytest

from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.tag_handle_codec import TagHandleError, decode_tag_handle, encode_tag_handle

pytestmark = [pytest.mark.unit]

_PREFIX = "t1."


def _canonical_b64(payload: dict) -> str:
    """URL-safe base64 of a canonical JSON serialisation (matches the codec)."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _std_b64(payload: dict) -> str:
    """Standard (non-URL-safe) base64 of a canonical JSON serialisation."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return base64.b64encode(raw).decode("ascii")


def _raw_b64(payload_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(payload_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# Determinism & shape
# ---------------------------------------------------------------------------


class TestDeterminismAndShape:
    def test_encode_is_deterministic(self) -> None:
        identity = TagRef(name="genre", value="rock")
        assert encode_tag_handle(identity) == encode_tag_handle(identity)

    def test_handle_is_versioned_and_url_safe(self) -> None:
        handle = encode_tag_handle(TagRef(name="genre", value="rock"))
        assert handle.startswith(_PREFIX)
        # Only URL-safe base64url characters plus canonical padding.
        body = handle[len(_PREFIX) :]
        assert "+" not in body and "/" not in body
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")
        assert set(body) <= allowed

    def test_handle_contains_no_storage_id(self) -> None:
        # 'id' is never part of the handle payload; the only fields are the
        # semantic name/value/namespace.
        payload = base64.urlsafe_b64decode(
            encode_tag_handle(TagRef(name="genre", value="rock"))[len(_PREFIX) :].encode("ascii")
        )
        decoded = json.loads(payload)
        assert set(decoded) == {"name", "namespace", "value"}

    def test_exception_is_valueerror(self) -> None:
        assert issubclass(TagHandleError, ValueError)


# ---------------------------------------------------------------------------
# Exact round-trip across JSON value types and namespaces
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.parametrize(
        ("identity",),
        [
            (TagRef(name="genre", value="rock"),),
            (TagRef(name="Electronic", value="classical"),),
            (TagRef(name="year", value=120),),
            (TagRef(name="year", value="120"),),  # string '120' stays a string
            (TagRef(name="bpm", value=120.0),),
            (TagRef(name="flag", value=True),),
            (TagRef(name="flag", value=False),),
            (TagRef(name="empty", value=None),),
            (TagRef(name="mood", value="happy", namespace="nom"),),
            (TagRef(name="name", value="café — 東京"),),  # non-ASCII round-trips
        ],
    )
    def test_round_trips_exactly(self, identity: TagRef) -> None:
        decoded = decode_tag_handle(encode_tag_handle(identity))
        assert decoded == identity
        # Value JSON type (not just equality) is preserved: '120' str != 120 int.
        assert type(decoded.value) is type(identity.value)

    def test_string_value_never_parsed_as_int(self) -> None:
        # "120" as a string is data and must not become the integer 120.
        decoded = decode_tag_handle(encode_tag_handle(TagRef(name="year", value="120")))
        assert decoded.value == "120"
        assert isinstance(decoded.value, str)

    def test_int_120_and_string_120_produce_distinct_handles(self) -> None:
        int_handle = encode_tag_handle(TagRef(name="year", value=120))
        str_handle = encode_tag_handle(TagRef(name="year", value="120"))
        assert int_handle != str_handle

    def test_default_and_nom_namespaces_distinct(self) -> None:
        default = encode_tag_handle(TagRef(name="genre", value="rock", namespace="default"))
        nom = encode_tag_handle(TagRef(name="genre", value="rock", namespace="nom"))
        assert default != nom
        assert decode_tag_handle(nom).namespace == "nom"
        assert decode_tag_handle(default).namespace == "default"

    def test_default_namespace_is_literal_default(self) -> None:
        assert encode_tag_handle(TagRef(name="genre", value="rock")).endswith(
            _canonical_b64({"name": "genre", "namespace": "default", "value": "rock"})
        )

    def test_omitted_value_none_round_trips(self) -> None:
        identity = TagRef(name="bpm")  # value defaults to None
        decoded = decode_tag_handle(encode_tag_handle(identity))
        assert decoded.value is None
        assert decoded == identity


# ---------------------------------------------------------------------------
# Rejection: version / structure / fields
# ---------------------------------------------------------------------------


class TestRejectsMalformed:
    def test_rejects_wrong_version(self) -> None:
        handle = "t2." + _canonical_b64({"name": "g", "namespace": "default", "value": "rock"})
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_missing_prefix(self) -> None:
        handle = _canonical_b64({"name": "g", "namespace": "default", "value": "rock"})
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_non_string_handle(self) -> None:
        with pytest.raises(TagHandleError):
            decode_tag_handle(123)  # type: ignore[arg-type]

    def test_rejects_empty_payload(self) -> None:
        with pytest.raises(TagHandleError):
            decode_tag_handle(_PREFIX)

    def test_rejects_non_base64(self) -> None:
        with pytest.raises(TagHandleError):
            decode_tag_handle(_PREFIX + "!!not-base64!!")

    def test_rejects_standard_base64_plus(self) -> None:
        # A URL-unsafe '+' character must be rejected even though it decodes to
        # the same bytes as the canonical '-' alphabet.
        std = _std_b64({"name": "~~~", "namespace": "default", "value": "x"})
        assert "+" in std
        with pytest.raises(TagHandleError):
            decode_tag_handle(_PREFIX + std)

    def test_rejects_invalid_json(self) -> None:
        with pytest.raises(TagHandleError):
            decode_tag_handle(_PREFIX + _raw_b64(b"{not json"))

    def test_rejects_non_object_json(self) -> None:
        with pytest.raises(TagHandleError):
            decode_tag_handle(_PREFIX + _raw_b64(b'["name"]'))

    def test_rejects_extra_field(self) -> None:
        handle = _PREFIX + _canonical_b64({"name": "g", "namespace": "default", "value": "rock", "id": 5})
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_missing_field(self) -> None:
        handle = _PREFIX + _canonical_b64({"name": "g", "value": "rock"})
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_blank_name(self) -> None:
        handle = _PREFIX + _canonical_b64({"name": "   ", "namespace": "default", "value": "rock"})
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_non_string_name(self) -> None:
        handle = _PREFIX + _canonical_b64({"name": 5, "namespace": "default", "value": "rock"})
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_non_string_namespace(self) -> None:
        handle = _PREFIX + _canonical_b64({"name": "g", "namespace": 7, "value": "rock"})
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_blank_namespace_as_non_canonical(self) -> None:
        # '' is normalised to 'default' by TagRef, so it is never canonical.
        handle = _PREFIX + _canonical_b64({"name": "g", "namespace": "", "value": "rock"})
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)


# ---------------------------------------------------------------------------
# Rejection: non-canonical encodings & oversized payloads
# ---------------------------------------------------------------------------


class TestRejectsNonCanonical:
    def test_rejects_reordered_keys(self) -> None:
        raw = json.dumps(
            {"value": "rock", "namespace": "default", "name": "g"},
            separators=(",", ":"),
        ).encode("ascii")
        handle = _PREFIX + _raw_b64(raw)
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_pretty_whitespace(self) -> None:
        raw = json.dumps({"name": "g", "namespace": "default", "value": "rock"}, indent=2).encode("ascii")
        handle = _PREFIX + _raw_b64(raw)
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_non_canonical_number_spelling(self) -> None:
        # A float spelled '1e2' is valid JSON but not the codec's canonical
        # (shortest-repr) form '100.0', so it must be rejected as ambiguous.
        handle = _PREFIX + _raw_b64(b'{"name":"g","namespace":"default","value":1e2}')
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_rejects_unpadded_base64(self) -> None:
        canonical = _canonical_b64({"name": "g", "namespace": "default", "value": "rock"})
        with pytest.raises(TagHandleError):
            decode_tag_handle(_PREFIX + canonical.rstrip("="))

    def test_accepts_float_round_trip(self) -> None:
        # The canonical spelling of float 100.0 IS '100.0' and round-trips.
        identity = TagRef(name="bpm", value=100.0)
        assert decode_tag_handle(encode_tag_handle(identity)).value == 100.0


class TestRejectsOversized:
    def test_encode_rejects_oversized_value(self) -> None:
        with pytest.raises(TagHandleError):
            encode_tag_handle(TagRef(name="x", value="y" * 5000))

    def test_decode_rejects_oversized_payload(self) -> None:
        raw = json.dumps(
            {"name": "x", "namespace": "default", "value": "y" * 3000},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        assert len(raw) > 2048
        handle = _PREFIX + _raw_b64(raw)
        with pytest.raises(TagHandleError):
            decode_tag_handle(handle)

    def test_encode_rejects_non_finite_float(self) -> None:
        with pytest.raises(TagHandleError):
            encode_tag_handle(TagRef(name="x", value=float("nan")))
