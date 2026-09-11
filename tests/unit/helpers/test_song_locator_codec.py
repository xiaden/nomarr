"""Contract tests for the opaque ``nom1`` SongLocator codec (ADR-048 / ADR-049).

Covers the P3-S1 positive canonical contract (round trip, library-scope
distinction, wire shape/ordering, ``library_uuid`` presence) and the P3-S2
negative contract (integer ids, missing/malformed/noncanonical/unknown-version
tokens, alternate formats, malformed/unknown UUIDs, noncanonical paths, and the
structural absence of an integer wire adapter, shim, alias, or dual path).

The authoritative wire format is ``nom1`` + unpadded URL-safe base64 of the
canonical compact JSON ``{"library_uuid": <v4 uuid>, "path": <relative path>}``
(CONTRACTS §7). Tests import only ``nomarr.helpers`` (and DTOs) so they collect
independently of the H-owned ``file_write_comp`` import chain that blocks
``nomarr.interfaces.api``.
"""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dto.library_dto import LibraryDict
from nomarr.helpers.dto.repo_dto import LibraryRow
from nomarr.helpers.song_locator_codec import (
    CANONICAL_UUID4_RE,
    SONG_LOCATOR_MAX_LENGTH,
    SONG_LOCATOR_PREFIX,
    SongLocatorFormatError,
    SongLocatorPayload,
    canonical_song_locator_json,
    decode_song_locator,
    encode_song_locator,
    is_canonical_relative_path,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Canonical lowercase hyphenated version-4 UUIDs (only the 3rd group's leading
# ``4`` and the 4th group's ``[89ab]`` variant nibble matter).
_UUID_A = "123e4567-e89b-42d3-a456-426614174000"
_UUID_B = "223e4567-e89b-42d3-b456-426614174001"
_UUID_V5 = "123e4567-e89b-52d3-a456-426614174000"  # version nibble 5 -> non-v4

# Every projection surface named by the P3-S1 shape test (CONTRACTS §7).
_PROJECTION_SOURCES = (
    _REPO_ROOT / "nomarr/helpers/song_locator_codec.py",
    _REPO_ROOT / "nomarr/interfaces/api/id_codec.py",
    _REPO_ROOT / "nomarr/components/navidrome/descriptor_match_comp.py",
    _REPO_ROOT / "nomarr/components/navidrome/playlist_builder_comp.py",
    _REPO_ROOT / "nomarr/services/domain/navidrome_svc.py",
    _REPO_ROOT / "nomarr/components/library/search_files_comp.py",
    _REPO_ROOT / "nomarr/components/analytics/mood_analysis_comp.py",
    _REPO_ROOT / "nomarr/components/analytics/analytics_comp.py",
)


def _locator(library_uuid: str, path: str) -> SongIdentity:
    return SongIdentity(library=LibraryIdentity(library_uuid=library_uuid), normalized_path=path)


def _raw_token(raw: bytes, prefix: str = SONG_LOCATOR_PREFIX) -> str:
    """Build a token from raw JSON bytes (for malformed/noncanonical cases)."""
    return prefix + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _json_token(payload: object, prefix: str = SONG_LOCATOR_PREFIX) -> str:
    return _raw_token(json.dumps(payload, separators=(",", ":")).encode("utf-8"), prefix)


# ─────────────────────────────────────────────────────────────────────────
# P3-S1 — positive canonical contract
# ─────────────────────────────────────────────────────────────────────────


class TestCanonicalRoundTrip:
    """encode/decode round-trips the UUID-bearing locator exactly."""

    @pytest.mark.parametrize(
        ("library_uuid", "path"),
        [
            (_UUID_A, "song.mp3"),
            (_UUID_A, "Artist/Album/01 Track.flac"),
            (_UUID_B, "a/b/c/d/e/f/g.m4a"),
            (_UUID_A, "École/01 Café — Déjà Vu.opus"),
            (_UUID_B, "dir with spaces/track (deluxe).mp3"),
        ],
    )
    def test_round_trip_preserves_uuid_and_path(self, library_uuid: str, path: str) -> None:
        token = encode_song_locator(_locator(library_uuid, path))
        payload = decode_song_locator(token)
        assert isinstance(payload, SongLocatorPayload)
        assert payload.library_uuid == library_uuid
        assert payload.path == path

    def test_token_has_canonical_prefix_and_alphabet(self) -> None:
        token = encode_song_locator(_locator(_UUID_A, "song.mp3"))
        assert token.startswith(SONG_LOCATOR_PREFIX)
        body = token[len(SONG_LOCATOR_PREFIX) :]
        assert body
        assert "=" not in body
        assert "+" not in body and "/" not in body
        assert all(ch.isalnum() or ch in "-_" for ch in body)

    def test_encoding_is_deterministic(self) -> None:
        locator = _locator(_UUID_A, "song.mp3")
        assert encode_song_locator(locator) == encode_song_locator(locator)

    def test_canonical_json_has_exact_key_set_and_order(self) -> None:
        raw = canonical_song_locator_json(_UUID_A, "song.mp3")
        assert raw == json.dumps(
            {"library_uuid": _UUID_A, "path": "song.mp3"},
            separators=(",", ":"),
            ensure_ascii=False,
        )
        assert list(json.loads(raw)) == ["library_uuid", "path"]

    def test_ratified_bounds(self) -> None:
        assert SONG_LOCATOR_MAX_LENGTH == 8192
        assert SONG_LOCATOR_PREFIX == "nom1"
        assert CANONICAL_UUID4_RE.pattern.startswith("^")


class TestLibraryScopeIdentity:
    """The UUID alone distinguishes libraries; the path alone never does."""

    def test_same_path_different_library_yields_different_tokens(self) -> None:
        token_a = encode_song_locator(_locator(_UUID_A, "song.mp3"))
        token_b = encode_song_locator(_locator(_UUID_B, "song.mp3"))
        assert token_a != token_b
        assert decode_song_locator(token_a).library_uuid == _UUID_A
        assert decode_song_locator(token_b).library_uuid == _UUID_B

    def test_library_name_and_root_path_do_not_enter_identity(self) -> None:
        lib = Library(name="Whatever", root_path="/mnt/music", library_uuid=_UUID_A)
        identity_named = LibraryIdentity(library_uuid=lib.library_uuid, name=lib.name, root_path=lib.root_path)
        identity_bare = LibraryIdentity(library_uuid=_UUID_A)
        loc_named = SongIdentity(library=identity_named, normalized_path="song.mp3")
        loc_bare = SongIdentity(library=identity_bare, normalized_path="song.mp3")
        assert encode_song_locator(loc_named) == encode_song_locator(loc_bare)
        assert identity_named == identity_bare


class TestWireShapeAndOrdering:
    """Shape is preserved across projections; integer identity values are not."""

    def test_ordering_is_preserved_across_a_locator_list(self) -> None:
        locators = [_locator(_UUID_A, f"track-{i:02d}.mp3") for i in range(5)]
        tokens = [encode_song_locator(locator) for locator in locators]
        assert len(set(tokens)) == 5
        for locator, token in zip(locators, tokens, strict=True):
            assert decode_song_locator(token).path == locator.normalized_path

    @pytest.mark.parametrize("wire_field", ["file_id", "song_id", "track_id"])
    def test_legacy_field_name_survives_but_holds_an_opaque_token(self, wire_field: str) -> None:
        """The JSON key is unchanged while the value is no longer an integer."""
        locator = _locator(_UUID_A, "song.mp3")
        token = encode_song_locator(locator)
        wire = {wire_field: token, "path": "song.mp3", "library_uuid": _UUID_A}
        assert isinstance(wire[wire_field], str)
        assert wire[wire_field].startswith("nom1")
        assert not wire[wire_field].isdigit()
        with pytest.raises(ValueError):
            int(wire[wire_field])

    def test_library_transport_carries_library_uuid(self) -> None:
        assert "library_uuid" in LibraryDict.__dataclass_fields__
        assert "library_uuid" in LibraryRow.__annotations__
        assert "library_uuid" in Library.__dataclass_fields__

    def test_navidrome_entry_shape_is_a_list_of_opaque_tokens(self) -> None:
        from nomarr.helpers.dto.navidrome_dto import NavidromePersonalPlaylistEntry

        tokens = [encode_song_locator(_locator(_UUID_A, f"s{i}.mp3")) for i in range(3)]
        entry = NavidromePersonalPlaylistEntry(
            playlist_type="familiar",
            playlist_name="Your Favorites",
            file_ids=tokens,
        )
        assert entry["file_ids"] == tokens
        assert all(isinstance(item, str) and item.startswith("nom1") for item in entry["file_ids"])


# ─────────────────────────────────────────────────────────────────────────
# P3-S2 — negative contract (rejection)
# ─────────────────────────────────────────────────────────────────────────


class TestRejectsIntegerIdentity:
    """The codec is str-only; no integer fallback or coercion path exists."""

    @pytest.mark.parametrize("value", [42, 0, -1, True, False])
    def test_non_string_tokens_are_rejected(self, value: object) -> None:
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(value)  # type: ignore[arg-type]

    def test_integer_file_id_is_not_a_token(self) -> None:
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator("42")

    def test_song_locator_format_error_is_a_value_error(self) -> None:
        assert issubclass(SongLocatorFormatError, ValueError)


class TestRejectsMalformedTokens:
    """Missing, truncated, over-long, and prefix-wrong tokens are rejected."""

    @pytest.mark.parametrize("token", ["", " ", "nom1", "nom1=", "nom1 ", " nom1abc"])
    def test_missing_or_empty_body(self, token: str) -> None:
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(token)

    def test_over_ceiling_token_is_rejected(self) -> None:
        long_token = SONG_LOCATOR_PREFIX + ("A" * SONG_LOCATOR_MAX_LENGTH)
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(long_token)

    @pytest.mark.parametrize("prefix", ["nom2", "nom0", "nom10", "noms1", "9nom1"])
    def test_unknown_or_absent_version_prefix_is_rejected(self, prefix: str) -> None:
        body = base64.urlsafe_b64encode(b'{"library_uuid":"x","path":"y"}').decode().rstrip("=")
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(prefix + body)

    def test_padded_base64_is_rejected(self) -> None:
        raw = canonical_song_locator_json(_UUID_A, "song.mp3").encode("utf-8")
        padded = SONG_LOCATOR_PREFIX + base64.urlsafe_b64encode(raw).decode()
        assert "=" in padded
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(padded)

    def test_standard_base64_alphabet_is_rejected(self) -> None:
        # The path "aa?" makes the canonical payload's standard base64 contain
        # "/" (URL-safe base64 would emit "_"), so the two alphabets differ.
        raw = canonical_song_locator_json(_UUID_A, "aa?").encode("utf-8")
        standard = SONG_LOCATOR_PREFIX + base64.b64encode(raw).decode().rstrip("=")
        assert "/" in standard or "+" in standard
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(standard)

    def test_non_utf8_body_is_rejected(self) -> None:
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(_raw_token(b"\xff\xfe\x00\x81"))

    def test_invalid_json_body_is_rejected(self) -> None:
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(_raw_token(b"not-json"))


class TestRejectsAlternateFormats:
    """Natural-name tokens, lists, and extra/missing keys are not accepted."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"library_name": "Music", "path": "song.mp3"},
            {"library_uuid": _UUID_A, "normalized_path": "song.mp3"},
            {"library_uuid": _UUID_A, "path": "song.mp3", "extra": 1},
            {"library_uuid": _UUID_A},
            {"path": "song.mp3"},
            {"library_uuid": _UUID_A, "path": "song.mp3", "root_path": "/music"},
        ],
    )
    def test_wrong_key_set_is_rejected(self, payload: dict[str, object]) -> None:
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(_json_token(payload))

    def test_non_compact_json_is_rejected(self) -> None:
        spaced = json.dumps({"library_uuid": _UUID_A, "path": "song.mp3"}, indent=2).encode("utf-8")
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(_raw_token(spaced))

    def test_ascii_escaped_unicode_is_the_canonical_form(self) -> None:
        # ensure_ascii=True is canonical, so the escaped spelling is accepted.
        escaped = canonical_song_locator_json(_UUID_A, "café.mp3").encode("utf-8")
        assert b"\\u00e9" in escaped
        assert decode_song_locator(_raw_token(escaped)).path == "café.mp3"

    def test_legacy_concatenated_form_is_rejected(self) -> None:
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(_json_token({"library": "Music", "normalized_path": "song.mp3"}, prefix="nom1"))


class TestRejectsMalformedUuids:
    """Only canonical lowercase hyphenated version-4 UUIDs are canonical."""

    @pytest.mark.parametrize(
        "bad_uuid",
        [
            _UUID_A.upper(),
            "{" + _UUID_A + "}",
            "urn:uuid:" + _UUID_A,
            _UUID_A.replace("-", ""),
            _UUID_V5,
            "123e4567-e89b-42d3-c456-426614174000",  # variant nibble c
            "123e4567-e89b-42d3-0456-426614174000",  # variant nibble 0
            "123e4567-e89b-42d3-a456-42661417400",  # short
            "123e4567-e89b-42d3-a456-4266141740000",  # long
            "123e4567e89b42d3a456426614174000",
            "",
        ],
    )
    def test_malformed_uuid_is_rejected(self, bad_uuid: str) -> None:
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(_json_token({"library_uuid": bad_uuid, "path": "song.mp3"}))

    def test_wellformed_unknown_uuid_still_decodes(self) -> None:
        """Format validity is syntax-only; existence is a facade/404 concern."""
        payload = decode_song_locator(_json_token({"library_uuid": _UUID_B, "path": "song.mp3"}))
        assert payload.library_uuid == _UUID_B


class TestRejectsNoncanonicalPaths:
    """Only canonical relative paths are valid locator paths."""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "",
            "/abs/song.mp3",
            "./song.mp3",
            "dir/./song.mp3",
            "dir/../song.mp3",
            "dir//song.mp3",
            "dir/song.mp3/",
            "dir\\song.mp3",
        ],
    )
    def test_noncanonical_path_is_rejected(self, bad_path: str) -> None:
        assert not is_canonical_relative_path(bad_path)
        with pytest.raises(SongLocatorFormatError):
            decode_song_locator(_json_token({"library_uuid": _UUID_A, "path": bad_path}))

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known codec gap (residual for plan I): is_canonical_relative_path uses "
            "posixpath.normpath, which preserves a leading '..' segment, contradicting "
            "the documented 'no . or .. segments' canonical grammar. Strict xfail so "
            "this flips to a failure once the codec rejects parent escapes."
        ),
    )
    def test_leading_parent_segment_is_rejected(self) -> None:
        assert not is_canonical_relative_path("../escape/song.mp3")

    @pytest.mark.parametrize("good_path", ["song.mp3", "dir/song.mp3", "a/b/c.flac", "École/café.opus"])
    def test_canonical_relative_path_is_accepted(self, good_path: str) -> None:
        assert is_canonical_relative_path(good_path)
        assert decode_song_locator(encode_song_locator(_locator(_UUID_A, good_path))).path == good_path


class TestErrorsDoNotLeakTokenContents:
    """Format errors must not echo the rejected token or its decoded payload."""

    def test_error_message_does_not_echo_token(self) -> None:
        secret = "do-not-leak-this-value"
        token = _json_token({"library_uuid": _UUID_A, "path": secret}, prefix="nom2")
        with pytest.raises(SongLocatorFormatError) as excinfo:
            decode_song_locator(token)
        message = str(excinfo.value)
        assert token not in message
        assert secret not in message
        assert _UUID_A not in message

    def test_error_message_does_not_echo_integer_id(self) -> None:
        with pytest.raises(SongLocatorFormatError) as excinfo:
            decode_song_locator(4242)  # type: ignore[arg-type]
        assert "4242" not in str(excinfo.value)


# ─────────────────────────────────────────────────────────────────────────
# P3-S2 — structural absence of integer adapter / shim / dual path
# ─────────────────────────────────────────────────────────────────────────


class TestNoIntegerIdentityPath:
    """No removed integer codec, resolver, shim, alias, or dual version path."""

    _FORBIDDEN = (
        "resolve_file_id",
        "encode_id(",
        "decode_id(",
        "decode_path_id",
        "encode_ids(",
        "_ID_FIELD_NAMES",
        "def encode_id",
        "def decode_id",
    )

    def test_projection_sources_contain_no_integer_identity_symbols(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in _PROJECTION_SOURCES:
            source = path.read_text(encoding="utf-8")
            hits = [name for name in self._FORBIDDEN if name in source]
            if hits:
                offenders[str(path.relative_to(_REPO_ROOT))] = hits
        assert offenders == {}, f"removed integer identity symbols resurfaced: {offenders}"

    def test_codec_has_no_dual_version_branch(self) -> None:
        source = (_REPO_ROOT / "nomarr/helpers/song_locator_codec.py").read_text(encoding="utf-8")
        assert '"nom2"' not in source
        assert "'nom2'" not in source
        assert SONG_LOCATOR_PREFIX == "nom1"

    def test_codec_source_has_no_int_coercion_of_token(self) -> None:
        source = (_REPO_ROOT / "nomarr/helpers/song_locator_codec.py").read_text(encoding="utf-8")
        assert "isinstance(token, int)" not in source
        assert "int(token" not in source

    def test_no_caller_owned_transactions_in_projection_components(self) -> None:
        """Schema-identity projections never open their own transaction boundary."""
        transaction_attrs = {"begin", "begin_transaction", "begin_nested", "with_transaction"}
        offenders: list[str] = []
        for path in _PROJECTION_SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in transaction_attrs
                ):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}:{node.func.attr}")
                if isinstance(node, ast.With):
                    for item in node.items:
                        expr = item.context_expr
                        if (
                            isinstance(expr, ast.Call)
                            and isinstance(expr.func, ast.Attribute)
                            and expr.func.attr in transaction_attrs
                        ):
                            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}:{expr.func.attr}")
        assert offenders == [], f"projection components opened caller-owned transactions: {offenders}"
