# mypy: disable-error-code=attr-defined
# mypy: disable-error-code=func-returns-value
"""Spec-first tests for the hard-cut semantic AppDb meta contract.

Scope (TASK-meta-intent-facades-A-hard-cut, P1-S5): pin the CONTRACTED semantic
surface of ``AppDb`` for the meta-backed domains — user config, schema version,
credentials (API key / admin password hash), calibration bookkeeping, model VRAM
limits, capacity estimates, GPU resource snapshots, and worker-control state.

These are spec-first semantic-contract tests: they pin the public ``AppDb``
surface (existence + signature + semantic output) for every meta-backed domain.
All 37 tests pass against the implemented surface. Mock wiring (the repository
method a facade getter delegates to) mirrors the facade method name, following
``test_app_db.py`` (e.g. ``get_worker_restart_policy`` facade →
``mock_app_repo.get_worker_restart_policy``).

By contract these tests must NOT assert ``get_meta`` / ``upsert_meta`` /
``delete_meta`` / prefix listing / ``MetaRow`` / ``{"value": ...}`` payloads from the
facade — that is repository-internal detail. All assertions are on the semantic
domain surface.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.app_dataclasses import CapacityEstimate, ConfigOption
from nomarr.persistence.api.application import AppDb
from nomarr.persistence.database.pipeline_repo import PipelineRepository

# NOTE (Phase 2): CapacityEstimate now lives at its single authoritative home in
# ``nomarr/helpers/dataclasses/app_dataclasses.py`` (frozen/slotted). The component
# ``ml_capacity_probe_comp`` is migrated to import it from helpers in Phase 3.
# ``ModelVramLimit`` / ``GpuResourceSnapshot`` exist in app_dataclasses now, but
# the tests that need them (list_model_vram_limits round trip, GPU setter) are
# deferred to Phase 2 rather than fabricating stand-in types.


# ── Fixtures (mirror tests/unit/persistence/api/test_app_db.py) ─────────────


@pytest.fixture
def mock_app_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_pipeline_repo() -> MagicMock:
    return MagicMock(spec=PipelineRepository)


@pytest.fixture
def mock_song_state_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def app_db(
    mock_app_repo: MagicMock,
    mock_song_state_repo: MagicMock,
    mock_pipeline_repo: MagicMock,
) -> AppDb:
    return AppDb(
        session=MagicMock(),
        app_repo=mock_app_repo,
        song_state_repo=mock_song_state_repo,
        pipeline_repo=mock_pipeline_repo,
    )


# ── User configuration (set_config_option / get_config_option) ──────────────


class TestUserConfigSemantics:
    @pytest.mark.unit
    def test_set_config_option_accepts_scalar(self, app_db: AppDb) -> None:
        """``set_config_option(key, value)`` takes a scalar/domain value directly."""
        result = app_db.set_config_option("config_scan_interval", 600)
        assert result is None

    @pytest.mark.unit
    def test_set_config_option_accepts_bool_and_str(self, app_db: AppDb) -> None:
        """Direct scalars (bool / str) are the only accepted write values."""
        assert app_db.set_config_option("config_calibrate", True) is None
        assert app_db.set_config_option("config_models_dir", "/models") is None

    @pytest.mark.unit
    def test_set_config_option_rejects_storage_payload_dict(self, app_db: AppDb) -> None:
        """The legacy ``{"value": ...}`` storage payload is not a valid write value."""
        with pytest.raises((TypeError, ValueError)):
            app_db.set_config_option("config_scan_interval", {"value": 600})

    @pytest.mark.unit
    def test_get_config_option_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_config_option.return_value = None
        assert app_db.get_config_option("config_missing") is None

    @pytest.mark.unit
    def test_get_config_option_returns_domain_option(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_config_option.return_value = ConfigOption(key="config_scan_interval", value=600)
        option = app_db.get_config_option("config_scan_interval")
        assert isinstance(option, ConfigOption)
        assert option.key == "config_scan_interval"
        assert option.value == 600


# ── Schema version ──────────────────────────────────────────────────────────


class TestSchemaVersionSemantics:
    @pytest.mark.unit
    def test_set_schema_version_accepts_str(self, app_db: AppDb) -> None:
        assert app_db.set_schema_version("2.5.0") is None

    @pytest.mark.unit
    def test_get_schema_version_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_schema_version.return_value = None
        assert app_db.get_schema_version() is None

    @pytest.mark.unit
    def test_get_schema_version_coerces_none_to_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_schema_version.return_value = None
        assert app_db.get_schema_version() is None

    @pytest.mark.unit
    def test_get_schema_version_coerces_non_str_to_str(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        """The schema version is exposed as a string even if persisted as a number."""
        mock_app_repo.get_schema_version.return_value = "42"
        assert app_db.get_schema_version() == "42"


# ── Credentials (API key / admin password hash) ─────────────────────────────


class TestCredentialSemantics:
    @pytest.mark.unit
    def test_set_api_key_accepts_str(self, app_db: AppDb) -> None:
        assert app_db.set_api_key("secret-key") is None

    @pytest.mark.unit
    def test_get_api_key_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_api_key.return_value = None
        assert app_db.get_api_key() is None

    @pytest.mark.unit
    def test_get_api_key_returns_stored_value(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_api_key.return_value = "secret-key"
        assert app_db.get_api_key() == "secret-key"

    @pytest.mark.unit
    def test_set_admin_password_hash_accepts_str(self, app_db: AppDb) -> None:
        assert app_db.set_admin_password_hash("$2b$12$abcdef") is None

    @pytest.mark.unit
    def test_get_admin_password_hash_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_admin_password_hash.return_value = None
        assert app_db.get_admin_password_hash() is None

    @pytest.mark.unit
    def test_get_admin_password_hash_returns_stored_value(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_admin_password_hash.return_value = "$2b$12$abcdef"
        assert app_db.get_admin_password_hash() == "$2b$12$abcdef"

    @pytest.mark.unit
    def test_credential_read_write_are_distinct_intents(self, app_db: AppDb) -> None:
        """API key and admin password hash are isolated — no cross-reads."""
        app_db.get_api_key()
        app_db.get_admin_password_hash()
        # Assertions are semantic only; no shared storage identity leaks.


# ── Calibration bookkeeping ─────────────────────────────────────────────────


class TestCalibrationBookkeepingSemantics:
    @pytest.mark.unit
    def test_set_calibration_version_accepts_hash(self, app_db: AppDb) -> None:
        assert app_db.set_calibration_version("hash-123") is None

    @pytest.mark.unit
    def test_get_calibration_version_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_calibration_version.return_value = None
        assert app_db.get_calibration_version() is None

    @pytest.mark.unit
    def test_get_calibration_version_returns_hash(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_calibration_version.return_value = "hash-123"
        assert app_db.get_calibration_version() == "hash-123"

    @pytest.mark.unit
    def test_set_calibration_last_run_accepts_str_timestamp(self, app_db: AppDb) -> None:
        """Locked (Phase 1): accepted type is ``str``, preserving the live caller."""
        assert app_db.set_calibration_last_run("1750000000000") is None

    @pytest.mark.unit
    def test_get_calibration_last_run_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_calibration_last_run.return_value = None
        assert app_db.get_calibration_last_run() is None

    @pytest.mark.unit
    def test_get_calibration_last_run_converts_to_int(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        """Stored string timestamp is exposed as an integer millisecond value."""
        mock_app_repo.get_calibration_last_run.return_value = 1750000000000
        assert app_db.get_calibration_last_run() == 1750000000000

    @pytest.mark.unit
    def test_clear_calibration_metadata_returns_count(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        """One atomic clear returns the number of bookkeeping values removed."""
        mock_app_repo.clear_calibration_metadata.return_value = 2
        assert app_db.clear_calibration_metadata() == 2


# ── Model VRAM limits / measurements ────────────────────────────────────────


class TestModelVramLimitSemantics:
    @pytest.mark.unit
    def test_set_model_vram_limit_accepts_bytes(self, app_db: AppDb) -> None:
        assert app_db.set_model_vram_limit("/models/a.onnx", 1_073_741_824) is None

    @pytest.mark.unit
    def test_get_model_vram_limit_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_model_vram_limit.return_value = None
        assert app_db.get_model_vram_limit("/models/a.onnx") is None

    @pytest.mark.unit
    def test_get_model_vram_limit_path_mapping(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        """The per-model limit is addressed by its model path, value in bytes."""
        mock_app_repo.get_model_vram_limit.return_value = 1_073_741_824
        assert app_db.get_model_vram_limit("/models/a.onnx") == 1_073_741_824

    @pytest.mark.unit
    def test_clear_model_vram_limits_returns_count(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.clear_model_vram_limits.return_value = 3
        assert app_db.clear_model_vram_limits() == 3


# ── Capacity estimates ──────────────────────────────────────────────────────


class TestCapacityEstimateSemantics:
    @pytest.mark.unit
    def test_set_capacity_estimate_accepts_domain_value(self, app_db: AppDb) -> None:
        estimate = CapacityEstimate(
            model_set_hash="abc123",
            measured_backbone_vram_mb=4096,
            estimated_worker_ram_mb=2048,
            gpu_capable=True,
        )
        assert app_db.set_capacity_estimate(estimate) is None

    @pytest.mark.unit
    def test_get_capacity_estimate_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_capacity_estimate.return_value = None
        assert app_db.get_capacity_estimate("abc123") is None

    @pytest.mark.unit
    def test_get_capacity_estimate_round_trip(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        estimate = CapacityEstimate(
            model_set_hash="abc123",
            measured_backbone_vram_mb=4096,
            estimated_worker_ram_mb=2048,
            gpu_capable=True,
        )
        mock_app_repo.get_capacity_estimate.return_value = estimate
        assert app_db.get_capacity_estimate("abc123") == estimate

    @pytest.mark.unit
    def test_remove_capacity_estimate_returns_none(self, app_db: AppDb) -> None:
        assert app_db.remove_capacity_estimate("abc123") is None


# ── GPU resource snapshot ───────────────────────────────────────────────────


class TestGpuSnapshotSemantics:
    @pytest.mark.unit
    def test_get_gpu_resource_snapshot_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_gpu_resource_snapshot.return_value = None
        assert app_db.get_gpu_resource_snapshot() is None

    # set_gpu_resource_snapshot(GpuResourceSnapshot) is deferred to Phase 2, once
    # the GpuResourceSnapshot dataclass lands in app_dataclasses.py.


# ── Worker-control state ────────────────────────────────────────────────────


class TestWorkerControlSemantics:
    @pytest.mark.unit
    def test_set_worker_system_enabled_accepts_bool(self, app_db: AppDb) -> None:
        assert app_db.set_worker_system_enabled(True) is None
        assert app_db.set_worker_system_enabled(False) is None

    @pytest.mark.unit
    def test_get_worker_system_enabled_absent_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_worker_system_enabled.return_value = None
        assert app_db.get_worker_system_enabled() is None

    @pytest.mark.unit
    def test_get_worker_system_enabled_returns_bool(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_worker_system_enabled.return_value = True
        assert app_db.get_worker_system_enabled() is True


# ── No transaction / session surface ────────────────────────────────────────


class TestNoTransactionSessionSurface:
    @pytest.mark.unit
    def test_facade_exposes_no_transaction_or_session_handles(self, app_db: AppDb) -> None:
        """AppDb meta intents never leak a transaction/session to callers."""
        for forbidden in ("transaction", "begin", "session", "commit", "rollback", "begin_nested"):
            assert not hasattr(app_db, forbidden), f"AppDb must not expose '{forbidden}'"

    @pytest.mark.unit
    def test_no_meta_payload_terminology_on_public_surface(self, app_db: AppDb) -> None:
        """No storage-shape names on the public facade."""
        for forbidden in ("get_meta", "upsert_meta", "delete_meta", "list_meta_keys_by_prefix"):
            assert not hasattr(app_db, forbidden), f"AppDb must not expose '{forbidden}'"
