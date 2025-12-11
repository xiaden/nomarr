"""
Tag normalization component for cross-format metadata standardization.

Maps format-specific tag names (MP4 atoms, ID3 frames, Vorbis comments) to
a small canonical set of normalized names.

Canonical tag set:
- title, artist, artists, album, album_artist
- tracknumber, discnumber
- date, year, genre
- composer, lyricist, label, publisher
- bpm
- nom:* (namespaced Nomarr tags)

Everything else is discarded.
"""

from __future__ import annotations

import json
from typing import Any

# Canonical tag set - only these keys (plus nom:*) will be kept
CANONICAL_TAGS = {
    "title",
    "artist",
    "artists",
    "album",
    "album_artist",
    "tracknumber",
    "discnumber",
    "date",
    "year",
    "genre",
    "composer",
    "lyricist",
    "label",
    "publisher",
    "bpm",
}

# MP4 atoms to canonical tag names (ONLY canonical mappings)
MP4_TAG_MAP: dict[str, str] = {
    "\xa9nam": "title",
    "\xa9ART": "artist",
    "\xa9alb": "album",
    "aART": "album_artist",
    "\xa9gen": "genre",
    "\xa9day": "date",
    "trkn": "tracknumber",  # Note: MP4 track is tuple (track, total)
    "disk": "discnumber",  # Note: MP4 disc is tuple (disc, total)
    "\xa9wrt": "composer",
    "tmpo": "bpm",
}

# MP4 freeform iTunes tags (----:com.apple.iTunes:*) - canonical only
MP4_FREEFORM_MAP: dict[str, str] = {
    "ARTISTS": "artists",
    "LABEL": "label",
    "originaldate": "date",
    "originalyear": "year",
}

# Explicitly DROP these MP4 freeform tags (for documentation/clarity)
MP4_FREEFORM_BLOCKLIST = {
    "Acoustid Fingerprint",
    "ASIN",
    "BARCODE",
    "CATALOGNUMBER",
    "ENGINEER",
    "MIXER",
    "PRODUCER",
    "LANGUAGE",
    "MEDIA",
    "SCRIPT",
    "iTunNORM",
    "iTunSMPB",
    "initialkey",
}

# ID3 frames to canonical tag names (ONLY canonical mappings)
ID3_TAG_MAP: dict[str, str] = {
    "TIT2": "title",
    "TPE1": "artist",
    "TALB": "album",
    "TPE2": "album_artist",
    "TCON": "genre",
    "TDRC": "date",  # Recording date
    "TYER": "year",  # Year (legacy)
    "TRCK": "tracknumber",  # Format: "5/12"
    "TPOS": "discnumber",  # Format: "1/2"
    "TCOM": "composer",
    "TEXT": "lyricist",
    "TPUB": "publisher",
    "TBPM": "bpm",
}

# ID3 TXXX (user-defined) mappings - canonical only
ID3_TXXX_MAP: dict[str, str] = {
    "ARTISTS": "artists",
    "artists": "artists",
    "LABEL": "label",
    "label": "label",
}

# Vorbis comment keys to canonical tag names (case-insensitive, ONLY canonical mappings)
VORBIS_TAG_MAP: dict[str, str] = {
    "TITLE": "title",
    "ARTIST": "artist",
    "ARTISTS": "artists",
    "ALBUM": "album",
    "ALBUMARTIST": "album_artist",
    "GENRE": "genre",
    "DATE": "date",
    "YEAR": "year",
    "TRACKNUMBER": "tracknumber",
    "DISCNUMBER": "discnumber",
    "COMPOSER": "composer",
    "LYRICIST": "lyricist",
    "LABEL": "label",
    "PUBLISHER": "publisher",
    "BPM": "bpm",
    "TEMPO": "bpm",
}


def normalize_mp4_tags(tags: Any) -> dict[str, str]:
    """
    Normalize MP4 tags to canonical tag names only.

    Only keeps canonical tags (title, artist, album, etc.) and nom:* namespaced tags.
    Drops cover art, sort tags, iTunes metadata, Acoustid fingerprints, etc.

    Args:
        tags: MP4 tags dict-like object from mutagen

    Returns:
        Dict with canonical tag names and serialized values (+ nom:* tags)
    """
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        # Skip cover art (binary data, don't serialize)
        if key == "covr":
            continue

        # Handle freeform iTunes tags (----:com.apple.iTunes:*)
        if isinstance(key, str) and key.startswith("----:com.apple.iTunes:"):
            tag_name = key.replace("----:com.apple.iTunes:", "")

            # Keep nom:* namespaced tags
            if tag_name.startswith("nom:"):
                normalized[tag_name] = _serialize_value(value)
                continue

            # Drop blocklisted tags (Acoustid, iTunNORM, etc.)
            if tag_name in MP4_FREEFORM_BLOCKLIST:
                continue

            # Drop old auto-tagging noise (ab:*, z_*)
            if tag_name.startswith(("ab:", "z_")):
                continue

            # Map canonical freeform tags (ARTISTS, LABEL, originaldate, etc.)
            if tag_name in MP4_FREEFORM_MAP:
                norm_key = MP4_FREEFORM_MAP[tag_name]
                normalized[norm_key] = _serialize_value(value)

            continue

        # Map standard atoms to canonical names
        if key in MP4_TAG_MAP:
            norm_key = MP4_TAG_MAP[key]
            normalized[norm_key] = _serialize_value(value)

    # Filter to only canonical tags + nom:*
    filtered: dict[str, str] = {}
    for key, value in normalized.items():
        if key.startswith("nom:") or key in CANONICAL_TAGS:
            filtered[key] = value

    return filtered


