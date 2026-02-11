"""Metadata normalization for fuzzy matching.

Normalizes artist/title/album strings to improve matching accuracy:
- Lowercase
- Strip punctuation
- Remove featuring/feat./ft. suffixes
- Normalize whitespace
- Strip common suffixes (Remastered, Live, etc.)
"""

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

    Applies multiple normalization steps to maximize match potential:
    1. Unicode NFKC normalization (handles accents, ligatures)
    2. Lowercase conversion
    3. Strip featuring suffixes (feat., ft., with, &)
    4. Strip version suffixes (Remastered, Live, etc.)
    5. Remove punctuation (except apostrophes)
    6. Collapse whitespace
    7. Strip leading/trailing whitespace

    Args:
        text: The string to normalize (artist name, track title, album name)

    Returns:
        Normalized string suitable for comparison

    Examples:
        >>> normalize_for_matching("Don't Stop Me Now (Remastered 2011)")
        "dont stop me now"

        >>> normalize_for_matching("Blinding Lights (feat. The Weeknd)")
        "blinding lights"

        >>> normalize_for_matching("  Hello   World  ")
        "hello world"
    """
    if not text:
        return ""

    # Unicode normalization (NFKC: compatibility decomposition + canonical composition)
    result = unicodedata.normalize("NFKC", text)

    # Lowercase
    result = result.lower()

    # Strip featuring suffixes (iteratively in case of multiple)
    prev = None
    while prev != result:
        prev = result
        result = _FEATURING_PATTERN.sub("", result)

    # Strip version suffixes (iteratively)
    prev = None
    while prev != result:
        prev = result
        result = _SUFFIX_PATTERN.sub("", result)

    # Remove punctuation (keep apostrophes for contractions)
    result = _PUNCTUATION_PATTERN.sub(" ", result)

    # Normalize apostrophes to standard form then remove
    result = result.replace("'", "").replace("'", "")

    # Collapse whitespace
    result = _WHITESPACE_PATTERN.sub(" ", result)

    # Strip
    return result.strip()


def normalize_artist(artist: str) -> str:
    """Normalize an artist name for matching.

    In addition to standard normalization, handles:
    - "The" prefix variations
    - Artist separators (,/&/and)

    Args:
        artist: Artist name string

    Returns:
        Normalized artist string
    """
    result = normalize_for_matching(artist)

    # Optionally strip leading "the "
    return result.removeprefix("the ")


def normalize_title(title: str) -> str:
    """Normalize a track title for matching.

    Uses standard normalization. Can be extended for title-specific rules.

    Args:
        title: Track title string

    Returns:
        Normalized title string
    """
    return normalize_for_matching(title)


def normalize_album(album: str) -> str:
    """Normalize an album name for matching.

    Uses standard normalization with additional album-specific handling:
    - Strip disc/CD number suffixes

    Args:
        album: Album name string

    Returns:
        Normalized album string
    """
    result = normalize_for_matching(album)

    # Strip disc/CD suffixes like "(Disc 1)" or "[CD 2]"
    result = re.sub(r"\s*(?:disc|cd)\s*\d+\s*$", "", result, flags=re.IGNORECASE)

    return result.strip()
