# ML Subsystem

Machine learning pipeline for audio analysis: load audio, preprocess into spectrograms, run ONNX inference, and store embedding vectors.

## Responsibilities

- Audio loading and preprocessing (waveform → mel spectrogram → patches)
- ONNX Runtime model management (session lifecycle, caching, device placement)
- Backbone embedding extraction and head classification/regression
- Score calibration and mood tier aggregation
- GPU/VRAM resource coordination across worker fleet
- Embedding vector storage with hot/cold tiered collections

## Pipeline Architecture

```
audio/ → onnx/ (backbone) → inference/ → onnx/ (heads) → vectors/
  │           │                  │             │              │
  load        session mgmt       embed          classify      persist
  preprocess  model discovery    segment        regress       promote
  fingerprint device placement   pool scores    decide tiers  index
```

## Subfolders

| Folder | Purpose |
|--------|----------|
| `audio/` | Audio loading (Essentia MonoLoader), mel spectrogram preprocessing, chromaprint |
| `calibration/` | Score calibration (p5/p95 normalization), calibration state persistence |
| `inference/` | Backbone embedding, head predictions, segment statistics, mood decisions |
| `onnx/` | ONNX Runtime session management, model discovery, caching, base classes |
| `resources/` | VRAM coordination, capacity probing, tier selection, worker context |
| `vectors/` | Embedding pooling, hot/cold vector storage, promotion, index maintenance |

## Architectural Rules

- **Essentia isolation:** Only `audio/ml_audio_comp.py` and `audio/ml_preprocess_comp.py` import Essentia. All other ML code uses ONNX Runtime.
- **ONNX as backend:** All model inference runs through ONNX Runtime (`onnx/`). No TensorFlow, no direct Essentia inference.
- **Components call persistence directly** — no intermediate service layer for DB access.

## Dependencies

- **Upstream:** Called by `workflows/` (ML tagging, calibration, vector promotion)
- **Downstream:** Calls `persistence/` for DB reads/writes, `helpers/` for paths and DTOs
- **External:** `onnxruntime`, `essentia` (isolated), `numpy`
