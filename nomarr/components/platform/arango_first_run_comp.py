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


def provision_database_and_user(
    hosts: str,
    root_password: str,
    username: str = "nomarr",
    db_name: str = "nomarr",
) -> str:
    """Provision database and user (first-run only).

    Creates database, generates random password for app user, grants permissions.

    SECURITY:
    - root_password is read from environment (ARANGO_ROOT_PASSWORD)
    - root_password is NEVER stored in app config
    - App password is randomly generated (64-char hex)
    - This function should only be called once during first boot

    Args:
        hosts: ArangoDB server URL(s)
        root_password: Root password from environment variable
        username: App username to create (default: "nomarr")
        db_name: Database name to create (default: "nomarr")

    Returns:
        Generated app password (caller must store in config)

    Raises:
        ServerConnectionError: Cannot connect to ArangoDB
        DatabaseCreateError: Database creation failed
        UserCreateError: User creation failed
    """
    client = ArangoClient(hosts=hosts)
    sys_db = client.db("_system", username="root", password=root_password)

    # Create database
    if not sys_db.has_database(db_name):
        sys_db.create_database(db_name)

    # Generate strong random password for app user
    app_password = secrets.token_hex(32)  # 64-character hex string

    # Create user with generated password
    if not sys_db.has_user(username):
        sys_db.create_user(
            username=username,
            password=app_password,
            active=True,
        )
    else:
        # User exists, update password
        sys_db.update_user(username=username, password=app_password)

    # Grant permissions
    sys_db.update_permission(
        username=username,
        permission="rw",  # Read-write access
        database=db_name,
    )

    return app_password


def is_first_run(config_path: Path) -> bool:
    """Check if this is first run (no config exists or no DB credentials).

    Args:
        config_path: Path to config file (e.g., /app/config/nomarr.yaml)

    Returns:
        True if first run needed, False if already configured
    """
    if not config_path.exists():
        return True

    # Check if config has ArangoDB credentials
    return not _has_db_config(config_path)


def _has_db_config(config_path: Path) -> bool:
    """Check if config file has ArangoDB credentials."""
    import yaml

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Check for required ArangoDB fields
        required_fields = ["arango_hosts", "arango_username", "arango_password", "arango_db_name"]
        return all(config.get(field) for field in required_fields)
    except Exception:
        return False


def write_db_config(
    config_path: Path,
    password: str,
    hosts: str = "http://nomarr-arangodb:8529",
    username: str = "nomarr",
    db_name: str = "nomarr",
) -> None:
    """Write ArangoDB credentials to config file.

    Creates/updates config with generated app credentials.
    NEVER writes root password.

    Args:
        config_path: Path to config file
        password: Generated app password (from provision_database_and_user)
        hosts: ArangoDB server URL(s)
        username: App username
        db_name: Database name
    """
    import yaml

    # Load existing config or create new
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # Update ArangoDB credentials
    config.update(
        {
            "arango_hosts": hosts,
            "arango_username": username,
            "arango_password": password,
            "arango_db_name": db_name,
        }
    )

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
