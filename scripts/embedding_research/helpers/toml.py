"""TOML configuration loader shared across the embedding-research package.

Both ``strategy_binned`` and ``run`` previously duplicated the logic for loading
``research_config.toml``.  This module is the single canonical implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "research_config.toml"


def load_research_config() -> dict:
    """Load ``research_config.toml``; return ``{}`` if missing or unparseable.

    Tries the stdlib ``tomllib`` (Python 3.11+) first, then the third-party
    ``tomli`` drop-in.  Logs a warning and returns an empty dict when neither
    is available.
    """
    if not _CONFIG_PATH.exists():
        return {}
    if sys.version_info >= (3, 11):
        import tomllib

        with open(_CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    try:
        import tomli  # type: ignore[import]

        with open(_CONFIG_PATH, "rb") as f:
            return tomli.load(f)
    except ImportError:
        import logging

        logging.getLogger(__name__).warning(
            "research_config.toml found but tomllib/tomli not available; using defaults"
        )
        return {}
