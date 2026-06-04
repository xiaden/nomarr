"""TOML configuration loader shared across the embedding-research package.

Both ``strategy_binned`` and ``run`` previously duplicated the logic for loading
``research_config.toml``.  This module is the single canonical implementation.
"""

from __future__ import annotations

import logging
from functools import cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "research_config.toml"
_LOG = logging.getLogger(__name__)


@cache
def load_research_config() -> dict:
    """Load ``research_config.toml``; return ``{}`` if missing or unparseable.

    Tries the stdlib ``tomllib`` (Python 3.11+) first, then the third-party
    ``tomli`` drop-in.  Logs a warning and returns an empty dict when neither
    is available.
    """
    if not _CONFIG_PATH.exists():
        return {}

    try:
        import tomllib

        with open(_CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass
    except Exception as exc:
        _LOG.warning("research_config.toml failed to parse with tomllib; using defaults (%s)", exc)
        return {}

    try:
        import tomli  # type: ignore[import]

        with open(_CONFIG_PATH, "rb") as f:
            return tomli.load(f)
    except ImportError:
        _LOG.warning("research_config.toml found but tomllib/tomli not available; using defaults")
        return {}
    except Exception as exc:
        _LOG.warning("research_config.toml failed to parse with tomli; using defaults (%s)", exc)
        return {}


@cache
def load_research_config_bytes() -> bytes:
    """Return raw bytes of research_config.toml (used for config hashing)."""
    if not _CONFIG_PATH.exists():
        return b""
    return _CONFIG_PATH.read_bytes()
