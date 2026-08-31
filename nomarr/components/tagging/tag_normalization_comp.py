"""Cross-format tag normalization — MP4 atoms, ID3 frames, Vorbis comments."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    "isrc",
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

# Freeform iTunes tags mapping (used when tag format includes ----:com.apple.iTunes:)
MP4_FREEFORM_MAP: dict[str, str] = {
    "ARTISTS": "artists",
    "ISRC": "isrc",
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

# ID3 frame types to canonical tag names
ID3_TAG_MAP: dict[str, str] = {
    "TIT2": "title",
    "TPE1": "artist",
    "TALB": "album",
    "TPE2": "album_artist",
    "TCON": "genre",
    "TDRC": "date",
    "TYER": "year",
    "TRCK": "tracknumber",
    "TPOS": "discnumber",
    "TCOM": "composer",
    "TEXT": "lyricist",
    "TPUB": "publisher",
    "TBPM": "bpm",
    "TSRC": "isrc",
}

# TXXX-frame to canonical mappings (case-insensitive keys)
ID3_TXXX_MAP: dict[str, str] = {
    "ARTISTS": "artists",
    "artists": "artists",
    "LABEL": "label",
    "label": "label",
    "ORIGINALDATE": "date",
    "LYRICIST": "lyricist",
}

# Vorbis comment to canonical tag names (uppercase keys)
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
    "ISRC": "isrc",
}


def normalize_mp4_tags(tags: Mapping[str, object]) -> dict[str, str]:
    """Normalize MP4 tags to canonical names; drops non-canonical atoms."""
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        if key == "covr":
            continue

        if isinstance(key, str) and key.startswith("----:com.apple.iTunes:"):
            tag_name = key.replace("----:com.apple.iTunes:", "")

            if tag_name.startswith("nom:"):
                normalized[tag_name] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)
                continue

            if tag_name in MP4_FREEFORM_BLOCKLIST:
                continue

            if tag_name.startswith(("ab:", "z_")):
                continue

            if tag_name in MP4_FREEFORM_MAP:
                norm_key = MP4_FREEFORM_MAP[tag_name]
                normalized[norm_key] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)

            continue

        if key in MP4_TAG_MAP:
            norm_key = MP4_TAG_MAP[key]
            normalized[norm_key] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)

    return {k: v for k, v in normalized.items() if k.startswith("nom:") or k in CANONICAL_TAGS}


def normalize_id3_tags(tags: Mapping[str, object]) -> dict[str, str]:
    """Normalize ID3 tags to canonical names; drops non-canonical frames."""
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        if isinstance(key, str) and key.startswith("TXXX:"):
            tag_name = key[5:]  # Remove "TXXX:" prefix

            if tag_name.startswith("nom:"):
                normalized[tag_name] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)
                continue

            tag_name_upper = tag_name.upper()
            if tag_name_upper in ID3_TXXX_MAP:
                norm_key = ID3_TXXX_MAP[tag_name_upper]
                normalized[norm_key] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)

            continue

        frame_type = key[:4] if isinstance(key, str) and len(key) >= 4 else key
        if frame_type in ("APIC", "GEOB", "USLT", "SYLT"):
            continue

        if frame_type in ID3_TAG_MAP:
            norm_key = ID3_TAG_MAP[frame_type]
            normalized[norm_key] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)

    return {k: v for k, v in normalized.items() if k.startswith("nom:") or k in CANONICAL_TAGS}


def normalize_vorbis_tags(tags: Mapping[str, object]) -> dict[str, str]:
    """Normalize Vorbis comments to canonical names; drops non-canonical fields."""
    normalized: dict[str, str] = {}

    for key, value in tags.items():
        key_upper = key.upper()

        if key_upper in ("METADATA_BLOCK_PICTURE", "COVERART", "COVERARTMIME"):
            continue

        if key_upper.startswith("NOM_"):
            normalized_key = "nom:" + key[4:].lower().replace("_", "-")
            normalized[normalized_key] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)
            continue

        if key.lower().startswith("nom:"):
            normalized[key] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)
            continue

        if key_upper in VORBIS_TAG_MAP:
            norm_key = VORBIS_TAG_MAP[key_upper]
            normalized[norm_key] = json.dumps(_extract_tag_strings(value), ensure_ascii=False)

    return {k: v for k, v in normalized.items() if k.startswith("nom:") or k in CANONICAL_TAGS}


def _extract_tag_strings(value: object) -> list[str]:
    """Extract string values from a mutagen tag value, always returning a list.

    Handles MP4FreeForm bytes, ID3 text frames, list values, and MP4 track/disc tuples.
    """
    if isinstance(value, tuple) and len(value) >= 2 and all(isinstance(x, int) for x in value[:2]):
        return [f"{value[0]}/{value[1]}" if value[1] > 0 else str(value[0])]

    if isinstance(value, list):
        if len(value) == 0:
            return []
        return [item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item) for item in value]

    if isinstance(value, bytes):
        return [value.decode("utf-8", errors="replace")]

    if not isinstance(value, tuple) and hasattr(value, "text"):
        text_value = value.text
        if isinstance(text_value, list):
            return [str(t) for t in text_value] if text_value else []
        return [str(text_value)]

    return [str(value)] if value is not None else []