def normalize_id3_tags(tags: Any) -> dict[str, str]:
    """
    Normalize ID3 tags to canonical tag names only.

    Only keeps canonical tags and nom:* namespaced tags.
    Drops cover art (APIC), lyrics (USLT), and other non-canonical frames.

    Args:
        tags: ID3 tags dict-like object from mutagen

    Returns:
        Dict with canonical tag names and serialized values (+ nom:* tags)
    """
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        # Handle TXXX frames (user-defined text)
        if isinstance(key, str) and key.startswith("TXXX:"):
            tag_name = key[5:]  # Remove "TXXX:" prefix

            # Keep nom:* namespaced tags
            if tag_name.startswith("nom:"):
                normalized[tag_name] = _serialize_value(value)
                continue

            # Map canonical TXXX tags (case-insensitive check)
            tag_name_upper = tag_name.upper()
            if tag_name_upper in ID3_TXXX_MAP:
                norm_key = ID3_TXXX_MAP[tag_name_upper]
                normalized[norm_key] = _serialize_value(value)

            continue

        # Skip binary/picture frames (APIC, GEOB, etc.)
        frame_type = key[:4] if isinstance(key, str) and len(key) >= 4 else key
        if frame_type in ("APIC", "GEOB", "USLT", "SYLT"):
            continue

        # Map standard frames to canonical names
        if frame_type in ID3_TAG_MAP:
            norm_key = ID3_TAG_MAP[frame_type]
            normalized[norm_key] = _serialize_value(value)

    # Filter to only canonical tags + nom:*
    filtered: dict[str, str] = {}
    for key, value in normalized.items():
        if key.startswith("nom:") or key in CANONICAL_TAGS:
            filtered[key] = value

    return filtered


def normalize_vorbis_tags(tags: Any) -> dict[str, str]:
    """
    Normalize Vorbis comments to canonical tag names only.

    Only keeps canonical tags and nom:* namespaced tags.
    Drops cover art (METADATA_BLOCK_PICTURE), lyrics, and other non-canonical fields.

    Vorbis tags written as "nom:mood-strict" are stored as "NOM_MOOD_STRICT"
    (uppercase with underscores). This function converts them back to "nom:mood-strict".

    Args:
        tags: Vorbis comments dict-like object from mutagen (FLAC, Ogg, etc.)

    Returns:
        Dict with canonical tag names and serialized values (+ nom:* tags)
    """
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        # Vorbis comments are case-insensitive
        key_upper = key.upper()

        # Skip picture/cover art fields (binary data)
        if key_upper in ("METADATA_BLOCK_PICTURE", "COVERART", "COVERARTMIME"):
            continue

        # Check if this is a namespaced tag (e.g., "NOM_MOOD_STRICT")
        # Convert back to "nom:mood-strict" format
        if key_upper.startswith("NOM_"):
            # Convert NOM_MOOD_STRICT -> nom:mood-strict
            normalized_key = "nom:" + key[4:].lower().replace("_", "-")
            normalized[normalized_key] = _serialize_value(value)
            continue

        # Keep nom:* namespaced tags if they're already in colon format (rare)
        if key.lower().startswith("nom:"):
            normalized[key] = _serialize_value(value)
            continue

        # Map standard Vorbis fields to canonical names
        if key_upper in VORBIS_TAG_MAP:
            norm_key = VORBIS_TAG_MAP[key_upper]
            normalized[norm_key] = _serialize_value(value)

    # Filter to only canonical tags + nom:*
    filtered: dict[str, str] = {}
    for key, value in normalized.items():
        if key.startswith("nom:") or key in CANONICAL_TAGS:
            filtered[key] = value

    return filtered


def _serialize_value(value: Any) -> str:
    """
    Serialize a tag value to string.

    Handles various mutagen types:
    - MP4FreeForm: Extract bytes and decode
    - Lists: Serialize as JSON array for structured data (moods, etc.)
    - Tuples (MP4 track/disc): Format as "N/total"
    - Bytes: Decode to UTF-8
    - Everything else: str()

    Args:
        value: Tag value from mutagen

    Returns:
        String representation (JSON for multi-value lists)
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
        # For multi-value lists, serialize as JSON array (enables individual value tracking)
        decoded_items = [
            item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item) for item in value
        ]
        return json.dumps(decoded_items, ensure_ascii=False)

    # Handle bytes directly
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    # Handle ID3 text frames (have .text attribute) - exclude tuples
    if not isinstance(value, tuple) and hasattr(value, "text"):
        text_value = value.text
        if isinstance(text_value, list):
            return "; ".join(str(t) for t in text_value) if text_value else ""
        return str(text_value)

    # Everything else
    return str(value) if value is not None else ""
