#!/usr/bin/env python3
# ======================================================================
#  Config Service - Configuration loading and caching
#  - Loads config from YAML, env vars, DB meta
#  - Caches composed config for performance
#  - Provides reload() for runtime changes
# ======================================================================

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING, Any

import yaml

from nomarr.helpers.dto.config import GetInternalInfoResult
from nomarr.persistence.db import Database

if TYPE_CHECKING:
    from nomarr.helpers.dto.processing import ProcessorConfig


# ======================================================================
# Nomarr Version (for tag versioning)
# ======================================================================
# Imported at module level so it's accessible as config.TAGGER_VERSION
# without needing to load from __version__ at runtime
try:
    from nomarr.__version__ import __version__

    TAGGER_VERSION: str = __version__
except ImportError:  # pragma: no cover
    TAGGER_VERSION = "unknown"


# ======================================================================
# Internal Constants (Not User-Configurable)
# ======================================================================
# These values control internal Nomarr behavior and are not exposed
# in config.yaml or environment variables. They represent operational
# parameters that users should not need to adjust.

# Tag namespace and versioning
INTERNAL_NAMESPACE = "nom"
INTERNAL_VERSION_TAG = "nom_version"

# Audio processing parameters
INTERNAL_MIN_DURATION_S = 60  # Skip tracks shorter than 60s
INTERNAL_BATCH_SIZE = 11  # Patches per batch for head inference
INTERNAL_ALLOW_SHORT = False  # Don't process files < min_duration

# API and worker settings
INTERNAL_HOST = "0.0.0.0"
INTERNAL_PORT = 8356
INTERNAL_POLL_INTERVAL = 2  # Worker queue check interval (seconds)
INTERNAL_WORKER_ENABLED = True  # Start worker on startup

# Library scanner settings
INTERNAL_LIBRARY_SCAN_POLL_INTERVAL = 10  # Library scanner poll interval (seconds)

# Calibration automation settings
INTERNAL_CALIBRATION_AUTO_RUN = False  # Auto-trigger calibration
INTERNAL_CALIBRATION_MIN_FILES = 100  # Min files before auto-calibration
INTERNAL_CALIBRATION_CHECK_INTERVAL = 604800  # 1 week between checks
INTERNAL_CALIBRATION_QUALITY_THRESHOLD = 0.85  # Don't recalibrate if quality > this

# Calibration drift thresholds
INTERNAL_CALIBRATION_APD_THRESHOLD = 0.01  # Max absolute percentile drift (1%)
INTERNAL_CALIBRATION_SRD_THRESHOLD = 0.05  # Max scale range drift (5%)
INTERNAL_CALIBRATION_JSD_THRESHOLD = 0.1  # Max Jensen-Shannon divergence
INTERNAL_CALIBRATION_MEDIAN_THRESHOLD = 0.05  # Max median drift (5%)
INTERNAL_CALIBRATION_IQR_THRESHOLD = 0.1  # Max IQR drift (10%)


