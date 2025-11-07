"""
Unit tests for nomarr/core/cache.py
"""

import time
from unittest.mock import patch

import pytest

from nomarr.ml.cache import (
    cache_key,
    check_and_evict_idle_cache,
    clear_predictor_cache,
    get_cache_idle_time,
    get_cache_size,
    is_initialized,
    touch_cache,
)
from nomarr.ml.models.discovery import HeadInfo, Sidecar


@pytest.mark.unit
class TestCacheKey:
    """Test cache key generation."""

    def test_cache_key_format(self, mock_sidecar):
        """Test that cache keys are generated correctly."""
        sidecar = Sidecar(path="/models/test_model.json", data=mock_sidecar)
        head_info = HeadInfo(
            sidecar=sidecar,
            backbone="effnet",
            head_type="softmax",
            embedding_graph="/models/embedding.pb",
        )

        key = cache_key(head_info)
        assert key == "test_model::effnet::softmax"
        assert isinstance(key, str)

    def test_cache_key_uniqueness(self, mock_sidecar):
        """Test that different models get different cache keys."""
        # Create first sidecar with name "model_a"
        sidecar1_data = mock_sidecar.copy()
        sidecar1_data["name"] = "model_a"
        sidecar1 = Sidecar(path="/models/model_a.json", data=sidecar1_data)
        head1 = HeadInfo(
            sidecar=sidecar1,
            backbone="effnet",
            head_type="softmax",
            embedding_graph="/models/embedding.pb",
        )

        # Create second sidecar with name "model_b"
        sidecar2_data = mock_sidecar.copy()
        sidecar2_data["name"] = "model_b"
        sidecar2 = Sidecar(path="/models/model_b.json", data=sidecar2_data)
        head2 = HeadInfo(
            sidecar=sidecar2,
            backbone="effnet",
            head_type="softmax",
            embedding_graph="/models/embedding.pb",
        )

        assert cache_key(head1) != cache_key(head2)


@pytest.mark.unit
class TestCacheLifecycle:
    """Test cache initialization and lifecycle."""

    def test_is_initialized_false_by_default(self):
        """Test that cache starts uninitialized."""
        clear_predictor_cache()
        assert not is_initialized()

    def test_get_cache_size_empty(self):
        """Test that cache size is 0 when empty."""
        clear_predictor_cache()
        assert get_cache_size() == 0


@pytest.mark.unit
class TestIdleEviction:
    """Test cache idle timeout and eviction logic."""

    def test_touch_cache_updates_access_time(self):
        """Test that touching the cache updates last access time."""
        touch_cache()
        idle_time_1 = get_cache_idle_time()

        time.sleep(0.1)

        idle_time_2 = get_cache_idle_time()
        assert idle_time_2 > idle_time_1
        assert idle_time_2 >= 0.1

    def test_get_cache_idle_time_initial(self):
        """Test that idle time starts at 0 after touch."""
        touch_cache()
        idle_time = get_cache_idle_time()
        assert idle_time < 0.5  # Should be very small

    def test_check_and_evict_no_timeout(self, mock_config):
        """Test that cache is NOT evicted when timeout is 0 (disabled)."""
        with patch("nomarr.ml.cache._get_cache_config", return_value=(0, True)):
            touch_cache()
            time.sleep(0.1)

            evicted = check_and_evict_idle_cache()
            assert not evicted  # Timeout disabled

    def test_check_and_evict_auto_evict_disabled(self, mock_config):
        """Test that cache is NOT evicted when auto_evict is False."""
        with patch("nomarr.ml.cache._get_cache_config", return_value=(1, False)):
            touch_cache()
            time.sleep(1.1)

            evicted = check_and_evict_idle_cache()
            assert not evicted  # Auto-evict disabled

    def test_check_and_evict_not_idle_long_enough(self, mock_config):
        """Test that cache is NOT evicted when idle time < timeout."""
        with patch("nomarr.ml.cache._get_cache_config", return_value=(10, True)):
            touch_cache()
            time.sleep(0.1)

            evicted = check_and_evict_idle_cache()
            assert not evicted  # Not idle long enough

    def test_check_and_evict_success(self, mock_config):
        """Test that cache IS evicted when idle time > timeout."""
        with (
            patch("nomarr.ml.cache._get_cache_config", return_value=(0.2, True)),
            patch("nomarr.ml.cache._CACHE_INITIALIZED", True),
            patch("nomarr.ml.cache._PREDICTOR_CACHE", {"dummy": lambda x, y: x}),
        ):
            touch_cache()
            time.sleep(0.3)

            evicted = check_and_evict_idle_cache()
            assert evicted  # Should evict

    def test_clear_predictor_cache_resets_state(self):
        """Test that clearing cache resets initialization state."""
        touch_cache()
        clear_predictor_cache()

        assert not is_initialized()
        assert get_cache_size() == 0


@pytest.mark.unit
class TestCacheThreadSafety:
    """Test thread safety of cache operations."""

    def test_touch_cache_concurrent_calls(self):
        """Test that multiple touch_cache() calls don't cause issues."""
        import threading

        def touch_many():
            for _ in range(100):
                touch_cache()

        threads = [threading.Thread(target=touch_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        idle_time = get_cache_idle_time()
        assert idle_time >= 0

    def test_clear_cache_concurrent_calls(self):
        """Test that multiple clear_predictor_cache() calls don't cause issues."""
        import threading

        def clear_many():
            for _ in range(10):
                clear_predictor_cache()

        threads = [threading.Thread(target=clear_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        assert not is_initialized()
