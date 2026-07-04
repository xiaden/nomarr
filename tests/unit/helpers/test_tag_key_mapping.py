"""Unit tests for tag_key_mapping.py — Navidrome display-name mapping."""

from __future__ import annotations

import pytest

from nomarr.helpers.tag_key_mapping import (
    extract_label_from_versioned_key,
    is_versioned_ml_key,
    make_navidrome_field_name,
    make_short_tag_name,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# is_versioned_ml_key
# ---------------------------------------------------------------------------


class TestIsVersionedMlKey:
    """Tests for ``is_versioned_ml_key``."""

    def test_identifies_model_key_with_known_backbone(self):
        """A key like nom:happy_yamnet_mood_happy is a versioned ML key."""
        assert is_versioned_ml_key("nom:happy_yamnet_mood_happy") is True

    def test_identifies_key_with_effnet_backbone(self):
        """Keys with 'effnet' backbone are detected (need model_stem after backbone)."""
        assert is_versioned_ml_key("nom:genre_discogs_effnet_v1") is True

    def test_returns_false_for_passthrough_tag(self):
        """'mood-strict' is a passthrough, not a versioned ML key."""
        assert is_versioned_ml_key("nom:mood-strict") is False

    def test_returns_false_for_too_short_key(self):
        """Keys with fewer than 3 underscore-separated parts return False."""
        assert is_versioned_ml_key("nom:just_two") is False

    def test_returns_false_for_key_with_no_known_backbone(self):
        """Keys without a known backbone token return False."""
        assert is_versioned_ml_key("nom:unknown_model_key") is False

    def test_returns_false_when_model_stem_is_empty(self):
        """Key with backbone but no model_stem after it returns False."""
        assert is_versioned_ml_key("nom:genre_discogs_effnet") is False


# ---------------------------------------------------------------------------
# extract_label_from_versioned_key
# ---------------------------------------------------------------------------


class TestExtractLabelFromVersionedKey:
    """Tests for ``extract_label_from_versioned_key``."""

    def test_extracts_label_from_model_key(self):
        """The label before the backbone is extracted."""
        result = extract_label_from_versioned_key("nom:happy_yamnet_mood_happy")
        assert result == "happy"

    def test_extracts_multi_word_label(self):
        """Labels with underscores are preserved."""
        result = extract_label_from_versioned_key("nom:not_happy_yamnet_mood_happy")
        assert result == "not_happy"

    def test_returns_none_for_non_model_key(self):
        """Non-model keys return None."""
        result = extract_label_from_versioned_key("nom:mood-strict")
        assert result is None

    def test_returns_none_for_short_key(self):
        """Keys too short to be model keys return None."""
        result = extract_label_from_versioned_key("nom:short")
        assert result is None


# ---------------------------------------------------------------------------
# make_short_tag_name
# ---------------------------------------------------------------------------


class TestMakeShortTagName:
    """Tests for ``make_short_tag_name``."""

    def test_makes_short_name_for_numeric_model_key(self):
        """A numeric ML key becomes 'nom-label-raw'."""
        result = make_short_tag_name("nom:happy_yamnet_mood_happy", is_numeric=True)
        assert result == "nom-happy-raw"

    def test_makes_short_name_for_non_numeric_model_key(self):
        """A non-numeric ML key omits the '-raw' suffix."""
        result = make_short_tag_name("nom:happy_yamnet_mood_happy", is_numeric=False)
        assert result == "nom-happy"

    def test_passthrough_mood_strict(self):
        """'mood-strict' is preserved as 'nom-mood-strict'."""
        result = make_short_tag_name("nom:mood-strict")
        assert result == "nom-mood-strict"

    def test_passthrough_mood_regular(self):
        """'mood-regular' is preserved as 'nom-mood-regular'."""
        result = make_short_tag_name("nom:mood-regular")
        assert result == "nom-mood-regular"

    def test_passthrough_mood_loose(self):
        """'mood-loose' is preserved as 'nom-mood-loose'."""
        result = make_short_tag_name("nom:mood-loose")
        assert result == "nom-mood-loose"

    def test_passthrough_effnet_prefix(self):
        """Keys starting with 'effnet_' are treated as passthrough."""
        result = make_short_tag_name("nom:effnet_some_key")
        assert result == "nom-effnet-some-key"

    def test_converts_underscores_to_hyphens_in_fallback(self):
        """Fallback path converts underscores to hyphens."""
        result = make_short_tag_name("nom:custom_tag_name_here")
        assert result == "nom-custom-tag-name-here"

    def test_handles_label_with_underscores(self):
        """Labels containing underscores have them converted to hyphens."""
        result = make_short_tag_name("nom:not_happy_yamnet_mood_happy", is_numeric=True)
        assert result == "nom-not-happy-raw"


# ---------------------------------------------------------------------------
# make_navidrome_field_name
# ---------------------------------------------------------------------------


class TestMakeNavidromeFieldName:
    """Tests for ``make_navidrome_field_name``."""

    def test_converts_hyphens_to_underscores(self):
        """Hyphens in short names become underscores for TOML compatibility."""
        result = make_navidrome_field_name("nom-happy-raw")
        assert result == "nom_happy_raw"

    def test_no_hyphens_returns_same(self):
        """Names without hyphens are returned unchanged."""
        result = make_navidrome_field_name("nom_happy_raw")
        assert result == "nom_happy_raw"

    def test_handles_passthrough_name(self):
        """Passthrough names have hyphens converted."""
        result = make_navidrome_field_name("nom-mood-strict")
        assert result == "nom_mood_strict"
