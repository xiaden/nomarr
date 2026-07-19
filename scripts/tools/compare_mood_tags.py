"""Compare mood tags on disk (essentia-tensorflow era) vs database (ONNX).

Reads each file with mutagen to extract nom:mood-* tags, then reports
the on-disk mood tags found.  Database comparison queries PostgreSQL
via the nomarr persistence layer (PG_DATABASE_URL environment variable).

Run inside container:
    python3 /tmp/compare_mood_tags.py [--limit N] [--show-matches]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import mutagen
import mutagen.flac
import mutagen.id3
import mutagen.mp3
import mutagen.mp4
import mutagen.oggvorbis

MOOD_TIER_RELS = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def load_db_mood_tags(
    db: Database,
    limit: int | None = None,
) -> dict[str, dict[str, list[str]]]:
    """Return {file_path: {tier_name: [mood_label, ...]}} for files with mood tags.

    Queries the PostgreSQL persistence layer: fetches library files,
    then batch-loads nom:mood-* tags via ``list_file_tags_for_files``.

    Args:
        db: A connected ``Database`` instance.
        limit: Optional cap on the number of files sampled from the DB.

    """
    files = db.library.list_files(limit=limit)
    if not files:
        return {}

    file_ids = [f["id"] for f in files]
    path_map: dict[int, str] = {f["id"]: f["path"] for f in files}

    tags_by_file = db.library.list_file_tags_for_files(
        file_ids,
        name_starts_with="nom:mood-",
    )

    result: dict[str, dict[str, list[str]]] = {}
    for file_id, tag_rows in tags_by_file.items():
        if not tag_rows:
            continue
        path = path_map.get(file_id)
        if not path:
            continue
        tiers: dict[str, list[str]] = {}
        for tag in tag_rows:
            tiers.setdefault(tag["name"], []).append(tag["value"])
        result[path] = tiers

    return result


# ---------------------------------------------------------------------------
# File tag reading
# ---------------------------------------------------------------------------


def _extract_nom_mood(tags_raw: dict) -> dict[str, list[str]]:
    """Extract nom:mood-* entries from a normalised tag dict.

    File tags store mood lists as a JSON-encoded string within the tag value
    (e.g. TXXX frame text = '["engaging","mainstream"]'). This unwraps
    any level of JSON encoding to get the raw label strings.

    Returns {tier_name: [mood_label, ...]}
    """

    def _unwrap(val: object) -> list[str]:
        if isinstance(val, list):
            out: list[str] = []
            for item in val:
                out.extend(_unwrap(item))
            return out
        if isinstance(val, str):
            stripped = val.strip()
            if stripped.startswith(("[", "{")):
                try:
                    return _unwrap(json.loads(stripped))
                except json.JSONDecodeError:
                    pass
            # Python tuple repr: "('a', 'b')"
            if stripped.startswith("(") and stripped.endswith(")"):
                inner = stripped[1:-1]
                items = [s.strip().strip("'\"") for s in inner.split(",")]
                return [i for i in items if i]
            return [val]
        return [str(val)]

    result: dict[str, list[str]] = {}
    for key, raw_value in tags_raw.items():
        if not key.startswith("nom:mood-"):
            continue
        labels = _unwrap(raw_value)
        if labels:
            result[key] = labels
    return result


def read_file_mood_tags(path: str) -> tuple[dict[str, list[str]], list[str]] | None:
    """Read nom:mood-* tags from a file on disk.

    Returns (mood_tags, all_tag_keys), or None on read error.
    mood_tags is empty dict when file has no nom:mood- tags.
    all_tag_keys is every raw tag key found in the file (for debugging).
    """
    try:
        audio = mutagen.File(path, easy=False)
    except Exception:
        return None
    if audio is None:
        return None

    tags = audio.tags
    if tags is None:
        return {}, []

    all_keys = list(tags.keys())

    # Detect format and normalise
    raw: dict = {}
    if isinstance(audio, mutagen.mp3.MP3):
        # ID3 — look for TXXX:nom:mood-* frames
        for frame_id, frame in tags.items():
            if frame_id.startswith("TXXX:"):
                desc = frame_id[5:]
                if desc.startswith("nom:mood-"):
                    raw[desc] = json.dumps(list(frame.text))
    elif isinstance(audio, mutagen.mp4.MP4):
        # MP4 freeform atoms ----:com.apple.iTunes:nom:mood-*
        for key, val in tags.items():
            if "nom:mood-" in key:
                # key is e.g. "----:com.apple.iTunes:nom:mood-loose"
                # find the nom:mood-* portion within the key
                idx = key.find("nom:mood-")
                short = key[idx:] if idx != -1 else key
                texts = []
                for item in val:
                    if hasattr(item, "decode"):
                        texts.append(item.decode("utf-8", errors="replace"))
                    elif hasattr(item, "value"):
                        v = item.value
                        texts.append(v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v))
                    else:
                        texts.append(str(item))
                raw[short] = json.dumps(texts)
    else:
        # Vorbis (FLAC, Ogg) — uppercase underscore format
        tag_dict = dict(tags)
        for key, val in tag_dict.items():
            norm_key = key.upper().replace("-", "_").replace(":", "_")
            if norm_key.startswith("NOM_MOOD_"):
                tier_suffix = key.lower().replace("nom_mood_", "")
                tier_rel = f"nom:mood-{tier_suffix}"
                values = val if isinstance(val, list) else [val]
                raw[tier_rel] = json.dumps([str(v) for v in values])

    return _extract_nom_mood(raw), all_keys


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare(
    db_tags: dict[str, dict[str, list[str]]],
    show_matches: bool,
) -> None:
    len(db_tags)
    match_count = 0
    mismatch_count = 0
    file_missing_count = 0
    no_file_tags_count = 0

    tier_mismatch: dict[str, int] = defaultdict(int)

    for path, db_tiers in db_tags.items():
        if not Path(path).exists():
            file_missing_count += 1
            continue

        result = read_file_mood_tags(path)
        if result is None:
            file_missing_count += 1
            continue
        file_tiers, _all_keys = result
        if not file_tiers:
            no_file_tags_count += 1
            continue

        # Normalise both to sets of (tier, label) tuples for comparison
        db_set: set[tuple[str, str]] = set()
        for tier, labels in db_tiers.items():
            for label in labels:
                db_set.add((tier, label))

        file_set: set[tuple[str, str]] = set()
        for tier, labels in file_tiers.items():
            for label in labels:
                file_set.add((tier, label))

        if db_set == file_set:
            match_count += 1
            if show_matches:
                for _t, _l in sorted(db_set):
                    pass
        else:
            mismatch_count += 1
            only_in_db = db_set - file_set
            only_in_file = file_set - db_set
            for tier, _ in only_in_db | only_in_file:
                tier_mismatch[tier] += 1
            for tier in MOOD_TIER_RELS:
                added = sorted(l for t, l in only_in_db if t == tier)
                removed = sorted(l for t, l in only_in_file if t == tier)
                if added or removed:
                    tier.replace("nom:mood-", "")
                    parts = []
                    if added:
                        parts.append(f"+db: {', '.join(added)}")
                    if removed:
                        parts.append(f"-db: {', '.join(removed)}")

    if mismatch_count:
        for tier in MOOD_TIER_RELS:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare on-disk vs DB mood tags")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of files sampled (default: all)")
    parser.add_argument("--show-matches", action="store_true", help="Also print matching files")
    args = parser.parse_args()

    pg_url = os.environ.get("PG_DATABASE_URL")
    if not pg_url:
        sys.exit(1)

    from nomarr.persistence.db import Database

    db = Database(url=pg_url)
    try:
        db_tags = load_db_mood_tags(db, args.limit)

        if not db_tags:
            sys.exit(1)

        compare(db_tags, args.show_matches)
    finally:
        db.close()


if __name__ == "__main__":
    main()
