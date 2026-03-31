#!/usr/bin/env python3
"""
inject_context.py - Output file contents for agent SessionStart hook injection.

Usage:
    python inject_context.py <file1> [file2 ...]

Each file is printed with a markdown header block, suitable for injection as
context via a VS Code Copilot agent SessionStart hook command.

Example agent hook:
    hooks:
      SessionStart:
        - type: command
          command: "python .github/scripts/inject_context.py plans/my-plan.md .github/instructions/layer.instructions.md"
"""

import sys
from pathlib import Path


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        print("Usage: inject_context.py <file1> [file2 ...]", file=sys.stderr)
        sys.exit(1)

    for raw in paths:
        path = Path(raw)
        print(f"\n\n--- {path} ---\n")
        if not path.exists():
            print(f"[File not found: {path}]")
            continue
        print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
