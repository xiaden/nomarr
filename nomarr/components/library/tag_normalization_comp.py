"""
Tag normalization component for cross-format metadata standardization.

Maps format-specific tag names (MP4 atoms, ID3 frames, Vorbis comments) to
normalized common names that work across all audio formats.

Example:
    MP4 'aART', ID3 'TPE2', FLAC 'ALBUMARTIST' → all become 'album_artist'
"""

from __future__ import annotations

from typing import Any

# Map MP4 atoms to normalized tag names
MP4_TAG_MAP: dict[str, str] = {
    # Basic metadata
    "\xa9nam": "title",
    "\xa9ART": "artist",
    "\xa9alb": "album",
    "aART": "album_artist",
    "\xa9gen": "genre",
    "\xa9day": "date",
    "\xa9cmt": "comment",
    # Track/disc info
    "trkn": "track",  # Note: MP4 track is tuple (track, total)
    "disk": "disc",  # Note: MP4 disc is tuple (disc, total)
    # Extended metadata
    "\xa9wrt": "composer",
    "\xa9lyr": "lyrics",
    "cprt": "copyright",
    "tmpo": "bpm",
    # Sort order tags
    "soar": "sort_artist",
    "soaa": "sort_album_artist",
    "soal": "sort_album",
    "sonm": "sort_title",
    "soco": "sort_composer",
    # Additional iTunes tags
    "covr": "cover_art",
    "\xa9grp": "grouping",
    "pcst": "podcast",
    "catg": "category",
    "desc": "description",
    "ldes": "long_description",
    # Ratings and playback
    "rtng": "rating",
    "\xa9too": "encoder",
    # Compilation flag
    "cpil": "compilation",
}

# Map ID3 frames to normalized tag names
ID3_TAG_MAP: dict[str, str] = {
    # Basic metadata
    "TIT2": "title",
    "TPE1": "artist",
    "TALB": "album",
    "TPE2": "album_artist",
    "TCON": "genre",
    "TDRC": "date",  # Recording date
    "TYER": "date",  # Year (legacy)
    "COMM": "comment",
    # Track/disc info
    "TRCK": "track",  # Format: "5/12"
    "TPOS": "disc",  # Format: "1/2"
    # Extended metadata
    "TCOM": "composer",
    "USLT": "lyrics",
    "TCOP": "copyright",
    "TBPM": "bpm",
    # Sort order tags
    "TSOP": "sort_artist",
    "TSO2": "sort_album_artist",
    "TSOA": "sort_album",
    "TSOT": "sort_title",
    "TSOC": "sort_composer",
    # Additional tags
    "APIC": "cover_art",
    "TIT1": "grouping",  # Content group
    "PCST": "podcast",
    "TCAT": "category",
    "TDES": "description",
    # Ratings and playback
    "POPM": "rating",  # Popularimeter
    "TENC": "encoder",
    "TSSE": "encoder",  # Software/hardware settings
    # Compilation flag
    "TCMP": "compilation",
}

# Map Vorbis comment keys to normalized tag names (case-insensitive)
VORBIS_TAG_MAP: dict[str, str] = {
    # Basic metadata
    "TITLE": "title",
    "ARTIST": "artist",
    "ALBUM": "album",
    "ALBUMARTIST": "album_artist",
    "GENRE": "genre",
    "DATE": "date",
    "COMMENT": "comment",
    # Track/disc info
    "TRACKNUMBER": "track",
    "DISCNUMBER": "disc",
    "TRACKTOTAL": "track_total",
    "DISCTOTAL": "disc_total",
    # Extended metadata
    "COMPOSER": "composer",
    "LYRICS": "lyrics",
    "COPYRIGHT": "copyright",
    "BPM": "bpm",
    # Sort order tags (non-standard but used by some taggers)
    "ARTISTSORT": "sort_artist",
    "ALBUMARTISTSORT": "sort_album_artist",
    "ALBUMSORT": "sort_album",
    "TITLESORT": "sort_title",
    "COMPOSERSORT": "sort_composer",
    # Additional tags
    "COVERART": "cover_art",
    "METADATA_BLOCK_PICTURE": "cover_art",
    "GROUPING": "grouping",
    "PERFORMER": "performer",
    "DESCRIPTION": "description",
    # Ratings and encoding
    "RATING": "rating",
    "ENCODER": "encoder",
    # Compilation flag
    "COMPILATION": "compilation",
}


