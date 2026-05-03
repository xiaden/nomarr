"""Compare mood tags on disk (essentia-tensorflow era) vs database (ONNX).

Queries the database for all songs with nom:mood-* tags, reads each file
with mutagen to extract the same tags, then reports matches/mismatches.

Run inside container:
    python3 /tmp/compare_mood_tags.py [--limit N] [--show-matches]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import mutagen
import mutagen.flac
import mutagen.id3
import mutagen.mp3
import mutagen.mp4
import mutagen.oggvorbis
import requests

ARANGO_URL = "http://nomarr-arangodb:8529/_db/nomarr/_api/cursor"
ARANGO_AUTH = ("root", "nomarr_dev_password")

MOOD_TIER_RELS = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _aql(query: str, bind_vars: dict | None = None, batch_size: int = 10000) -> list:
    payload: dict = {"query": query, "batchSize": batch_size}
    if bind_vars:
        payload["bindVars"] = bind_vars
    results = []
    resp = requests.post(ARANGO_URL, json=payload, auth=ARANGO_AUTH, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    results.extend(data["result"])
    cursor_id = data.get("id")
    while data.get("hasMore") and cursor_id:
        data = requests.put(
            f"{ARANGO_URL}/{cursor_id}",
            auth=ARANGO_AUTH,
            timeout=120,
        ).json()
        results.extend(data["result"])
    return results


def load_db_mood_tags(limit: int | None) -> dict[str, dict[str, list[str]]]:
    """Return {file_path: {tier_name: [mood_label, ...]}} for all files with mood tags."""
    # Step 1: get distinct file IDs that have any mood tag (limit applies here = per file)
    limit_clause = f"LIMIT {limit}" if limit else ""
    file_rows = _aql(f"""
        FOR e IN song_has_tags
          LET tag = DOCUMENT(e._to)
          FILTER tag.rel IN ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"]
          COLLECT file_id = e._from
          {limit_clause}
          RETURN file_id
    """)

    if not file_rows:
        return {}

    # Step 2: fetch all mood edges for those files
    rows = _aql("""
        FOR file_id IN @file_ids
          FOR e IN song_has_tags
            FILTER e._from == file_id
            LET tag = DOCUMENT(e._to)
            FILTER tag.rel IN ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"]
            LET file = DOCUMENT(file_id)
            FILTER file != null
            COLLECT file_path = file.path, tier = tag.rel INTO groups
            RETURN {
              path: file_path,
              tier: tier,
              values: groups[*].tag.value
            }
    """, {"file_ids": file_rows})

    result: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        result[row["path"]][row["tier"]] = row["values"]

    return {k: dict(v) for k, v in result.items()}


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
    except Exception as exc:
        print(f"  [read error] {exc}")
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
    total = len(db_tags)
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
        file_tiers, all_keys = result
        if not file_tiers:
            no_file_tags_count += 1
            print(f"\nNO MOOD TAGS ON DISK  {path}")
            print(f"  All tag keys ({len(all_keys)}): {sorted(all_keys)}")
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
                print(f"  MATCH  {Path(path).name}")
                for t, l in sorted(db_set):
                    print(f"         {t}: {l}")
        else:
            mismatch_count += 1
            only_in_db = db_set - file_set
            only_in_file = file_set - db_set
            for tier, _ in only_in_db | only_in_file:
                tier_mismatch[tier] += 1
            print(f"\nMISMATCH  {path}")
            for tier in MOOD_TIER_RELS:
                added = sorted(l for t, l in only_in_db if t == tier)
                removed = sorted(l for t, l in only_in_file if t == tier)
                if added or removed:
                    tier_short = tier.replace("nom:mood-", "")
                    parts = []
                    if added:
                        parts.append(f"+db: {', '.join(added)}")
                    if removed:
                        parts.append(f"-db: {', '.join(removed)}")
                    print(f"  {tier_short:<8} {' | '.join(parts)}")

    print("\n" + "=" * 60)
    print(f"Total files with DB mood tags : {total}")
    print(f"  File not found / unreadable  : {file_missing_count}")
    print(f"  No mood tags on disk         : {no_file_tags_count}")
    print(f"  Match                        : {match_count}")
    print(f"  Mismatch                     : {mismatch_count}")
    if mismatch_count:
        print("\nMismatches by tier:")
        for tier in MOOD_TIER_RELS:
            print(f"  {tier}: {tier_mismatch.get(tier, 0)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Compare on-disk vs DB mood tags")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of files sampled (default: all)")
    parser.add_argument("--show-matches", action="store_true",
                        help="Also print matching files")
    args = parser.parse_args()

    print("Loading DB mood tags...", flush=True)
    db_tags = load_db_mood_tags(args.limit)
    print(f"  Found {len(db_tags)} files with mood tags in DB", flush=True)

    if not db_tags:
        print("No mood tags in DB — run calibration first.")
        sys.exit(0)

    print("Comparing against files on disk...\n", flush=True)
    compare(db_tags, args.show_matches)


if __name__ == "__main__":
    main()
