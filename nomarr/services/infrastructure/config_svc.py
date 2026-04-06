#!/usr/bin/env python3
# ======================================================================
#  Config Service - Configuration loading and caching
#  - Loads config from YAML, env vars, DB meta
#  - Caches composed config for performance
#  - Provides reload() for runtime changes
# ======================================================================

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import threading
from typing import Any, Literal

import yaml

from nomarr.components.ml.onnx.ml_discovery_comp import compute_model_suite_hash
from nomarr.helpers.config_schema import ALL_CONFIG_KEYS, WEB_EDITABLE_KEYS, DynamicConfig, StaticConfig
from nomarr.helpers.dto.config_dto import ConfigResult, GetInternalInfoResult, WebConfigResult
from nomarr.helpers.dto.processing_dto import ProcessorConfig
from nomarr.persistence.db import Database

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
INTERNAL_CALIBRATION_MIN_FILES = 100  # Min files before auto-calibration
INTERNAL_CALIBRATION_QUALITY_THRESHOLD = 0.85  # Don't recalibrate if quality > this

# Calibration drift thresholds
INTERNAL_CALIBRATION_APD_THRESHOLD = 0.01  # Max absolute percentile drift (1%)
INTERNAL_CALIBRATION_SRD_THRESHOLD = 0.05  # Max scale range drift (5%)
INTERNAL_CALIBRATION_JSD_THRESHOLD = 0.1  # Max Jensen-Shannon divergence
INTERNAL_CALIBRATION_MEDIAN_THRESHOLD = 0.05  # Max median drift (5%)
INTERNAL_CALIBRATION_IQR_THRESHOLD = 0.1  # Max IQR drift (10%)


# Key sets derived from config_schema — see nomarr.helpers.config_schema
# ALL_CONFIG_KEYS and WEB_EDITABLE_KEYS are imported at the top of this file.
_ALLOWED_CONFIG_KEYS = ALL_CONFIG_KEYS


