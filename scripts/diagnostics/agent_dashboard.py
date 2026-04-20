"""Agent Performance Dashboard — redirects to the agent_dashboard package.

Usage:
    python scripts/diagnostics/agent_dashboard.py [--logs-dir PATH] [--output PATH] [--sessions N]
    python -m scripts.diagnostics.agent_dashboard [--logs-dir PATH] [--output PATH] [--sessions N]
"""

import importlib
import sys
from pathlib import Path

# Ensure the package's parent is on sys.path so the relative import works
_pkg_parent = str(Path(__file__).resolve().parent)
if _pkg_parent not in sys.path:
    sys.path.insert(0, _pkg_parent)

_main_mod = importlib.import_module("agent_dashboard.__main__")

if __name__ == "__main__":
    _main_mod.main()
