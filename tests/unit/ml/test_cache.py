"""
Unit tests for nomarr.ml.cache module.

Tests use REAL fixtures from conftest.py - no redundant mocks.
"""

import pytest

from nomarr.ml.cache import (
    check_and_evict_idle_cache,
    clear_predictor_cache,
    get_cache_idle_time,
    get_cache_size,
    is_initialized,
    touch_cache,
    warmup_predictor_cache,
)

# === STANDALONE FUNCTION TESTS ===


@pytest.mark.skip(reason="Requires HeadInfo parameter - needs model fixture")
def test_cache_key():
    """Unique cache key for a head across backbones/types."""
    # TODO: Create mock HeadInfo and test cache_key generation
    pass


def test_check_and_evict_idle_cache():
    """Check if cache has been idle longer than timeout and evict if needed."""
    # Arrange

    # Act
    check_and_evict_idle_cache()

    # Assert
    # TODO: Add assertions
    pass


def test_clear_predictor_cache():
    """Clear the predictor cache and free GPU memory."""
    # Arrange

    # Act
    clear_predictor_cache()

    # Assert
    # TODO: Add assertions
    pass


def test_get_cache_idle_time():
    """Get the number of seconds since last cache access."""
    # Arrange

    # Act
    get_cache_idle_time()

    # Assert
    # TODO: Add assertions
    pass


def test_get_cache_size():
    """Return number of predictors in cache."""
    # Arrange

    # Act
    get_cache_size()

    # Assert
    # TODO: Add assertions
    pass


def test_is_initialized():
    """Check if cache has been initialized."""
    # Arrange

    # Act
    is_initialized()

    # Assert
    # TODO: Add assertions
    pass


def test_touch_cache():
    """Update the last access time for the cache."""
    # Arrange

    # Act
    touch_cache()

    # Assert
    # TODO: Add assertions
    pass


def test_warmup_predictor_cache():
    """Pre-load all model predictors into cache to avoid loading overhead during processing."""
    # Arrange
    models_dir = "models"  # Mock directory
    cache_idle_timeout = 300
    cache_auto_evict = True

    # Act
    # Note: Will fail if models_dir doesn't exist, but tests function signature
    try:
        warmup_predictor_cache(
            models_dir=models_dir,
            cache_idle_timeout=cache_idle_timeout,
            cache_auto_evict=cache_auto_evict,
        )
    except Exception:
        pass  # Expected to fail without real models

    # Assert
    # TODO: Add assertions with proper fixtures
    pass