class ConfigService:
    """Service for loading and caching application configuration.

    Architecture (post-refactor):
    - Bootstrap: defaults → YAML → ENV → seed to DB (once at startup)
    - Cache: mutable dict populated from DB after bootstrap
    - Reads: always from cache (fast, no recomposition)
    - Writes: mutate cache → cache setter triggers DB write

    DB is the durable store. Cache is the fast read path.
    """

    def __init__(self) -> None:
        """Initialize ConfigService: bootstrap config to DB, load cache."""
        self._cache: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._bootstrap_and_load()

    def get_config(self) -> ConfigResult:
        """Get a snapshot of the current configuration.

        Returns:
            ConfigResult wrapping a shallow copy of the cache

        """
        with self._lock:
            return ConfigResult(config=dict(self._cache))

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by flat key from the mutable cache.

        Args:
            key: Flat config key (e.g. "namespace", "calibrate_heads")
            default: Default value if key not found

        Returns:
            Config value (typed Python object) or default

        """
        with self._lock:
            return self._cache.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Write-through setter: update cache then persist to DB.

        Args:
            key: Config key (must be in _ALLOWED_CONFIG_KEYS)
            value: Typed Python value (stored as-is in cache, stringified for DB)

        Raises:
            ValueError: If key is not in _ALLOWED_CONFIG_KEYS

        """
        if key not in _ALLOWED_CONFIG_KEYS:
            msg = f"Config key '{key}' is not an allowed config key"
            raise ValueError(msg)

        with self._lock:
            self._cache[key] = value
        self._write_to_db(key, str(value) if value is not None else "")
        self._logger.info("Config '%s' updated (cache + DB)", key)

    def _write_to_db(self, key: str, value: str) -> None:
        """Persist a config value to DB meta table via throwaway connection."""
        try:
            db = Database()
            try:
                db.meta.set(f"config_{key}", value)
            finally:
                db.close()
        except Exception:
            self._logger.exception("Failed to persist config '%s' to DB", key)

    def get_internal_info(self) -> GetInternalInfoResult:
        """Get internal (read-only) configuration constants.

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

    def get_config_for_web(self, worker_service: Any | None = None) -> WebConfigResult:
        """Get configuration for the web UI endpoint.

        Returns only WEB_EDITABLE_KEYS subset, plus internal constants
        and live worker status.

        Args:
            worker_service: Optional WorkersCoordinator to check live worker status

        Returns:
            WebConfigResult with filtered config for web UI

        """
        with self._lock:
            filtered_config = {k: v for k, v in self._cache.items() if k in WEB_EDITABLE_KEYS}
        internal_info = self.get_internal_info()
        worker_enabled = worker_service.is_worker_system_enabled() if worker_service else internal_info.worker_enabled

        return WebConfigResult(config=filtered_config, internal_info=internal_info, worker_enabled=worker_enabled)

    def get_worker_count(self, kind: Literal["tagger"] = "tagger") -> int:
        """Get worker count for the tagger worker pool.

        Args:
            kind: Worker pool type (only "tagger" is supported)

        Returns:
            Worker count (constrained to 1-8, defaults to 1)

        Example:
            >>> config_service.get_worker_count("tagger")
            2  # from tagger_worker_count

        """
        cfg = self.get_config().config

        pool_key = f"{kind}_worker_count"
        if pool_key in cfg and cfg[pool_key] is not None:
            count = int(cfg[pool_key])
            self._logger.debug(f"[ConfigService] Using {pool_key}={count}")
            return max(1, min(8, count))

        # Default to 1
        self._logger.debug(f"[ConfigService] No {pool_key} configured, defaulting to 1 for {kind} pool")
        return 1

    # ----------------------------------------------------------------------
    # Private composition logic
    # ----------------------------------------------------------------------

    def _bootstrap_and_load(self) -> None:
        """Bootstrap config to DB and load cache from DB.

        Opens ONE throwaway Database connection and performs:
        1. Compose bootstrap config (defaults → YAML → ENV)
        2. Seed to DB: write keys NOT already present (preserves web UI changes)
        3. Load all config_* keys from DB into self._cache (parsed to Python types)

        Cache holds parsed Python types (bool, int, float, str).
        DB holds string representations.
        """
        bootstrap_config = self._build_bootstrap_config()

        try:
            db = Database()
            try:
                # Batch-read existing config keys from DB
                existing = db.meta.get_by_prefix("config_")
                existing_keys = {k[7:] for k in existing}  # Strip 'config_' prefix

                # Seed: write only keys NOT already in DB
                for key in _ALLOWED_CONFIG_KEYS:
                    if key not in existing_keys and key in bootstrap_config:
                        value = bootstrap_config[key]
                        db.meta.set(f"config_{key}", str(value) if value is not None else "")

                # Load: read all config_* keys back into cache
                all_config = db.meta.get_by_prefix("config_")
                for db_key, db_value in all_config.items():
                    config_key = db_key[7:]  # Strip 'config_' prefix
                    if config_key in _ALLOWED_CONFIG_KEYS:
                        self._cache[config_key] = self._parse_db_value(db_value)

                self._logger.debug("Config bootstrap complete: %d keys loaded", len(self._cache))
            finally:
                db.close()

        except Exception as e:
            # DB unavailable at startup — fall back to bootstrap config directly
            self._logger.warning("DB unavailable for config bootstrap, using file/env config: %s", e)
            for key in _ALLOWED_CONFIG_KEYS:
                if key in bootstrap_config:
                    self._cache[key] = bootstrap_config[key]

    @staticmethod
    def _parse_db_value(value: str) -> bool | int | float | str:
        """Parse a DB string value to the appropriate Python type."""
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        # Handle negative integers: strip optional leading minus for digit check
        stripped = value.lstrip("-")
        if stripped.isdigit() and (len(stripped) == len(value) or len(value) == len(stripped) + 1):
            return int(value)
        if value.replace(".", "", 1).replace("-", "", 1).isdigit():
            return float(value)
        return value

    def _build_bootstrap_config(self) -> dict[str, Any]:
        """Build bootstrap config from defaults → YAML → ENV (no DB).

        Called once during bootstrap. DB seeding is handled separately
        in _bootstrap_and_load(). This method only composes the file/env layers.
        """
        cfg = self._default_config()

        # 1) System-wide YAML
        self._deep_merge(cfg, self._load_yaml("/etc/nomarr/config.yaml"))

        # 1b) Container-mounted or repo-local config (common Docker layout)
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

        # 3) Environment variable overrides (flat -> nested mapping)
        self._apply_env_overrides(cfg)

        with contextlib.suppress(Exception):
            self._logger.debug("Bootstrap config composed; keys: %s", list(cfg.keys()))

        return cfg

    def _default_config(self) -> dict[str, Any]:
        """Base defaults for all user-configurable settings.

        Derived from StaticConfig and DynamicConfig dataclass defaults.
        These settings are exposed to users via config.yaml,
        environment variables, or database overrides.

        All other operational parameters are internal constants
        defined at module level.
        """
        return {
            **dataclasses.asdict(StaticConfig()),
            **dataclasses.asdict(DynamicConfig()),
        }

    def _deep_merge(self, base_dict: dict[str, Any], override_dict: dict[str, Any]) -> dict[str, Any]:
        """Recursively merge dict b into dict a (mutates a, returns it)."""
        for key, value in override_dict.items():
            if isinstance(value, dict) and isinstance(base_dict.get(key), dict):
                self._deep_merge(base_dict[key], value)
            else:
                base_dict[key] = value
        return base_dict

    def _load_yaml(self, path: str) -> dict[str, Any]:
        """Load a YAML file; returns {} if not found or invalid."""
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _apply_env_overrides(self, cfg: dict[str, Any]) -> None:
        """Apply NOMARR_* environment variable overrides to the config dict.

        Scans os.environ for keys prefixed with NOMARR_ (primary) or legacy
        TAGGER_/AUTOTAG_ prefixes.  Only keys present in ALL_CONFIG_KEYS
        (derived from StaticConfig + DynamicConfig) are accepted.

        Values are parsed with the same ``_parse_db_value`` logic used for
        DB reads, which correctly handles booleans, negative integers, floats,
        and plain strings.

        Internal constants cannot be overridden via environment.
        """
        for env_key, env_value in os.environ.items():
            # Support NOMARR_* prefix (primary), TAGGER_* and AUTOTAG_* (legacy)
            if not env_key.startswith(("NOMARR_", "TAGGER_", "AUTOTAG_")):
                continue

            # Normalize to lowercase key name
            key = env_key.replace("NOMARR_", "").replace("TAGGER_", "").replace("AUTOTAG_", "").lower()

            # Only allow whitelisted keys
            if key not in _ALLOWED_CONFIG_KEYS:
                self._logger.debug("Ignoring environment override for unknown key: %s", key)
                continue

            try:
                cfg[key] = self._parse_db_value(env_value)
            except Exception:
                continue

    def make_processor_config(self) -> ProcessorConfig:
        """Build a ProcessorConfig from the current configuration.

        Contains only startup-fixed values (model paths, internal constants,
        tagger versioning). Created once and serialized to worker subprocesses.

        Returns:
            ProcessorConfig instance for injection into worker spawn.

        """
        cfg = self.get_config()
        models_dir = str(cfg.config["models_dir"])

        # Compute tagger_version dynamically from installed models
        tagger_version = compute_model_suite_hash(models_dir)

        return ProcessorConfig(
            models_dir=models_dir,
            min_duration_s=INTERNAL_MIN_DURATION_S,
            allow_short=INTERNAL_ALLOW_SHORT,
            batch_size=INTERNAL_BATCH_SIZE,
            namespace=INTERNAL_NAMESPACE,
            version_tag_key=INTERNAL_VERSION_TAG,
            tagger_version=tagger_version,
        )
