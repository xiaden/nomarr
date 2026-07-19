"""Tests for auth helper functions.

Covers:
- get_key_service (success, missing key service)
- verify_password (success, failure)
- get_admin_password_hash (success, missing password)
- create_session (success)
- invalidate_session (success)
- validate_session (success, failure)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.interfaces.api import auth


@pytest.mark.unit
@pytest.mark.mocked
class TestAuthHelpers:
    """Test auth helper functions."""

    def test_get_key_service_returns_service(self) -> None:
        """get_key_service should return the key service from application.services."""
        mock_key_service = MagicMock()
        with patch("nomarr.app.application") as mock_app:
            mock_app.services = {"keys": mock_key_service}
            result = auth.get_key_service()

        assert result == mock_key_service

    def test_get_key_service_raises_when_missing(self) -> None:
        """get_key_service should raise RuntimeError when key service is not initialized."""
        with patch("nomarr.app.application") as mock_app:
            mock_app.services = {}
            with pytest.raises(RuntimeError, match="KeyManagementService not initialized"):
                auth.get_key_service()

    def test_verify_password_returns_true_for_valid_password(self) -> None:
        """verify_password should return True when password matches hash."""
        with patch.object(auth.KeyManagementService, "verify_password", return_value=True):
            result = auth.verify_password("correct_password", "hashed_password")

        assert result is True

    def test_verify_password_returns_false_for_invalid_password(self) -> None:
        """verify_password should return False when password doesn't match hash."""
        with patch.object(auth.KeyManagementService, "verify_password", return_value=False):
            result = auth.verify_password("wrong_password", "hashed_password")

        assert result is False

    def test_get_admin_password_hash_returns_hash(self) -> None:
        """get_admin_password_hash should return the admin password hash."""
        mock_key_service = MagicMock()
        mock_key_service.get_admin_password_hash.return_value = "test_hash"

        with patch.object(auth, "get_key_service", return_value=mock_key_service):
            result = auth.get_admin_password_hash()

        assert result == "test_hash"
        mock_key_service.get_admin_password_hash.assert_called_once()

    def test_create_session_returns_token(self) -> None:
        """create_session should return a session token."""
        mock_key_service = MagicMock()
        mock_key_service.create_session.return_value = "test_session_token"

        with patch.object(auth, "get_key_service", return_value=mock_key_service):
            result = auth.create_session()

        assert result == "test_session_token"
        mock_key_service.create_session.assert_called_once()

    def test_invalidate_session_calls_service(self) -> None:
        """invalidate_session should call the key service's invalidate_session."""
        mock_key_service = MagicMock()

        with patch.object(auth, "get_key_service", return_value=mock_key_service):
            auth.invalidate_session("test_session_token")

        mock_key_service.invalidate_session.assert_called_once_with("test_session_token")

    def test_validate_session_returns_true_for_valid_session(self) -> None:
        """validate_session should return True for valid session token."""
        mock_key_service = MagicMock()
        mock_key_service.validate_session.return_value = True

        with patch.object(auth, "get_key_service", return_value=mock_key_service):
            result = auth.validate_session("valid_session_token")

        assert result is True
        mock_key_service.validate_session.assert_called_once_with("valid_session_token")

    def test_validate_session_returns_false_for_invalid_session(self) -> None:
        """validate_session should return False for invalid session token."""
        mock_key_service = MagicMock()
        mock_key_service.validate_session.return_value = False

        with patch.object(auth, "get_key_service", return_value=mock_key_service):
            result = auth.validate_session("invalid_session_token")

        assert result is False
        mock_key_service.validate_session.assert_called_once_with("invalid_session_token")
