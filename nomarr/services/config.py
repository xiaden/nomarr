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

from nomarr.__version__ import __version__
from nomarr.persistence.db import Database

if TYPE_CHECKING:
    from nomarr.workflows.processor_config import ProcessorConfig


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

    def reload(self) -> dict[str, Any]:
        """
        Force reload configuration from all sources.

        Returns:
            Newly composed config
        """
        self._logger.info("Reloading configuration from all sources")
        return self.get_config(force_reload=True)

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
        Base defaults; all fields present so no KeyErrors downstream.
        """
        return {
            # Filesystem paths
            "models_dir": "/app/models",
            "db_path": "/app/config/db/essentia.sqlite",
            "library_path": None,  # Optional: path to music library to scan/track
            # Tag writing settings
            "namespace": "essentia",
            "version_tag": "essentia_at_version",
            "tagger_version": __version__,  # Version from nomarr.__version__
            # Audio processing rules
            "min_duration_s": 60,  # Skip tracks shorter than 60s
            "batch_size": 11,  # Batch size for head model inference (patches per batch)
            "allow_short": False,
            "overwrite_tags": True,
            # API and worker settings
            "host": "0.0.0.0",
            "port": 8356,
            "blocking_mode": True,
            "blocking_timeout": 3600,
            "poll_interval": 2,
            "worker_enabled": True,
            # Library scanner settings
            "library_scan_poll_interval": 10,
            "library_auto_tag": True,
            "library_ignore_patterns": "",
            # Calibration settings
            "calibrate_heads": False,
            "calibration_repo": "https://github.com/xiaden/nom-cal",
            "calibration_auto_run": False,
            "calibration_min_files": 100,
            "calibration_check_interval": 604800,
            "calibration_quality_threshold": 0.85,
            # Calibration drift thresholds
            "calibration_apd_threshold": 0.01,
            "calibration_srd_threshold": 0.05,
            "calibration_jsd_threshold": 0.1,
            "calibration_median_threshold": 0.05,
            "calibration_iqr_threshold": 0.1,
            # Web UI authentication
            "admin_password": None,  # Optional; auto-generated if not set
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

        Only loads operational config (worker_count, poll_interval, etc.).
        Infrastructure config (db_path, host, port, models_dir) is YAML/env-only.

        Graceful fallback if DB doesn't exist or is corrupted.

        Args:
            db_path: Path to SQLite database (from YAML/env config)

        Returns:
            dict: Config overrides from DB meta table (empty if unavailable)
        """
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
                # Query all config_* keys from meta table
                cursor = db.conn.execute("SELECT key, value FROM meta WHERE key LIKE 'config_%'")
                rows = cursor.fetchall()

                if not rows:
                    self._logger.debug("DB config skipped: no config_* keys in meta table")
                    return {}

                config_overrides = {}
                for key, value in rows:
                    # Remove 'config_' prefix
                    config_key = key[7:]  # len('config_') == 7

                    # Parse value to correct type
                    if value.lower() in ("true", "false"):
                        parsed = value.lower() == "true"
                    elif value.isdigit():
                        parsed = int(value)
                    elif value.replace(".", "", 1).replace("-", "", 1).isdigit():
                        parsed = float(value)
                    else:
                        parsed = value

                    config_overrides[config_key] = parsed

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
        Support environment overrides of the form:
          TAGGER_NAMESPACE=custom
          TAGGER_VERSION_TAG=build_version
          NOMARR_TAGGER_MIN_DURATION_S=5
        """
        for k, v in os.environ.items():
            if not (k.startswith("TAGGER_") or k.startswith("NOMARR_TAGGER_") or k.startswith("AUTOTAG_")):
                continue

            # Normalize key path
            key = k.replace("NOMARR_", "").replace("AUTOTAG_", "").lower()
            parts = key.split("_", 1)
            if len(parts) == 1:
                continue
            section, field = parts
            if section not in cfg:
                # fallback: tagger-level only
                section = "tagger"

            try:
                # try to parse numeric/bool types
                if v.lower() in ("true", "false"):
                    val: Any = v.lower() == "true"
                elif v.isdigit():
                    val = int(v)
                else:
                    val = v
                if section in cfg and isinstance(cfg[section], dict):
                    cfg[section][field.lower()] = val
            except Exception:
                continue

    def make_processor_config(self) -> ProcessorConfig:
        """
        Build a ProcessorConfig from the current configuration.

        This is the boundary where we extract and validate processor-specific
        settings from the raw config dict.

        Returns:
            ProcessorConfig instance ready for injection into process_file()
        """
        from nomarr.workflows.processor_config import ProcessorConfig

        cfg = self.get_config()

        return ProcessorConfig(
            models_dir=str(cfg["models_dir"]),
            min_duration_s=int(cfg["min_duration_s"]),
            allow_short=bool(cfg["allow_short"]),
            batch_size=int(cfg.get("batch_size", 11)),
            overwrite_tags=bool(cfg["overwrite_tags"]),
            namespace=str(cfg["namespace"]),
            version_tag_key=str(cfg["version_tag"]),
            tagger_version=str(cfg["tagger_version"]),
            calibrate_heads=bool(cfg.get("calibrate_heads", False)),
        )
