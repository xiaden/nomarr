"""
Cache-refresh command: Rebuild predictor cache.
"""

from __future__ import annotations

import argparse

import nomarr.app as app
from nomarr.interfaces.cli.ui import InfoPanel, print_error
from nomarr.ml.cache import warmup_predictor_cache


def cmd_cache_refresh(args: argparse.Namespace) -> int:
    """Rebuild predictor cache."""
    # Check if Application is running
    if not app.application.is_running():
        print_error("Application is not running. Start the server first.")
        return 1

    try:
        # Warmup the predictor cache
        warmup_predictor_cache()

        InfoPanel.show("Cache Refresh", "Cache warmed successfully", "green")

        return 0
    except Exception as e:
        print_error(f"Error refreshing cache: {e}")
        return 1
