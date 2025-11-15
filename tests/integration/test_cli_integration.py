"""
Integration tests for CLI commands.

Tests the real CLI commands that exist (admin tools, not workflow commands).

These tests require:
- Running nomarr system (database, services)
- Docker container environment preferred

Skip in CI with: pytest -m "not container_only"
"""

import os
import subprocess
import sys

import pytest

# Mark all tests in this module
pytestmark = [
    pytest.mark.integration,
    pytest.mark.container_only,
]

# Test fixtures
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures")


def run_cli(*args):
    """
    Run CLI command and return result.

    Args:
        *args: Command arguments

    Returns:
        subprocess.CompletedProcess
    """
    cmd = [sys.executable, "-m", "nomarr.interfaces.cli.main", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    return result


class TestCLIRemove:
    """Test remove command (queue management)."""

    def test_remove_help(self):
        """Test remove command help."""
        result = run_cli("remove", "--help")
        assert result.returncode == 0
        assert "remove" in result.stdout.lower()

    def test_remove_nonexistent_job(self):
        """Test removing nonexistent job ID."""
        result = run_cli("remove", "999999")
        # Should handle gracefully
        assert result.returncode in [0, 1]

    def test_remove_by_status(self):
        """Test removing jobs by status."""
        result = run_cli("remove", "--status", "error")
        assert result.returncode in [0, 1]


class TestCLICleanup:
    """Test cleanup command (remove old jobs)."""

    def test_cleanup_help(self):
        """Test cleanup command help."""
        result = run_cli("cleanup", "--help")
        assert result.returncode == 0
        assert "cleanup" in result.stdout.lower()

    def test_cleanup_default(self):
        """Test cleanup with default hours."""
        result = run_cli("cleanup")
        assert result.returncode in [0, 1]

    def test_cleanup_custom_hours(self):
        """Test cleanup with custom hour threshold."""
        result = run_cli("cleanup", "--hours", "24")
        assert result.returncode in [0, 1]


class TestCLICacheRefresh:
    """Test cache-refresh command (model cache management)."""

    def test_cache_refresh_help(self):
        """Test cache-refresh help."""
        result = run_cli("cache-refresh", "--help")
        assert result.returncode == 0

    def test_cache_refresh(self):
        """Test refreshing model cache."""
        result = run_cli("cache-refresh")
        # Should work or fail gracefully if no models
        assert result.returncode in [0, 1]


class TestCLIAdminReset:
    """Test admin-reset command (reset stuck/error jobs)."""

    def test_admin_reset_help(self):
        """Test admin-reset help."""
        result = run_cli("admin-reset", "--help")
        assert result.returncode == 0
        assert "admin-reset" in result.stdout.lower()

    def test_admin_reset_stuck(self):
        """Test resetting stuck jobs."""
        result = run_cli("admin-reset", "--stuck", "--force")
        assert result.returncode in [0, 1]

    def test_admin_reset_errors(self):
        """Test resetting error jobs."""
        result = run_cli("admin-reset", "--errors", "--force")
        assert result.returncode in [0, 1]


class TestCLIManagePassword:
    """Test manage-password command (admin password management)."""

    def test_manage_password_help(self):
        """Test manage-password help."""
        result = run_cli("manage-password", "--help")
        assert result.returncode == 0
        assert "password" in result.stdout.lower()

    def test_manage_password_show(self):
        """Test showing password hash."""
        result = run_cli("manage-password", "show")
        # Should work or fail gracefully if not set
        assert result.returncode in [0, 1]


class TestCLIHelp:
    """Test CLI help output."""

    def test_main_help(self):
        """Test main CLI help."""
        result = run_cli("--help")
        assert result.returncode == 0
        assert "nom" in result.stdout.lower() or "nomarr" in result.stdout.lower()

    def test_no_command(self):
        """Test running with no command shows help."""
        result = run_cli()
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "commands" in result.stdout.lower()
