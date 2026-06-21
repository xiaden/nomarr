# ADR-035: Essentia as the Audio DSP and Preprocessing Backend

**Status:** Accepted  
**Date:** 2026-06-18  
**Tags:** audio, dependencies, preprocessing, dsp  
**Source Log:** agent#L47  

## Context

Nomarr uses Essentia for two purposes, isolated to two files under the existing Essentia isolation rule:

1. **Audio loading** (`ml_audio_comp.py`): `MonoLoader` — ffmpeg decode → mono downmix → libsamplerate resample (quality=4), all in one C++ call. Handles MP3, M4A, FLAC, OGG, WAV, and anything ffmpeg can decode.
2. **Mel spectrogram preprocessing** (`ml_preprocess_comp.py`): `Windowing`(Hann) → `Spectrum`(FFTW3) → `MelBands` → `UnaryOperator`(log compression), with numerically-verified parameters for four backbones (effnet, musicnn, vggish, yamnet).

The preprocessing parameters are validated against Essentia's own `TensorflowInputMusiCNN.cpp` and `TensorflowInputVGGish.cpp` upstream source — the models were trained on Essentia-preprocessed audio, and Nomarr's preprocessing produces identical output. Essentia is built from source as a custom minimal build (audio I/O + DSP algorithms only; no TensorFlow, Gaia, Vamp, or extractors).

This pipeline achieves ~20 songs/minute through 2 embedders and 12 classifiers.

We evaluated librosa and madmom as potential replacements or additions to the audio preprocessing stack.

## Decision

**Essentia remains the sole audio DSP and preprocessing backend.** Neither librosa nor madmom will be adopted.

### librosa — Rejected as replacement

librosa was evaluated as a potential Essentia replacement. Three blockers:

1. **FFT performance.** librosa uses SciPy's fftpack; Essentia uses FFTW3 (or Accelerate on macOS). For Nomarr's throughput, where every frame of every song hits the FFT with window sizes of 400–512 samples, the FFT is the bottleneck. SciPy's fftpack is measurably slower.

2. **Audio loading overhead.** librosa uses `soundfile` (libsndfile) for WAV/FLAC/OGG but falls back to `audioread` for MP3/M4A, which shells out to ffmpeg as a subprocess. Essentia's `MonoLoader` calls libav* directly in-process. For batch loading, this adds subprocess spawn overhead per file.

3. **Numerical non-equivalence.** Nomarr's preprocessing parameters are validated against Essentia's C++ output. librosa's mel implementation uses different defaults (Slaney mel scale, different normalization conventions). Getting pixel-identical output would require parameter archaeology — a research project, not a library swap. Even sub-percent differences in mel bin values, compounded across 96 bins × 187 frames × multiple classifiers, could silently shift predictions.

librosa was also evaluated for onset detection and tempo estimation. Signal-processing-based onset detection has an F-measure of ~0.70–0.80; tempo estimation has a 15–25% octave error rate. Neither meets the reliability bar Nomarr requires for automated metadata. Onset detection will instead use existing effnet embeddings for silence/song-start suppression. Tempo estimation is deferred.

### madmom — Rejected

madmom's supervised CNN/RNN models achieve better onset detection (F1 ~0.85–0.93) and tempo estimation (Acc1 ~0.83–0.87) than signal-processing approaches. Rejected because onset detection is solved more simply via effnet embeddings, and tempo estimation carries dependency weight for a feature not currently needed.

## Consequences

### What we gain

- **Verified, deterministic preprocessing.** The Essentia pipeline produces output numerically identical to what the models were trained on. No guesswork, no silent accuracy degradation.
- **High throughput.** In-process ffmpeg decode + FFTW3 FFT + C++ DSP chain. No subprocess overhead, no Python-level data transfers between pipeline stages.
- **No new dependencies.** The audio stack remains Essentia + numpy/scipy. No librosa, no madmom, no additional native libraries.
- **Clean isolation.** The two-file Essentia rule continues to contain the AGPL surface. Everything else uses the pure NumPy interfaces `load_audio_mono()` and `preprocess_for_backbone()`.

### What we lose

- **AGPL dependency.** Essentia is AGPLv3. The two-file isolation contains the legal surface, but the dependency persists. If it ever becomes a blocker, migration to librosa+soundfile is a documented path — just an expensive one requiring re-validation.
- **Custom build maintenance.** The minimal Essentia build (from `build_resources/essentia/`) must be maintained. This is a C++ build with waf, FFmpeg, FFTW3, and libsamplerate dependencies.
- **No onset detection or tempo estimation.** These features are not provided by Essentia in Nomarr's minimal build and will not be added via new libraries. Onset-like segmentation will use existing effnet embeddings. Tempo is deferred.
- **Vendor lock-in on preprocessing parameters.** The four backbone configurations in `ml_preprocess_comp.py` are tightly coupled to Essentia's specific mel filterbank implementation. Changing the backend requires re-validating all four.
