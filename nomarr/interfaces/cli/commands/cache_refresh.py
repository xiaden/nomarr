"""
Cache-refresh command: Rebuild predictor cache via API.
"""

from __future__ import annotations

import argparse

from nomarr.interfaces.cli.ui import InfoPanel, print_error
from nomarr.interfaces.cli.utils import api_call


def cmd_cache_refresh(args: argparse.Namespace) -> int:
    """Rebuild predictor cache via API."""
    try:
        res = api_call("/admin/cache/refresh", method="POST")
        count = res.get("predictors")
        InfoPanel.show("Cache Refresh", f"Predictors loaded: {count}", "green")
        return 0
    except Exception as e:
        print_error(str(e))
        return 1
