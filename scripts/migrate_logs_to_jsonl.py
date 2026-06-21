"""Migrate .log.md files to .log.jsonl format.

Reads each markdown log using the legacy log_md parser, writes entries to
the corresponding JSONL file, then deletes the markdown file.

Run from the repo root:
    python scripts/migrate_logs_to_jsonl.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without package install
REPO_ROOT = Path(__file__).parent.parent
CODE_INTEL_SRC = REPO_ROOT / "code-intel" / "src"
sys.path.insert(0, str(CODE_INTEL_SRC))

from mcp_code_intel.helpers.log_jsonl import (  # noqa: E402
    LogEntry,
    append_entry,
    next_entry_id,
)
from mcp_code_intel.helpers.log_md import LOGS_DIR, parse_log  # noqa: E402

LOGS_PATH = REPO_ROOT / LOGS_DIR


def migrate_file(md_file: Path) -> int:
    """Migrate one .log.md file. Returns number of entries migrated."""
    agent = md_file.stem.removesuffix(".log")
    jsonl_file = md_file.parent / f"{agent}.log.jsonl"

    try:
        markdown = md_file.read_text(encoding="utf-8")
        log = parse_log(markdown)
    except (ValueError, OSError) as exc:
        print(f"  SKIP {md_file.name}: parse error — {exc}")
        return 0

    if not log.entries:
        print(f"  SKIP {md_file.name}: no entries")
        md_file.unlink()
        return 0

    count = 0
    # Determine starting ID offset from any existing JSONL content
    existing_max = 0
    if jsonl_file.exists():
        id_str = next_entry_id(jsonl_file)  # returns "L{n+1}"
        existing_max = int(id_str[1:]) - 1

    for entry in log.entries:
        # Normalise timestamp: ensure UTC Z suffix; use epoch for missing dates
        raw_date = entry.date or ""
        if not raw_date:
            ts = "1970-01-01T00:00:00Z"
        elif raw_date.endswith("Z"):
            ts = raw_date
        else:
            ts = raw_date + "Z"

        # Re-number to avoid collisions when appending to existing JSONL
        new_id = f"L{existing_max + count + 1}"

        jsonl_entry = LogEntry(
            id=new_id,
            ts=ts,
            category=entry.category,
            title=entry.title,
            tags=entry.tags,
            body=entry.body,
        )
        append_entry(jsonl_file, jsonl_entry)
        count += 1

    md_file.unlink()
    print(f"  OK  {md_file.name} → {jsonl_file.name}  ({count} entries)")
    return count


def main() -> None:
    md_files = sorted(LOGS_PATH.glob("*.log.md"))
    if not md_files:
        print("No .log.md files found — nothing to migrate.")
        return

    total_entries = 0
    total_files = 0
    for md_file in md_files:
        n = migrate_file(md_file)
        total_entries += n
        total_files += 1

    print(f"\nDone. Migrated {total_entries} entries across {total_files} files.")


if __name__ == "__main__":
    main()