def normalize_mp4_tags(tags: dict[str, Any]) -> dict[str, str]:
    """
    Normalize MP4 tags to common tag names.

    Args:
        tags: MP4 tags dict from mutagen

    Returns:
        Dict with normalized tag names and serialized values
    """
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        # Handle freeform iTunes tags (----:com.apple.iTunes:*)
        if isinstance(key, str) and key.startswith("----:com.apple.iTunes:"):
            tag_name = key.replace("----:com.apple.iTunes:", "")
            # Only include namespace-prefixed tags (nom:, ab:, etc.)
            if ":" in tag_name:
                # Keep freeform tags with their original names (after prefix removal)
                normalized[tag_name] = _serialize_value(value)
            continue

        # Map standard atoms to normalized names
        if key in MP4_TAG_MAP:
            norm_key = MP4_TAG_MAP[key]
            normalized[norm_key] = _serialize_value(value)

    return normalized


def normalize_id3_tags(tags: dict[str, Any]) -> dict[str, str]:
    """
    Normalize ID3 tags to common tag names.

    Args:
        tags: ID3 tags dict from mutagen

    Returns:
        Dict with normalized tag names and serialized values
    """
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        # Handle TXXX frames (user-defined text)
        if isinstance(key, str) and key.startswith("TXXX:"):
            tag_name = key[5:]  # Remove "TXXX:" prefix
            # Only include namespace-prefixed tags (nom:, ab:, etc.)
            if ":" in tag_name:
                normalized[tag_name] = _serialize_value(value)
            continue

        # Map standard frames to normalized names
        # Extract frame type (first 4 chars)
        frame_type = key[:4] if isinstance(key, str) and len(key) >= 4 else key
        if frame_type in ID3_TAG_MAP:
            norm_key = ID3_TAG_MAP[frame_type]
            normalized[norm_key] = _serialize_value(value)

    return normalized


def normalize_vorbis_tags(tags: dict[str, Any]) -> dict[str, str]:
    """
    Normalize Vorbis comments to common tag names.

    Args:
        tags: Vorbis comments dict from mutagen (FLAC, Ogg, etc.)

    Returns:
        Dict with normalized tag names and serialized values
    """
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        # Vorbis comments are case-insensitive
        key_upper = key.upper()

        # Handle namespace-prefixed tags (nom:, ab:, etc.)
        if ":" in key:
            # Keep namespace tags with original casing
            normalized[key] = _serialize_value(value)
            continue

        # Map standard Vorbis fields to normalized names
        if key_upper in VORBIS_TAG_MAP:
            norm_key = VORBIS_TAG_MAP[key_upper]
            normalized[norm_key] = _serialize_value(value)

    return normalized


def _serialize_value(value: Any) -> str:
    """
    Serialize a tag value to string.

    Handles various mutagen types:
    - MP4FreeForm: Extract bytes and decode
    - Lists: Take first value or join multiple values
    - Tuples (MP4 track/disc): Format as "N/total"
    - Bytes: Decode to UTF-8
    - Everything else: str()

    Args:
        value: Tag value from mutagen

    Returns:
        String representation
    """
    # Handle MP4 track/disc tuples: (track, total)
    if isinstance(value, tuple) and len(value) >= 2 and all(isinstance(x, int) for x in value[:2]):
        return f"{value[0]}/{value[1]}" if value[1] > 0 else str(value[0])

    # Handle lists (common in mutagen)
    if isinstance(value, list):
        if len(value) == 0:
            return ""
        # For single-item lists, unwrap
        if len(value) == 1:
            item = value[0]
            if isinstance(item, bytes):
                return item.decode("utf-8", errors="replace")
            return str(item)
        # For multi-value lists, join with semicolon
        return "; ".join(
            item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item) for item in value
        )

    # Handle bytes directly
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    # Handle ID3 text frames (have .text attribute)
    if hasattr(value, "text"):
        text_value = value.text
        if isinstance(text_value, list):
            return "; ".join(str(t) for t in text_value) if text_value else ""
        return str(text_value)

    # Everything else
    return str(value) if value is not None else ""
