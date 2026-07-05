"""Metadata normalization for fuzzy matching.

Normalizes artist/title/album strings to improve matching accuracy:
- Lowercase
- Strip punctuation
- Remove featuring/feat./ft. suffixes
- Normalize whitespace
- Strip common suffixes (Remastered, Live, etc.)
"""

from __future__ import annotations

import re
import unicodedata

# Pattern to match featuring indicators and everything after
_FEATURING_PATTERN = re.compile(
    r"\s*[\(\[]?\s*"
    r"(?:feat(?:uring)?\.?|ft\.?|with|&|x)\s+"
    r"[^\)\]]*[\)\]]?"
    r"$",
    re.IGNORECASE,
)

# Pattern to match common track suffixes to strip
_SUFFIX_PATTERN = re.compile(
    r"\s*[\(\[]\s*"
    r"(?:"
    r"remaster(?:ed)?(?:\s+\d{4})?"
    r"|live(?:\s+(?:at|from|in)[^\)\]]*)?"
    r"|(?:original\s+)?(?:album\s+)?version"
    r"|mono(?:\s+version)?"
    r"|stereo(?:\s+version)?"
    r"|radio\s+edit"
    r"|single\s+version"
    r"|bonus\s+track"
    r"|explicit"
    r"|clean(?:\s+version)?"
    r")"
    r"\s*[\)\]]"
    r"$",
    re.IGNORECASE,
)

# Pattern to match punctuation except apostrophes
_PUNCTUATION_PATTERN = re.compile(r"[^\w\s'']")

# Multiple spaces
_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_for_matching(text: str) -> str:
    """Normalize a string for fuzzy matching.

    Applies: NFKC normalization, lowercase, strip featuring/version suffixes,
    remove punctuation, collapse whitespace.
    """
    if not text:
        return ""

    result = unicodedata.normalize("NFKC", text)
    result = result.lower()

    prev = None
    while prev != result:
        prev = result
        result = _FEATURING_PATTERN.sub("", result)

    prev = None
    while prev != result:
        prev = result
        result = _SUFFIX_PATTERN.sub("", result)

    result = _PUNCTUATION_PATTERN.sub(" ", result)
    result = result.replace("'", "").replace("'", "")
    result = _WHITESPACE_PATTERN.sub(" ", result)

    return result.strip()


def normalize_artist(artist: str) -> str:
    """Normalize an artist name, stripping leading 'the' prefix."""
    result = normalize_for_matching(artist)
    return result.removeprefix("the ")


def normalize_title(title: str) -> str:
    """Normalize a track title for matching."""
    return normalize_for_matching(title)


def normalize_album(album: str) -> str:
    """Normalize an album name, also stripping disc/CD number suffixes."""
    result = normalize_for_matching(album)
    result = re.sub(r"\s*(?:disc|cd)\s*\d+\s*$", "", result, flags=re.IGNORECASE)
    return result.strip()
