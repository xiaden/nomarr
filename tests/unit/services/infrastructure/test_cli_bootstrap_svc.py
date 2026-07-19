"""Unit tests for ``nomarr.services.infrastructure.cli_bootstrap_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.db import Database
from nomarr.services.infrastructure.cli_bootstrap_svc import (
    get_config_service,
    get_database,
    get_keys_service,
    get_metadata_service,
)


class TestGetDatabase:
    """Tests for ``get_database()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_database_instance(self) -> None:
        """get_database() returns a Database instance."""
        with patch("nomarr.services.infrastructure.cli_bootstrap_svc.Database") as mock_db_cls:
            result = get_database()

        assert result is mock_db_cls.return_value

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_pg_database_url_env_var(self) -> None:
        """get_database() passes PG_DATABASE_URL env var to Database constructor."""
        with (
            patch("nomarr.services.infrastructure.cli_bootstrap_svc.Database") as mock_db_cls,
            patch.dict("os.environ", {"PG_DATABASE_URL": "postgresql://custom:url@host:5432/customdb"}),
        ):
            get_database()

        mock_db_cls.assert_called_once_with(url="postgresql://custom:url@host:5432/customdb")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_default_url_when_env_not_set(self) -> None:
        """get_database() falls back to default URL when PG_DATABASE_URL is not set."""
        import os

        with (
            patch("nomarr.services.infrastructure.cli_bootstrap_svc.Database") as mock_db_cls,
            patch.dict("os.environ", {}, clear=True),
        ):
            os.environ.pop("PG_DATABASE_URL", None)
            get_database()

        mock_db_cls.assert_called_once_with(url="postgresql+psycopg2://nomarr:nomarr@localhost:5432/nomarr")


class TestGetConfigService:
    """Tests for ``get_config_service()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_config_service_instance(self) -> None:
        """get_config_service() returns a ConfigService instance."""
        with patch("nomarr.services.infrastructure.cli_bootstrap_svc.ConfigService") as mock_cls:
            result = get_config_service()

        assert result is mock_cls.return_value
        mock_cls.assert_called_once_with()


class TestGetKeysService:
    """Tests for ``get_keys_service()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_key_management_service_with_injected_db(self) -> None:
        """get_keys_service() returns KeyManagementService with injected Database."""
        mock_db = MagicMock(spec=Database)

        with (
            patch("nomarr.services.infrastructure.cli_bootstrap_svc.get_database", return_value=mock_db),
            patch("nomarr.services.infrastructure.cli_bootstrap_svc.KeyManagementService") as mock_cls,
        ):
            result = get_keys_service()

        mock_cls.assert_called_once_with(mock_db)
        assert result is mock_cls.return_value


class TestGetMetadataService:
    """Tests for ``get_metadata_service()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_metadata_service_with_injected_db(self) -> None:
        """get_metadata_service() returns MetadataService with injected Database."""
        mock_db = MagicMock(spec=Database)

        with (
            patch("nomarr.services.infrastructure.cli_bootstrap_svc.get_database", return_value=mock_db),
            patch("nomarr.services.infrastructure.cli_bootstrap_svc.MetadataService") as mock_cls,
        ):
            result = get_metadata_service()

        mock_cls.assert_called_once_with(mock_db)
        assert result is mock_cls.return_value
