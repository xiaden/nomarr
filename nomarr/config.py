#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Config (compatibility layer)
#  - Thin wrapper around ConfigService for backward compatibility
#  - Use ConfigService directly in new code
# ======================================================================

from __future__ import annotations

from typing import Any

from nomarr.services.config import ConfigService

# Global service instance
_config_service = ConfigService()


# ----------------------------------------------------------------------
# Backward compatibility functions
# ----------------------------------------------------------------------
def compose(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    DEPRECATED: Use ConfigService.get_config() instead.

    Load final configuration from:
      1) Built-in defaults
      2) /etc/nomarr/config.yaml  (if present)
      3) /app/config/config.yaml or ./config/config.yaml
      4) $CONFIG_PATH (if set)
      5) overrides dict passed in
      6) Environment variables (TAGGER_* / NOMARR_TAGGER_*)
      7) Database meta table (config_* keys, user customizations via web UI)

    Returns merged config as dict.
    """
    if overrides:
        # If overrides provided, bypass cache and compose fresh
        return _config_service._compose(overrides)
    return _config_service.get_config()


def get(key_path: str, default: Any = None) -> Any:
    """
    DEPRECATED: Use ConfigService.get() instead.

    Convenience getter using dotted path, e.g. get("namespace")
    """
    return _config_service.get(key_path, default)
