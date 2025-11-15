"""
Test audio fixture generator.

Generates minimal valid MP3 audio files for integration testing.
Uses pydub to create MP3 files programmatically (requires ffmpeg).
"""

import os

try:
    from pydub.generators import Sine

    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False


def generate_sine_tone_mp3(output_path: str, duration_ms: int = 65000, frequency: float = 440.0) -> str:
    """
    Create an MP3 file with a sine wave tone.

    Args:
        output_path: Path to save MP3 file
        duration_ms: Duration in milliseconds (default 65s to exceed 60s minimum)
        frequency: Frequency in Hz (440 Hz = A4 note)

    Returns:
        Absolute path to created file
    """
    if not PYDUB_AVAILABLE:
        raise ImportError("pydub is required for MP3 generation. Install with: pip install pydub")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Generate sine wave
    sine_wave = Sine(frequency).to_audio_segment(duration=duration_ms)

    # Export as MP3
    sine_wave.export(output_path, format="mp3", bitrate="192k")

    return os.path.abspath(output_path)


def create_test_fixtures(fixtures_dir: str = "tests/fixtures") -> dict[str, str]:
    """
    Create all test audio fixtures as MP3 files.

    Returns:
        Dictionary mapping fixture names to file paths
    """
    if not PYDUB_AVAILABLE:
        print("WARNING: pydub not available, cannot generate MP3 fixtures")
        print("Install with: pip install pydub")
        print("Also requires ffmpeg to be installed on system")
        return {}

    fixtures = {}

    # Create fixtures directory
    os.makedirs(fixtures_dir, exist_ok=True)

    # Test file 1: Basic 65-second file (just over 60s minimum)
    fixtures["basic"] = generate_sine_tone_mp3(
        os.path.join(fixtures_dir, "test_basic.mp3"),
        duration_ms=65000,  # 65 seconds
        frequency=440.0,  # A4
    )

    # Test file 2: Longer 90-second file
    fixtures["long"] = generate_sine_tone_mp3(
        os.path.join(fixtures_dir, "test_long.mp3"),
        duration_ms=90000,  # 90 seconds
        frequency=523.25,  # C5
    )

    # Test file 3: Short 30-second file (below 60s minimum)
    fixtures["short"] = generate_sine_tone_mp3(
        os.path.join(fixtures_dir, "test_short.mp3"),
        duration_ms=30000,  # 30 seconds
        frequency=330.0,  # E4
    )

    # Test file 4: Different frequency for variety (120 seconds)
    fixtures["variety"] = generate_sine_tone_mp3(
        os.path.join(fixtures_dir, "test_variety.mp3"),
        duration_ms=120000,  # 120 seconds (2 minutes)
        frequency=659.25,  # E5
    )

    # Create a README to explain these files
    readme_path = os.path.join(fixtures_dir, "README.md")
    with open(readme_path, "w") as f:
        f.write("""# Test Audio Fixtures

These are programmatically generated MP3 files used for integration testing.

**Files:**
- `test_basic.mp3` - 65s, 440 Hz (A4), standard test file (just over 60s minimum)
- `test_long.mp3` - 90s, 523.25 Hz (C5), longer processing test
- `test_short.mp3` - 30s, 330 Hz (E4), below min_duration test
- `test_variety.mp3` - 120s, 659.25 Hz (E5), variety test

**Generation:**
These files are generated using pydub with sine waves.
Requires: pydub and ffmpeg

**License:**
Generated test data - no copyright restrictions.

**Regeneration:**
Run `python tests/fixtures/generate.py` to regenerate all fixtures.
Note: Requires pydub and ffmpeg installed.
""")

    return fixtures


if __name__ == "__main__":
    # Generate fixtures when run directly
    fixtures = create_test_fixtures()
    if fixtures:
        print("Generated test fixtures:")
        for name, path in fixtures.items():
            size = os.path.getsize(path)
            print(f"  {name}: {path} ({size:,} bytes)")
    else:
        print("Failed to generate fixtures - pydub not available")
