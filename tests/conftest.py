"""Pytest fixtures for test data."""

from pathlib import Path

import pytest


@pytest.fixture
def good_library_root():
    """Path to good test library with valid structure."""
    return Path(__file__).parent / "fixtures" / "library" / "good"


@pytest.fixture
def bad_library_root():
    """Path to bad test library for negative tests."""
    return Path(__file__).parent / "fixtures" / "library" / "bad"


@pytest.fixture
def good_library_paths(good_library_root):
    """Dictionary of known good library paths."""
    return {
        "root": good_library_root,
        "rock_beatles": good_library_root / "Rock" / "Beatles",
        "jazz_miles": good_library_root / "Jazz" / "Miles",
        "classical_bach": good_library_root / "Classical" / "Bach",
        "files": {
            "help": good_library_root / "Rock" / "Beatles" / "help.mp3",
            "yesterday": good_library_root / "Rock" / "Beatles" / "yesterday.mp3",
            "so_what": good_library_root / "Jazz" / "Miles" / "so_what.flac",
            "blue_in_green": good_library_root / "Jazz" / "Miles" / "blue_in_green.mp3",
            "fugue": good_library_root / "Classical" / "Bach" / "fugue.flac",
            "prelude": good_library_root / "Classical" / "Bach" / "prelude.mp3",
        },
    }
