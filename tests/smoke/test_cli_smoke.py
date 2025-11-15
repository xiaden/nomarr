"""
Smoke tests for CLI commands.

Tests all CLI commands with minimal setup - verifies they don't crash.
Uses fake database and generated test audio files.
"""

import subprocess
import sys


def run_cli_command(*args, env=None):
    """
    Run a CLI command and return result.

    Args:
        *args: Command arguments to pass to CLI
        env: Optional environment variables

    Returns:
        subprocess.CompletedProcess
    """
    cmd = [sys.executable, "-m", "nomarr.interfaces.cli.main", *list(args)]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
    )
    return result


class TestCLITag:
    """Smoke tests for 'tag' command."""

    def test_tag_basic_file(self, test_audio_fixtures, smoke_test_env):
        """Test tagging a basic audio file."""
        test_file = test_audio_fixtures["basic"]
        result = run_cli_command("tag", test_file, env=smoke_test_env)

        # Should not crash (exit code 0 or 1 acceptable)
        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_tag_long_file(self, test_audio_fixtures, smoke_test_env):
        """Test tagging a longer audio file."""
        test_file = test_audio_fixtures["long"]
        result = run_cli_command("tag", test_file, env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_tag_short_file_below_min_duration(self, test_audio_fixtures, smoke_test_env):
        """Test tagging a file below min_duration (should fail gracefully)."""
        test_file = test_audio_fixtures["short"]
        result = run_cli_command("tag", test_file, env=smoke_test_env)

        # Should fail gracefully (not crash)
        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_tag_nonexistent_file(self, smoke_test_env):
        """Test tagging a nonexistent file (should fail gracefully)."""
        result = run_cli_command("tag", "/nonexistent/file.wav", env=smoke_test_env)

        # Should fail gracefully
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_tag_with_force_flag(self, test_audio_fixtures, smoke_test_env):
        """Test tagging with --force flag."""
        test_file = test_audio_fixtures["basic"]
        result = run_cli_command("tag", "--force", test_file, env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"


class TestCLIQueue:
    """Smoke tests for 'queue' commands."""

    def test_queue_list(self, smoke_test_env):
        """Test listing queue (should work even if empty)."""
        result = run_cli_command("queue", "list", env=smoke_test_env)

        assert result.returncode == 0, f"CLI crashed: {result.stderr}"

    def test_queue_status_nonexistent(self, smoke_test_env):
        """Test checking status of nonexistent job."""
        result = run_cli_command("queue", "status", "99999", env=smoke_test_env)

        # Should handle gracefully
        assert result.returncode in [0, 1]

    def test_queue_remove_nonexistent(self, smoke_test_env):
        """Test removing nonexistent job."""
        result = run_cli_command("queue", "remove", "99999", env=smoke_test_env)

        # Should handle gracefully
        assert result.returncode in [0, 1]

    def test_queue_clear_all(self, smoke_test_env):
        """Test clearing all jobs from queue."""
        result = run_cli_command("queue", "clear", "--all", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"


class TestCLILibrary:
    """Smoke tests for 'library' commands."""

    def test_library_scan(self, smoke_test_env, temp_test_dir):
        """Test library scan command."""
        # Create a fake library path
        library_path = temp_test_dir / "music"
        library_path.mkdir()

        result = run_cli_command("library", "scan", str(library_path), env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_library_list(self, smoke_test_env):
        """Test listing library files."""
        result = run_cli_command("library", "list", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_library_stats(self, smoke_test_env):
        """Test showing library statistics."""
        result = run_cli_command("library", "stats", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"


class TestCLICalibration:
    """Smoke tests for 'calibration' commands."""

    def test_calibration_status(self, smoke_test_env):
        """Test checking calibration status."""
        result = run_cli_command("calibration", "status", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_calibration_start(self, smoke_test_env):
        """Test starting calibration (should fail gracefully without models)."""
        result = run_cli_command("calibration", "start", env=smoke_test_env)

        # Should fail gracefully without models
        assert result.returncode in [0, 1]

    def test_calibration_history(self, smoke_test_env):
        """Test viewing calibration history."""
        result = run_cli_command("calibration", "history", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"


class TestCLIWorker:
    """Smoke tests for 'worker' commands."""

    def test_worker_status(self, smoke_test_env):
        """Test checking worker status."""
        result = run_cli_command("worker", "status", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_worker_pause(self, smoke_test_env):
        """Test pausing worker."""
        result = run_cli_command("worker", "pause", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_worker_resume(self, smoke_test_env):
        """Test resuming worker."""
        result = run_cli_command("worker", "resume", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"


class TestCLICache:
    """Smoke tests for 'cache' commands."""

    def test_cache_refresh(self, smoke_test_env):
        """Test refreshing model cache."""
        result = run_cli_command("cache", "refresh", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_cache_list(self, smoke_test_env):
        """Test listing cached models."""
        result = run_cli_command("cache", "list", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"


class TestCLIAdmin:
    """Smoke tests for 'admin' commands."""

    def test_admin_reset_stuck(self, smoke_test_env):
        """Test resetting stuck jobs."""
        result = run_cli_command("admin", "reset", "--stuck", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_admin_reset_errors(self, smoke_test_env):
        """Test resetting error jobs."""
        result = run_cli_command("admin", "reset", "--errors", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"

    def test_admin_cleanup(self, smoke_test_env):
        """Test cleanup command."""
        result = run_cli_command("admin", "cleanup", env=smoke_test_env)

        assert result.returncode in [0, 1], f"CLI crashed: {result.stderr}"


class TestCLIHelp:
    """Smoke tests for help output."""

    def test_help_main(self):
        """Test main help output."""
        result = run_cli_command("--help")

        assert result.returncode == 0
        assert "nomarr" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_help_tag(self):
        """Test tag command help."""
        result = run_cli_command("tag", "--help")

        assert result.returncode == 0
        assert "tag" in result.stdout.lower()

    def test_help_queue(self):
        """Test queue command help."""
        result = run_cli_command("queue", "--help")

        assert result.returncode == 0
        assert "queue" in result.stdout.lower()
