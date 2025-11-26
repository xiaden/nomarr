"""
CLI Bootstrap Service - Service Container for CLI Commands

Provides clean DI for CLI commands that need to access services without
requiring the running server application.

Architecture:
- This is a SERVICE layer module (interfaces → services)
- CLI commands should NOT use app.application.services (that's the running server)
- CLI commands should NOT import persistence modules directly
- CLI commands SHOULD use these bootstrap functions to get service instances
- Services are instantiated with proper DI (Database, config, etc.)

This module creates a minimal service container for CLI use cases where the
full Application lifecycle (workers, coordinator, event broker) is not needed.
"""

from __future__ import annotations

import logging

from nomarr.persistence.db import Database
from nomarr.services.config_svc import ConfigService
from nomarr.services.keys_svc import KeyManagementService


def get_database() -> Database:
    """
    Get Database instance for CLI operations.

    Uses ConfigService to get db_path, respecting YAML config and env vars.

    Returns:
        Database instance
    """
    config_service = ConfigService()
    config = config_service.get_config()
    db_path = str(config["db_path"])
    return Database(db_path)


def get_keys_service() -> KeyManagementService:
    """
    Get KeyManagementService instance for CLI operations.

    This is the architecture-compliant way for CLI commands to access
    password/key management functionality.

    Returns:
        KeyManagementService instance with injected Database

    Example:
        >>> from nomarr.services.cli_bootstrap_service import get_keys_service
        >>> service = get_keys_service()
        >>> service.reset_admin_password("newpassword123")
    """
    db = get_database()
    return KeyManagementService(db)


def get_config_service() -> ConfigService:
    """
    Get ConfigService instance for CLI operations.

    Returns:
        ConfigService instance
    """
    return ConfigService()


# Log that bootstrap module is designed for CLI use only
logging.debug("[CLI Bootstrap] Service container initialized for CLI operations")
