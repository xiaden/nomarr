#!/usr/bin/env python
"""Generate a deterministic 128 Hz sine-wave WAV file used as the VRAM-probe fixture.

Output: tests/fixtures/ml_probe_audio.wav
  - Sample rate : 16 000 Hz
  - Duration    : 20 s
  - Channels    : 1 (mono)
  - Bit depth   : 16-bit PCM (signed int16)
  - Frequency   : 128 Hz
  - Seed        : 42
"""

from __future__ import annotations

import pathlib

import numpy as np
import scipy.io.wavfile as wavfile

SAMPLE_RATE = 16_000
DURATION_S = 20
FREQUENCY_HZ = 128
AMPLITUDE = 0.9
SEED = 42

OUTPUT_PATH = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ml_probe_audio.wav"


def main() -> None:
    np.random.seed(SEED)

    n_samples = SAMPLE_RATE * DURATION_S
    t = np.linspace(0.0, DURATION_S, n_samples, endpoint=False)

    waveform = np.sin(2.0 * np.pi * FREQUENCY_HZ * t) * AMPLITUDE
    audio_int16 = (waveform * 32767).astype(np.int16)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(OUTPUT_PATH), SAMPLE_RATE, audio_int16)

    print(f"Written {OUTPUT_PATH}  ({n_samples} samples, {DURATION_S} s @ {SAMPLE_RATE} Hz)")


if __name__ == "__main__":
    main()
