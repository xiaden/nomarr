"""Tests for resource_monitor_comp.py."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.platform.resource_monitor_comp import (
    check_nvidia_gpu_capability,
    check_resource_headroom,
    get_ram_usage_mb,
    get_vram_usage_for_pid_mb,
    get_vram_usage_mb,
    reset_capability_cache,
    reset_telemetry_cache,
)


@pytest.fixture(autouse=True)
def reset_caches():
    """Reset caches before each test."""
    reset_capability_cache()
    reset_telemetry_cache()
    yield
    reset_capability_cache()
    reset_telemetry_cache()


class TestCheckNvidiaGpuCapability:
    """Tests for check_nvidia_gpu_capability()."""

    def test_returns_true_when_nvidia_smi_succeeds(self):
        """GPU is capable when nvidia-smi returns GPU name."""
        mock_result = MagicMock()
        mock_result.stdout = "NVIDIA GeForce RTX 3090\n"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = check_nvidia_gpu_capability()

        assert result is True

    def test_returns_false_when_nvidia_smi_not_found(self):
        """GPU not capable when nvidia-smi binary is missing."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = check_nvidia_gpu_capability()

        assert result is False

    def test_returns_false_when_nvidia_smi_times_out(self):
        """GPU not capable when nvidia-smi times out (driver wedged)."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5)):
            result = check_nvidia_gpu_capability()

        assert result is False

    def test_returns_false_when_nvidia_smi_fails(self):
        """GPU not capable when nvidia-smi returns error."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "nvidia-smi", stderr="NVML error"),
        ):
            result = check_nvidia_gpu_capability()

        assert result is False

    def test_caches_result(self):
        """Result is cached after first call."""
        mock_result = MagicMock()
        mock_result.stdout = "NVIDIA GeForce RTX 3090\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result1 = check_nvidia_gpu_capability()
            result2 = check_nvidia_gpu_capability()

        assert result1 is True
        assert result2 is True
        # Should only be called once due to caching
        assert mock_run.call_count == 1


class TestGetVramUsageMb:
    """Tests for get_vram_usage_mb()."""

    def test_parses_nvidia_smi_output(self):
        """VRAM usage is correctly parsed from nvidia-smi output."""
        mock_result = MagicMock()
        mock_result.stdout = "8192, 24576\n"  # used, total in MiB

        with patch("subprocess.run", return_value=mock_result):
            result = get_vram_usage_mb()

        assert result["used_mb"] == 8192
        assert result["total_mb"] == 24576
        assert result["error"] is None

    def test_sums_multiple_gpus(self):
        """VRAM from multiple GPUs is summed."""
        mock_result = MagicMock()
        mock_result.stdout = "4096, 12288\n8192, 24576\n"  # Two GPUs

        with patch("subprocess.run", return_value=mock_result):
            result = get_vram_usage_mb()

        assert result["used_mb"] == 4096 + 8192
        assert result["total_mb"] == 12288 + 24576

    def test_returns_zero_on_error(self):
        """Returns zero values on nvidia-smi error."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5)):
            result = get_vram_usage_mb()

        assert result["used_mb"] == 0
        assert result["total_mb"] == 0
        assert result["error"] is not None


class TestGetVramUsageForPidMb:
    """Tests for get_vram_usage_for_pid_mb()."""

    def test_finds_correct_pid(self):
        """Returns VRAM for specific process."""
        mock_result = MagicMock()
        mock_result.stdout = "1234, 4096\n5678, 8192\n"

        with patch("subprocess.run", return_value=mock_result):
            result = get_vram_usage_for_pid_mb(1234)

        assert result == 4096

    def test_returns_zero_when_pid_not_found(self):
        """Returns 0 when PID is not using GPU."""
        mock_result = MagicMock()
        mock_result.stdout = "1234, 4096\n"

        with patch("subprocess.run", return_value=mock_result):
            result = get_vram_usage_for_pid_mb(9999)

        assert result == 0


class TestGetRamUsageMb:
    """Tests for get_ram_usage_mb()."""

    def test_returns_ram_usage_for_host_mode(self):
        """Returns RAM usage in host mode using psutil."""
        import nomarr.components.platform.resource_monitor_comp as rm

        # Clear the cache to ensure fresh query
        rm._ram_cache = None
        rm._ram_cache_ts = 0

        result = get_ram_usage_mb(detection_mode="host")

        # Should return actual values (we can't predict exact values, but format is known)
        assert isinstance(result["used_mb"], int)
        assert isinstance(result["available_mb"], int)
        assert result["used_mb"] >= 0
        assert result["available_mb"] >= 0
        assert result["error"] is None


class TestCheckResourceHeadroom:
    """Tests for check_resource_headroom()."""

    def test_returns_ok_when_within_budget(self):
        """Returns OK when resources are within budget."""
        # Mock GPU not capable to simplify test
        with patch(
            "nomarr.components.platform.resource_monitor_comp.check_nvidia_gpu_capability",
            return_value=False,
        ):
            mock_ram = {"used_mb": 4096, "available_mb": 8192, "error": None}
            with patch(
                "nomarr.components.platform.resource_monitor_comp.get_ram_usage_mb",
                return_value=mock_ram,
            ):
                result = check_resource_headroom(
                    vram_budget_mb=0,  # No VRAM budget (CPU-only)
                    ram_budget_mb=16384,
                    vram_estimate_mb=0,
                    ram_estimate_mb=2048,
                )

        assert result.ram_ok is True
        assert result.vram_ok is True  # Trivially OK when no VRAM budget
        assert result.gpu_capable is False

    def test_returns_not_ok_when_over_budget(self):
        """Returns not OK when resources exceed budget."""
        with patch(
            "nomarr.components.platform.resource_monitor_comp.check_nvidia_gpu_capability",
            return_value=False,
        ):
            mock_ram = {"used_mb": 14000, "available_mb": 2000, "error": None}
            with patch(
                "nomarr.components.platform.resource_monitor_comp.get_ram_usage_mb",
                return_value=mock_ram,
            ):
                result = check_resource_headroom(
                    vram_budget_mb=0,
                    ram_budget_mb=16384,
                    vram_estimate_mb=0,
                    ram_estimate_mb=4096,  # Would exceed budget
                )

        # 14000 + 4096 = 18096 > 16384
        assert result.ram_ok is False
