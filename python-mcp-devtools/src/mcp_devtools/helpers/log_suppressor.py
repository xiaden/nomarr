"""Logging suppression helper for MCP tools.

Provides a context manager to suppress all logging output during tool execution.
This prevents logs from interfering with MCP's JSON-RPC communication over stdio.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def suppress_logs() -> Iterator[None]:
    """Context manager to suppress all logging during tool execution.

    Temporarily sets all loggers to CRITICAL level and restores them afterward.
    This ensures no log output contaminates MCP's stdout JSON-RPC channel.

    Usage:
        with suppress_logs():
            # Code that might log
            result = some_function_that_logs()
    """
    # Get root logger and all existing loggers
    root_logger = logging.getLogger()
    all_loggers = [root_logger] + [logging.getLogger(name) for name in logging.root.manager.loggerDict]

    # Save current levels
    saved_levels = {logger: logger.level for logger in all_loggers}

    try:
        # Suppress all loggers
        for logger in all_loggers:
            logger.setLevel(logging.CRITICAL + 1)  # Higher than CRITICAL = no output

        yield

    finally:
        # Restore original levels
        for logger, level in saved_levels.items():
            logger.setLevel(level)
