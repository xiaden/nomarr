#!/usr/bin/env python3
"""Capture Copilot hook stdin payloads for local schema probing."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    raw = sys.stdin.read()
    parsed: dict | None = None
    try:
        candidate = json.loads(raw) if raw.strip() else {}
        if isinstance(candidate, dict):
            parsed = candidate
    except json.JSONDecodeError:
        parsed = None

    out_path = Path(__file__).resolve().parent / "_probe_payloads.jsonl"
    record = {
        "raw": raw,
        "parsed": parsed,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(json.dumps({"continue": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
