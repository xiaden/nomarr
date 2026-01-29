"""Cache-refresh command: Rebuild predictor cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr import app
from nomarr.interfaces.cli.cli_ui import InfoPanel, print_error

if TYPE_CHECKING:
    import argparse


def cmd_cache_refresh(args: argparse.Namespace) -> int:
    """Rebuild predictor cache."""
    # Check if Application is running
    if not app.application.is_running():
        print_error("Application is not running. Start the server first.")
        return 1

    try:
        # Use ML service from running Application
        ml_service = app.application.services["ml"]
        count = ml_service.warmup_cache()

        InfoPanel.show("Cache Refresh", f"Warmed {count} predictors successfully", "green")

        return 0
    except Exception as e:
        print_error(f"Error refreshing cache: {e}")
        return 1
