# ML Audio

Audio loading and preprocessing — the entry point of the ML pipeline.

## Responsibilities

- Load audio files as mono float32 waveforms via Essentia MonoLoader
- Compute mel spectrograms and extract patches for ONNX backbone input
- Generate chromaprint fingerprints for move detection
- Handle shutdown-aware loading and short-file filtering

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `ml_audio_comp` | Audio loading via Essentia MonoLoader (ffmpeg-backed), shutdown handling, duration checks |
 | `ml_preprocess_comp` | Mel spectrogram computation (Essentia Windowing → Spectrum → MelBands), patch extraction with per-backbone parameters |
 | `ml_chromaprint_comp` | Content-based audio fingerprinting (spectral hash) for file move detection |

## Patterns

- **Essentia isolation:** These are the ONLY two modules in the entire codebase that import Essentia (`ml_audio_comp` for MonoLoader, `ml_preprocess_comp` for mel spectrogram). All downstream processing uses ONNX.
- **Backbone-specific params:** `ml_preprocess_comp` resolves per-backbone preprocessing parameters (sample rate, n_mels, patch size) — effnet, musicnn, vggish, yamnet each have different settings.
- **Shutdown awareness:** `ml_audio_comp` accepts a stop event to abort long audio decodes during worker shutdown.

## Dependencies

- **Upstream:** Called by `inference/` (embedding pipeline) and `library/` (chromaprint for move detection)
- **Downstream:** Calls `helpers/` for LibraryPath validation
- **External:** `essentia.standard` (MonoLoader, Windowing, Spectrum, MelBands), `numpy`
