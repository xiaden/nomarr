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

import logging
import os
import secrets
from pathlib import Path

import yaml
from arango import ArangoClient

logger = logging.getLogger(__name__)
USERNAME = "nomarr"
DB_NAME = "nomarr"


def provision_database_and_user(hosts: str, root_password: str) -> str:
    """Provision database and user (first-run only). Creates database, generates random app password, grants permissions."""
    client = ArangoClient(hosts=hosts)
    sys_db = client.db("_system", username="root", password=root_password)
    if not sys_db.has_database(DB_NAME):
        sys_db.create_database(DB_NAME)
    app_password = secrets.token_hex(32)
    if not sys_db.has_user(USERNAME):
        sys_db.create_user(username=USERNAME, password=app_password, active=True)
    else:
        sys_db.update_user(username=USERNAME, password=app_password)
    sys_db.update_permission(username=USERNAME, permission="rw", database=DB_NAME)
    return app_password


def is_first_run(config_path: Path, hosts: str | None = None) -> bool:
    """Check if this is first run (no config exists, no DB credentials, or DB missing)."""
    if not config_path.exists():
        return True
    if not _has_db_config(config_path):
        return True
    return not _database_exists(hosts)


def _has_db_config(config_path: Path) -> bool:
    """Check if config file has ArangoDB password (the only required field).

    Username and db_name are hardcoded as 'nomarr', so only password matters.
    """
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        return bool(config.get("arango_password"))
    except Exception:
        logger.debug("Failed to read DB config from %s — treating as unconfigured", config_path, exc_info=True)
        return False


def _database_exists(hosts: str | None = None) -> bool:
    """Check if the 'nomarr' database exists in ArangoDB."""
    actual_hosts: str = hosts or os.getenv("ARANGO_HOST") or "http://nomarr-arangodb:8529"
    try:
        root_password = os.getenv("ARANGO_ROOT_PASSWORD")
        if not root_password:
            logger.debug("ARANGO_ROOT_PASSWORD not set, skipping database existence check")
            return True
        client = ArangoClient(hosts=actual_hosts)
        sys_db = client.db("_system", username="root", password=root_password)
        return bool(sys_db.has_database(DB_NAME))
    except Exception as e:
        logger.warning(f"Database existence check failed: {e}", exc_info=True)
        return False


def write_db_config(config_path: Path, password: str) -> None:
    """Write auto-generated ArangoDB app password to config file. NEVER writes root password."""
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
    config["arango_password"] = password
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_root_password_from_env() -> str:
    """Get root password from ARANGO_ROOT_PASSWORD environment variable."""
    root_password = os.getenv("ARANGO_ROOT_PASSWORD")
    if not root_password:
        msg = (
            "ARANGO_ROOT_PASSWORD environment variable not set. "
            "First-run provisioning requires root access to create database and user."
        )
        raise RuntimeError(msg)
    return root_password
