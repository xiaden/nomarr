"""ArangoDB first-run provisioning component.

This module handles FIRST-RUN ONLY privileged operations:
  - Create database
  - Create app user with generated password
  - Grant permissions
  - Write to persistent config

CRITICAL INVARIANTS:
  1. Only runs when explicitly triggered by first-run detection
  2. Root password from environment NEVER stored in app config
  3. App generates strong random password for itself
  4. Privileged access is a one-way door (cannot be re-entered)

This is not "lazy provisioning" - it's explicit onboarding.
"""

import os
import secrets
from pathlib import Path

from arango import ArangoClient

# Hardcoded credentials (not user-configurable)
USERNAME = "nomarr"
DB_NAME = "nomarr"


def provision_database_and_user(
    hosts: str,
    root_password: str,
) -> str:
    """Provision database and user (first-run only).

    Creates database, generates random password for app user, grants permissions.

    SECURITY:
    - root_password is read from environment (ARANGO_ROOT_PASSWORD)
    - root_password is NEVER stored in app config
    - App password is randomly generated (64-char hex)
    - This function should only be called once during first boot

    Note: Username and db_name are hardcoded as 'nomarr' (not configurable).

    Args:
        hosts: ArangoDB server URL(s)
        root_password: Root password from environment variable

    Returns:
        Generated app password (caller must store in config)

    Raises:
        ServerConnectionError: Cannot connect to ArangoDB
        DatabaseCreateError: Database creation failed
        UserCreateError: User creation failed
    """
    client = ArangoClient(hosts=hosts)
    sys_db = client.db("_system", username="root", password=root_password)

    # Create database (hardcoded name)
    if not sys_db.has_database(DB_NAME):
        sys_db.create_database(DB_NAME)

    # Generate strong random password for app user
    app_password = secrets.token_hex(32)  # 64-character hex string

    # Create user with generated password (hardcoded username)
    if not sys_db.has_user(USERNAME):
        sys_db.create_user(
            username=USERNAME,
            password=app_password,
            active=True,
        )
    else:
        # User exists, update password
        sys_db.update_user(username=USERNAME, password=app_password)

    # Grant permissions
    sys_db.update_permission(
        username=USERNAME,
        permission="rw",  # Read-write access
        database=DB_NAME,
    )

    return app_password


def is_first_run(config_path: Path, hosts: str | None = None) -> bool:
    """Check if this is first run (no config exists, no DB credentials, or DB missing).

    Args:
        config_path: Path to config file (e.g., /app/config/nomarr.yaml)
        hosts: ArangoDB server URL(s). Read from ARANGO_HOST env var if not provided.

    Returns:
        True if first run needed, False if already configured AND database exists
    """
    if not config_path.exists():
        return True

    # Check if config has ArangoDB credentials
    if not _has_db_config(config_path):
        return True

    # Config exists with password - verify database actually exists
    # (handles case where DB was reset but config still has old password)
    return not _database_exists(hosts)


def _has_db_config(config_path: Path) -> bool:
    """Check if config file has ArangoDB password (the only required field).

    Username and db_name are hardcoded as 'nomarr', so only password matters.
    """
    import yaml

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Only password is required - username/db_name are hardcoded
        return bool(config.get("arango_password"))
    except Exception:
        return False


def _wait_for_arango(hosts: str, max_attempts: int = 30, delay_s: float = 2.0) -> bool:
    """Wait for ArangoDB to become available.

    Args:
        hosts: ArangoDB server URL(s)
        max_attempts: Maximum connection attempts (default 30 = 60 seconds)
        delay_s: Delay between attempts in seconds

    Returns:
        True if connected, False if timeout
    """
    import logging
    import time

    root_password = os.getenv("ARANGO_ROOT_PASSWORD")
    if not root_password:
        logging.debug("ARANGO_ROOT_PASSWORD not set, skipping connection wait")
        return True

    for attempt in range(1, max_attempts + 1):
        try:
            client = ArangoClient(hosts=hosts)
            sys_db = client.db("_system", username="root", password=root_password)
            # Simple connectivity check
            sys_db.properties()
            logging.info(f"ArangoDB connection established (attempt {attempt}/{max_attempts})")
            return True
        except Exception as e:
            if attempt < max_attempts:
                logging.info(f"Waiting for ArangoDB... ({attempt}/{max_attempts}): {e}")
                time.sleep(delay_s)
            else:
                logging.error(f"ArangoDB connection timeout after {max_attempts} attempts: {e}")
                return False
    return False


def _database_exists(hosts: str | None = None) -> bool:
    """Check if the 'nomarr' database exists in ArangoDB.

    Uses root credentials from environment to check system database.
    This handles the case where the DB volume was reset but config still has old password.

    Args:
        hosts: ArangoDB server URL(s). Read from ARANGO_HOST env var if not provided.

    Returns:
        True if database exists, False otherwise (including connection errors)
    """
    import logging

    # actual_hosts is always a str: either `hosts` (if str), or getenv with default
    actual_hosts: str = hosts or os.getenv("ARANGO_HOST") or "http://nomarr-arangodb:8529"

    # Wait for ArangoDB to be ready before checking
    if not _wait_for_arango(actual_hosts):
        logging.error("Cannot check database existence - ArangoDB not available")
        return False

    try:
        root_password = os.getenv("ARANGO_ROOT_PASSWORD")
        if not root_password:
            # Can't check without root password - assume DB exists
            # (will fail later with clear error if it doesn't)
            logging.debug("ARANGO_ROOT_PASSWORD not set, skipping database existence check")
            return True

        client = ArangoClient(hosts=actual_hosts)
        sys_db = client.db("_system", username="root", password=root_password)
        return bool(sys_db.has_database(DB_NAME))
    except Exception as e:
        # Connection error or auth failure - assume needs provisioning
        logging.warning(f"Database existence check failed: {e}")
        return False


def write_db_config(
    config_path: Path,
    password: str,
) -> None:
    """Write auto-generated ArangoDB password to config file.

    Creates/updates config with generated app password.
    NEVER writes root password.

    Note:
        - Only the password is written here (auto-generated secret)
        - Host comes from ARANGO_HOST environment variable (set in nomarr.env)
        - Username and db_name are hardcoded as 'nomarr' (not configurable)

    Args:
        config_path: Path to config file (e.g., /app/config/nomarr.yaml)
        password: Generated app password (from provision_database_and_user)
    """
    import yaml

    # Load existing config or create new
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # Only write the auto-generated password
    # Host comes from ARANGO_HOST env var, not config file
    config["arango_password"] = password

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write config
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_root_password_from_env() -> str:
    """Get root password from environment variable.

    Returns:
        Root password from ARANGO_ROOT_PASSWORD env var

    Raises:
        RuntimeError: If ARANGO_ROOT_PASSWORD not set
    """
    root_password = os.getenv("ARANGO_ROOT_PASSWORD")
    if not root_password:
        raise RuntimeError(
            "ARANGO_ROOT_PASSWORD environment variable not set. "
            "First-run provisioning requires root access to create database and user."
        )
    return root_password
