"""
Test audio fixture generator.

Generates minimal valid audio files for testing without requiring external files.
Uses pure Python (wave module) to create test audio files programmatically.
"""

import os
import struct
import wave


def generate_sine_wave(frequency: float, duration: float, sample_rate: int = 44100, amplitude: float = 0.5) -> bytes:
    """
    Generate a sine wave as raw PCM audio data.

    Args:
        frequency: Frequency in Hz
        duration: Duration in seconds
        sample_rate: Sample rate in Hz
        amplitude: Amplitude (0.0 to 1.0)

    Returns:
        Raw PCM audio data (16-bit signed integers, mono)
    """
    import math

    num_samples = int(sample_rate * duration)
    audio_data = []

    for i in range(num_samples):
        t = i / sample_rate
        value = amplitude * math.sin(2 * math.pi * frequency * t)
        # Convert to 16-bit signed integer
        sample = int(value * 32767)
        audio_data.append(struct.pack("<h", sample))  # Little-endian signed short

    return b"".join(audio_data)


def create_wav_file(output_path: str, duration: float = 8.0, frequency: float = 440.0) -> str:
    """
    Create a WAV file with a sine wave.

    Args:
        output_path: Path to save WAV file
        duration: Duration in seconds (minimum 7s for nomarr min_duration)
        frequency: Frequency in Hz (440 Hz = A4 note)

    Returns:
        Absolute path to created file
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    sample_rate = 44100
    num_channels = 1  # Mono
    sample_width = 2  # 16-bit

    # Generate audio data
    audio_data = generate_sine_wave(frequency, duration, sample_rate)

    # Write WAV file
    with wave.open(output_path, "wb") as wav_file:
        wav_file.setnchannels(num_channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data)

    return os.path.abspath(output_path)


def create_test_fixtures(fixtures_dir: str = "tests/fixtures") -> dict[str, str]:
    """
    Create all test audio fixtures.

    Returns:
        Dictionary mapping fixture names to file paths
    """
    fixtures = {}

    # Create fixtures directory
    os.makedirs(fixtures_dir, exist_ok=True)

    # Test file 1: Basic 8-second file (A440)
    fixtures["basic"] = create_wav_file(os.path.join(fixtures_dir, "test_basic.wav"), duration=8.0, frequency=440.0)

    # Test file 2: Longer 15-second file (C523 - middle C)
    fixtures["long"] = create_wav_file(os.path.join(fixtures_dir, "test_long.wav"), duration=15.0, frequency=523.25)

    # Test file 3: Short 5-second file (below min_duration)
    fixtures["short"] = create_wav_file(os.path.join(fixtures_dir, "test_short.wav"), duration=5.0, frequency=330.0)

    # Test file 4: Different frequency for variety (E659)
    fixtures["variety"] = create_wav_file(
        os.path.join(fixtures_dir, "test_variety.wav"), duration=10.0, frequency=659.25
    )

    # Create a README to explain these files
    readme_path = os.path.join(fixtures_dir, "README.md")
    with open(readme_path, "w") as f:
        f.write("""# Test Audio Fixtures

These are programmatically generated WAV files used for testing.

**Files:**
- `test_basic.wav` - 8s, 440 Hz (A4), standard test file
- `test_long.wav` - 15s, 523.25 Hz (C5), longer processing test
- `test_short.wav` - 5s, 330 Hz (E4), below min_duration test
- `test_variety.wav` - 10s, 659.25 Hz (E5), variety test

**Generation:**
These files are generated using pure Python (wave module) with sine waves.
No external audio files or dependencies required.

**License:**
Generated test data - no copyright restrictions.

**Regeneration:**
Run `python tests/fixtures/generate.py` to regenerate all fixtures.
""")

    return fixtures


if __name__ == "__main__":
    # Generate fixtures when run directly
    fixtures = create_test_fixtures()
    print("Generated test fixtures:")
    for name, path in fixtures.items():
        size = os.path.getsize(path)
        print(f"  {name}: {path} ({size:,} bytes)")
