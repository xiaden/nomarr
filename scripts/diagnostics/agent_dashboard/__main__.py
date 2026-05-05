"""CLI entry point — python -m scripts.diagnostics.agent_dashboard"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .parser import parse_session
from .serializer import write_json


def _find_logs_dir() -> Path | None:
    """Auto-detect the debug-logs directory."""
    base = Path.home() / "AppData" / "Roaming" / "Code" / "User" / "workspaceStorage"
    if not base.exists():
        return None

    candidates: list[Path] = []
    for ws_dir in base.iterdir():
        if not ws_dir.is_dir():
            continue
        logs_dir = ws_dir / "GitHub.copilot-chat" / "debug-logs"
        if logs_dir.exists():
            candidates.append(logs_dir)

    if not candidates:
        return None

    best = None
    best_mtime = 0.0
    for d in candidates:
        for child in d.iterdir():
            if child.is_dir() and (child / "main.jsonl").exists():
                mt = (child / "main.jsonl").stat().st_mtime
                if mt > best_mtime:
                    best_mtime = mt
                    best = d
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Performance Dashboard")
    parser.add_argument("--logs-dir", type=Path, help="Path to debug-logs directory")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: auto based on --format)",
    )
    parser.add_argument(
        "--sessions",
        type=int,
        default=0,
        help="Max sessions to analyze (0 = all)",
    )
    args = parser.parse_args()

    logs_dir = args.logs_dir
    if logs_dir is None:
        logs_dir = _find_logs_dir()
        if logs_dir is None:
            print("ERROR: Could not auto-detect debug-logs directory. Use --logs-dir.", file=sys.stderr)
            sys.exit(1)

    print(f"Scanning: {logs_dir}")

    session_dirs = sorted(
        [
            d
            for d in logs_dir.iterdir()
            if d.is_dir() and not d.name.startswith("toolu_") and (d / "main.jsonl").exists()
        ],
        key=lambda d: (d / "main.jsonl").stat().st_mtime,
        reverse=True,
    )

    if args.sessions > 0:
        session_dirs = session_dirs[: args.sessions]

    print(f"Found {len(session_dirs)} sessions")

    sessions = []
    for sd in session_dirs:
        try:
            session = parse_session(sd)
            if session and session.root:
                sessions.append(session)
        except Exception as e:
            print(f"  WARN: Failed to parse {sd.name}: {e}", file=sys.stderr)

    if not sessions:
        print("ERROR: No valid sessions found.", file=sys.stderr)
        sys.exit(1)

    out_dir = Path("scripts/diagnostics/outputs")
    json_path = args.output or out_dir / "agent_dashboard.json"
    write_json(sessions, json_path)


if __name__ == "__main__":
    main()
