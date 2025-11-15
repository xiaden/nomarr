# Test Audio Fixtures

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