class ConfigService:
    """
    Service for loading and caching application configuration.

    Loads config from multiple sources (defaults → YAML → env → DB),
    caches the result, and provides reload capability.

    This is a service because it:
    - Answers questions about configuration
    - Is long-lived (cached state)
    - Can reload when needed (runtime changes)
    """

    def __init__(self) -> None:
        """Initialize ConfigService with empty cache."""
        self._config: dict[str, Any] | None = None
        self._logger = logging.getLogger(__name__)

    def get_config(self, force_reload: bool = False) -> dict[str, Any]:
        """
        Get the composed configuration.

        Args:
            force_reload: If True, bypass cache and reload from sources

        Returns:
            Complete configuration dict
        """
        if self._config is None or force_reload:
            self._config = self._compose()
        return self._config

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get a config value by dotted path.

        Args:
            key_path: Dotted path like "namespace" or "worker.poll_interval"
            default: Default value if key not found

        Returns:
            Config value or default

        Example:
            >>> service.get("namespace")
            'essentia'
            >>> service.get("worker.poll_interval", 2)
            2
        """
        cfg = self.get_config()
        node: Any = cfg
        for part in key_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set_config_value(self, key: str, value: str, db_path: str | None = None) -> None:
        """
        Store a user-editable config value in DB meta.

        This persists configuration changes made via web UI. The value is stored
        with a 'config_' prefix and will be picked up on next reload/restart.

        Args:
            key: Config key (without 'config_' prefix)
            value: String value to store
            db_path: Path to database (if None, uses current config's db_path)

        Note:
            Changes take effect after reload() or application restart.
            Caller is responsible for validating that key is editable.
        """
        if db_path is None:
            db_path = self.get("db_path")

        if not db_path:
            raise ValueError("Cannot set config value: no db_path available")

        # Create temporary DB connection for write
        db = Database(db_path)
        db.meta.set(f"config_{key}", value)
        self._logger.info(f"[ConfigService] Set config_{key} = {value}")

    def reload(self) -> dict[str, Any]:
        """
        Force reload configuration from all sources.

        Returns:
            Newly composed config
        """
        self._logger.info("Reloading configuration from all sources")
        return self.get_config(force_reload=True)

    def get_internal_info(self) -> GetInternalInfoResult:
        """
        Get internal (read-only) configuration constants.

        These are operational parameters that are not user-configurable.

        Returns:
            GetInternalInfoResult with internal constant values
        """
        return GetInternalInfoResult(
            namespace=INTERNAL_NAMESPACE,
            version_tag=INTERNAL_VERSION_TAG,
            min_duration_s=INTERNAL_MIN_DURATION_S,
            allow_short=INTERNAL_ALLOW_SHORT,
            poll_interval=INTERNAL_POLL_INTERVAL,
            library_scan_poll_interval=INTERNAL_LIBRARY_SCAN_POLL_INTERVAL,
            worker_enabled=INTERNAL_WORKER_ENABLED,
        )

    # ----------------------------------------------------------------------
    # Private composition logic
    # ----------------------------------------------------------------------

    def _compose(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """
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
        cfg = self._default_config()

        # 1) System-wide YAML
        self._deep_merge(cfg, self._load_yaml("/etc/nomarr/config.yaml"))

        # 1b) Container-mounted or repo-local config (common Docker layout)
        # Prefer /app/config/config.yaml when mounted in containers, then ./config/config.yaml in repo root.
        app_cfg = self._load_yaml("/app/config/config.yaml")
        if app_cfg:
            self._deep_merge(cfg, app_cfg)
        repo_cfg = self._load_yaml(os.path.join(os.getcwd(), "config", "config.yaml"))
        if repo_cfg:
            self._deep_merge(cfg, repo_cfg)

        # 2) Optional path via env
        env_path = os.getenv("CONFIG_PATH")
        if env_path:
            self._deep_merge(cfg, self._load_yaml(env_path))

        # 3) Direct overrides
        if overrides:
            self._deep_merge(cfg, overrides)

        # 4) Environment variable overrides (flat -> nested mapping)
        self._apply_env_overrides(cfg)

        # 5) Database meta table overrides (web UI customizations)
        # Can be disabled via NOMARR_IGNORE_DB_CONFIG=true for recovery
        if os.getenv("NOMARR_IGNORE_DB_CONFIG", "").lower() != "true":
            db_overrides = self._load_db_config(cfg.get("db_path"))
            if db_overrides:
                self._deep_merge(cfg, db_overrides)
        else:
            self._logger.warning("Ignoring DB config (NOMARR_IGNORE_DB_CONFIG=true)")

        # Log effective config source for easier debugging in containers
        with contextlib.suppress(Exception):
            self._logger.debug("compose() loaded config; keys: %s", list(cfg.keys()))

        return cfg

    def _default_config(self) -> dict[str, Any]:
        """
        Base defaults for USER-CONFIGURABLE settings only.

        These 12 keys are the only settings exposed to users via
        config.yaml, environment variables, or database overrides.

        All other operational parameters are internal constants
        defined at module level.
        """
        return {
            # Filesystem paths
            "models_dir": "/app/models",
            "db_path": "/app/config/db/nomarr.db",
            "library_root": "/media",  # Required: music library root for security
            # Tag writing settings
            "file_write_mode": "full",  # "none", "minimal", or "full"
            "overwrite_tags": True,
            # Library scanner settings
            "library_auto_tag": True,
            "library_ignore_patterns": "",
            # Worker settings
            "worker_count": 1,  # Number of parallel ML workers (controls VRAM usage)
            # Calibration settings
            "calibrate_heads": False,
            "calibration_repo": "https://github.com/xiaden/nom-cal",
            # Web UI authentication
            "admin_password": None,  # Optional; auto-generated if not set
            # Model cache settings
            "cache_idle_timeout": 300,  # Seconds before unloading models (0=never)
        }

    def _deep_merge(self, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively merge dict b into dict a (mutates a, returns it).
        """
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                self._deep_merge(a[k], v)
            else:
                a[k] = v
        return a

    def _load_yaml(self, path: str) -> dict[str, Any]:
        """
        Load a YAML file; returns {} if not found or invalid.
        """
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _load_db_config(self, db_path: str | None) -> dict[str, Any]:
        """
        Load configuration overrides from database meta table.

        Only allows overrides for the 11 user-configurable keys.
        All other config_* keys in the DB are ignored (internal constants
        cannot be overridden at runtime).

        Graceful fallback if DB doesn't exist or is corrupted.

        Args:
            db_path: Path to SQLite database (from YAML/env config)

        Returns:
            dict: Config overrides from DB meta table (empty if unavailable)
        """
        # Whitelist of allowed DB config overrides (matches user-facing config)
        ALLOWED_DB_KEYS = {
            "models_dir",
            "db_path",
            "library_root",
            "library_auto_tag",
            "library_ignore_patterns",
            "file_write_mode",
            "overwrite_tags",
            "admin_password",
            "cache_idle_timeout",
            "worker_count",
            "calibrate_heads",
            "calibration_repo",
        }

        if not db_path:
            self._logger.debug("DB config skipped: no db_path provided")
            return {}

        try:
            # Only import DB if path exists (avoids errors during initial setup)
            if not os.path.exists(db_path):
                self._logger.debug(f"DB config skipped: {db_path} does not exist")
                return {}

            db = Database(db_path)
            try:
                # Query all config_* keys from meta table via persistence layer
                meta_dict = db.meta.get_by_prefix("config_")

                if not meta_dict:
                    self._logger.debug("DB config skipped: no config_* keys in meta table")
                    return {}

                config_overrides = {}
                for key, value in meta_dict.items():
                    # Remove 'config_' prefix
                    config_key = key[7:]  # len('config_') == 7

                    # Only allow whitelisted keys
                    if config_key not in ALLOWED_DB_KEYS:
                        self._logger.debug(f"Ignoring DB config for internal key: {config_key}")
                        continue

                    # Parse value to correct type
                    parsed: bool | int | float | str
                    if value.lower() in ("true", "false"):
                        parsed = value.lower() == "true"
                    elif value.isdigit():
                        parsed = int(value)
                    elif value.replace(".", "", 1).replace("-", "", 1).isdigit():
                        parsed = float(value)
                    else:
                        parsed = value

                    config_overrides[config_key] = parsed

                if config_overrides:
                    self._logger.info(f"Loaded {len(config_overrides)} config overrides from database")
                return config_overrides

            finally:
                db.close()

        except Exception as e:
            # Graceful fallback - DB config is optional, YAML/env config continues
            self._logger.warning(f"Failed to load DB config (using YAML/env fallback): {e}")
            return {}

    def _apply_env_overrides(self, cfg: dict[str, Any]) -> None:
        """
        Support environment overrides for the 12 user-configurable keys only.

        Supported formats:
          NOMARR_MODELS_DIR=/custom/path
          NOMARR_DB_PATH=/custom/db.sqlite
          NOMARR_LIBRARY_ROOT=/music
          NOMARR_LIBRARY_AUTO_TAG=true
          NOMARR_LIBRARY_IGNORE_PATTERNS=*.wav,*/Audiobooks/*
          NOMARR_FILE_WRITE_MODE=full
          NOMARR_OVERWRITE_TAGS=false
          NOMARR_ADMIN_PASSWORD=secretpass
          NOMARR_CACHE_IDLE_TIMEOUT=600
          NOMARR_WORKER_COUNT=4
          NOMARR_CALIBRATE_HEADS=true
          NOMARR_CALIBRATION_REPO=https://github.com/user/repo

        Internal constants cannot be overridden via environment.
        """
        # Whitelist of allowed env overrides
        ALLOWED_ENV_KEYS = {
            "models_dir",
            "db_path",
            "library_root",
            "library_auto_tag",
            "library_ignore_patterns",
            "file_write_mode",
            "overwrite_tags",
            "admin_password",
            "cache_idle_timeout",
            "worker_count",
            "calibrate_heads",
            "calibration_repo",
        }

        for k, v in os.environ.items():
            # Support NOMARR_* prefix (primary), TAGGER_* and AUTOTAG_* (legacy)
            if not (k.startswith("NOMARR_") or k.startswith("TAGGER_") or k.startswith("AUTOTAG_")):
                continue

            # Normalize to lowercase key name
            key = k.replace("NOMARR_", "").replace("TAGGER_", "").replace("AUTOTAG_", "").lower()

            # Only allow whitelisted keys
            if key not in ALLOWED_ENV_KEYS:
                self._logger.debug(f"Ignoring environment override for internal key: {key}")
                continue

            try:
                # Parse typed values
                if v.lower() in ("true", "false"):
                    val: Any = v.lower() == "true"
                elif v.isdigit():
                    val = int(v)
                elif v.replace(".", "", 1).replace("-", "", 1).isdigit():
                    val = float(v)
                else:
                    val = v

                cfg[key] = val
            except Exception:
                continue

    def make_processor_config(self) -> ProcessorConfig:
        """
        Build a ProcessorConfig from the current configuration.

        This is the boundary where we extract and validate processor-specific
        settings from the raw config dict, combining user-configurable settings
        with internal constants.

        Returns:
            ProcessorConfig instance ready for injection into process_file()
        """
        from nomarr.helpers.dto.processing import ProcessorConfig

        cfg = self.get_config()

        return ProcessorConfig(
            # User-configurable settings
            models_dir=str(cfg["models_dir"]),
            overwrite_tags=bool(cfg["overwrite_tags"]),
            file_write_mode=str(cfg.get("file_write_mode", "minimal")),  # type: ignore
            calibrate_heads=bool(cfg.get("calibrate_heads", False)),
            # Internal constants (not user-configurable)
            min_duration_s=INTERNAL_MIN_DURATION_S,
            allow_short=INTERNAL_ALLOW_SHORT,
            batch_size=INTERNAL_BATCH_SIZE,
            namespace=INTERNAL_NAMESPACE,
            version_tag_key=INTERNAL_VERSION_TAG,
            tagger_version=TAGGER_VERSION,
        )
