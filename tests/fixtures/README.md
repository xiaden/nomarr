# Test Audio Fixtures

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
