# AcousticBrainz 2.0 — Design & Roadmap

## 1. Vision

- Reboot AcousticBrainz as a distributed tagging network producing shareable, reproducible audio descriptors.
- Support multiple ML frameworks (Essentia, PyTorch/CLAP, ONNX, future vendors) without rewriting downstream tooling.
- Ship modular inference runtimes as separate container images; avoid framework lock-in and dependency conflicts.
- Enable bring-your-own-models workflow via shared volume + manifest registry; push licensing burden to operators.
- Encode full provenance with every tag so results from different frameworks/models coexist safely.
- Reuse community-computed tags when confidence is sufficient; only recompute when necessary.

## 2. Guiding Principles

- **Framework neutrality**: Nothing in interfaces, storage, or analytics assumes a single inference stack.
- **Deterministic provenance**: Every tag traceable to framework, embedder, build ID, model head, head build ID.
- **Confidence-first decisions**: Low-variance, high-agreement results propagate; disagreements surfaced for review.
- **Modular runtimes**: Per-framework container images with pinned dependencies, strict version locking, offline-complete builds.
- **User-managed models**: Models live on shared volume; web UI guides operators through legal import, validates checksums, surfaces adoption stats.
- **Incremental evolution**: Keep existing Essentia pipeline running while adding adapters and provenance plumbing.
- **Reproducibility**: Checksum of configuration, model IDs, and parameters accompanies every tag emission.

## 3. Tag Namespace Specification

- **Format**: `nom:<framework>_<embedder>_<embedder_id>_<model>_<model_id>_<tag>`
- **Prefix**: Literal `nom:` namespace prefix shared by all framework families.
- **Fields**:
  - `<framework>` — inference stack identifier (`essentia`, `pytorch`, `tensorflow`, `onnx`, etc.).
  - `<embedder>` — backbone/representation generator (`effnet`, `maest`, `yamnet`, `clap-haiku`).
  - `<embedder_id>` — unique build or release ID for the embedder (`v2`, `2024-10-15`, commit hash, HF revision).
  - `<model>` — head or task-specific model (`mood`, `genre`, `era`, `bpm`).
  - `<model_id>` — build ID/version for the head (`discogs519`, `maest-30s`, `clap-laion-2024-05`).
  - `<tag>` — concrete tag key (`aggressive_high`, `mood_happy_high`, `probability`).
- **Example**: `nom:essentia_effnet_v1_mood_discogs519_aggressive_high`
- **Rules**:
  - Components are case-insensitive, ASCII, snake-case. Use hyphens only for upstream release IDs.
  - Avoid dots inside IDs; translate `1.2.3` → `1-2-3` to keep delimiter parsing consistent.
  - `_tag` component is whatever aggregation emits (tier labels, raw probability keys, etc.).
  - Writers must never mutate namespace components; they only append `_tag` values.
- **Backwards Compatibility**:
  - Historic tags (`essentia:*`) stay readable; analytics accept both formats.
  - Migration tooling maps legacy prefixes to new spec when re-tagging or refreshing entries.

## 4. Container Architecture

### 4.1 Split Inference Images

- **Base orchestrator**: Lightweight Python image (`nomarr-base`) hosting API, queue, DB, web UI, analytics—no ML dependencies.
- **Runtime images**: Per-framework containers (`nomarr-essentia`, `nomarr-pytorch`, `nomarr-onnx`) with pinned dependencies and GPU support.
- **Communication**: Base orchestrator dispatches inference requests to runtime containers via internal HTTP/gRPC; runtimes return normalized outputs.
- **Version locking**: Each runtime image pins exact versions of TensorFlow/PyTorch/ONNX + CUDA libs; Dockerfile checksums ensure reproducibility.
- **Offline packaging**: Runtime images built with all dependencies baked in; no internet required at deploy time (models excepted).

### 4.2 Model Management (Shared Volume)

- **Storage**: Models live on host volume mounted into both base and runtime containers (e.g., `/models`).
- **Manifest registry**: YAML/TOML files in `config/models/` declare allowed models with metadata:
  - Provider name, runtime requirement, expected file structure, SHA256 checksums, output schema, licence URL.
- **Web UI model manager**: First-class interface for operators (not CLI):
  - **Catalog view**: List available models with runtime, licence, size, supported tasks, install status.
  - **Detail panel**: Per-model stats from tagging telemetry—consensus delta, user feedback counts, confidence histograms, adoption rate.
  - **Guided import**: Step-by-step checklist for downloading/extracting models; displays licence terms, curl/git-lfs commands, validation steps.
  - **Validation**: Web UI verifies checksums against manifest, reports missing files, flags version mismatches.
- **Telemetry pipeline**: Track per-job model IDs, collect crowd feedback ("incorrect tag" flags), aggregate nightly for web UI metrics.
- **Discovery**: Base orchestrator scans `/models` on startup, loads manifests for present models only; runtimes expose capabilities via API.

### 4.3 Deployment Strategy

- **Docker Compose**: Multi-container setup with base + selected runtime(s); shared network and volumes.
- **No DIND**: Avoid docker-in-docker; operators run `docker compose up` on host.
- **GPU passthrough**: Runtime containers use `--gpus all` or device-specific mounts; VRAM monitored per container.
- **Graceful degradation**: Base orchestrator functions without runtimes (queue management, analytics); inference requests fail-fast if no runtime available.

## 5. Architectural Pillars

- **Model Discovery & Registry**
  - Discover embeddings/heads from filesystem + manifest metadata.
  - Record framework + build IDs in registry consumed by inference adapters and writers.
  - Web UI surfaces registry as browsable catalog with rich metadata.
- **Inference Adapters**
  - Thin wrappers normalizing outputs to `dict[str, list[float]]` schema plus variance data.
  - Essentia adapter in place; CLAP/PyTorch adapter next, ONNX follow-on.
  - Adapters live in runtime containers; base orchestrator only sees normalized outputs.
- **Tag Aggregation & Provenance**
  - Extend aggregators to accept provenance bundle (namespace prefix, model metadata, confidence metrics).
  - Emit tiers and raw scores under new namespace.
- **Distribution & Reuse**
  - AcousticID/Chromaprint matching exposes previously computed tags.
  - Confidence aggregation across frameworks guides reuse vs recompute.
- **APIs & Tooling**
  - HTTP/CLI surfaces provide unified views regardless of framework.
  - Navidrome and analytics need namespace-aware queries and presentation.

## 6. Essentia Model Strategy

**Current state**: Discogs-EffNet embeddings feed the entire production pipeline (binary mood heads, MTG-Jamendo multi-label heads, instrumentation, Navidrome exports). VRAM footprint stays under ~120 MB per worker and the tier aggregation math is well-characterised.

**Decision (2025‑11‑10)**:

1. **Hold the line on Discogs-EffNet for production tagging.** Swapping embedder/backbone is postponed until the modular runtime work is finished and burnout recovery period is over.
2. **Treat MAEST as an optional future experiment.** MAEST provides stronger genre embeddings, but Essentia does not ship MAEST mood heads, so adopting it today would break mood tiers or force custom training.
3. **Document the viable Essentia backbones and their trade-offs.**
   - `discogs-effnet` — best balance of VRAM and music-specific accuracy; production default.
   - `audioset-vggish` / `audioset-yamnet` — light general-audio embedders; useful for diagnostics only.
   - `msd-musicnn` — tiny footprint, lower recall; keep for edge devices.
   - `openl3-music-mel128-emb512` — largest VRAM hit; reserve for research jobs.

**Future experiments (deferred)**:

- Evaluate MAEST embeddings + genre heads inside a dedicated runtime once split-container architecture exists.
- Commission or train MAEST-based mood heads if community contributors appear.
- Benchmark alternate backbones (CLAP, OpenL3) against Discogs-EffNet using telemetry once the metrics pipeline lands.

## 7. Roadmap (Sequential Milestones)

### Phase 1: Foundation (Current Focus)

1. **Discogs-EffNet Baseline Hardening**

- Confirm manifests/checksums for existing Discogs-EffNet models.
- Capture telemetry benchmarks (VRAM, latency, tier agreement) to compare against future experiments.
- Ship client-only build for production use while planning refactor.

2. **Burnout Recovery Period**
   - Use current system in production to identify pain points.
   - Document operator feedback on model management UX.
   - Gather telemetry on tag confidence and user corrections.

### Phase 2: Modular Runtime (Post-Recovery)

3. **Container Split Design**

   - Finalize base orchestrator vs runtime image boundaries.
   - Define inference API contract (request schema, response format, health checks).
   - Prototype `nomarr-essentia` runtime image with MAEST models.

4. **Model Manager Web UI**

   - Build catalog/detail views consuming manifest registry.
   - Implement guided import workflow with licence display.
   - Wire telemetry pipeline for consensus stats and feedback aggregation.

5. **Namespace Migration**
   - Update writers to emit `nom:*` tags alongside `essentia:*`.
   - Migrate analytics and Navidrome integration to handle both formats.
   - Provide migration script for existing DB entries.

### Phase 3: Multi-Framework (Future)

6. **CLAP/PyTorch Runtime**

   - Build `nomarr-pytorch` image with CLAP dependencies.
   - Implement adapter converting cosine similarities to probabilities.
   - Extend tier aggregation to handle contrastive model outputs.

7. **Distributed Tag Reuse**

   - Integrate AcousticID/Chromaprint matching service.
   - Confidence aggregation logic across frameworks.
   - Define thresholds for reuse vs recompute.

8. **Community & API Extensions**
   - Public API endpoints for submitting/retrieving/voting on tags.
   - Publish roadmap, API reference, onboarding guide.

## 8. Immediate Next Steps (Pre-Burnout Recovery)

- ✅ Lock in roadmap document with split images, model management, Discogs-EffNet focus.
- 🔄 Record production baselines: VRAM usage, latency, tier agreement stats for Discogs-EffNet pipeline.
- 🔄 Deploy client-only build for personal use; gather real-world usage and operator feedback.
- ⏳ Take break from major refactoring; return when ready to tackle modular runtime work.

## 9. Open Questions

- Manifest schema finalization: required fields, versioning strategy, checksum format?
- Web UI tech stack: enhance existing vanilla JS or adopt React/Vue/Svelte?
- Telemetry opt-in/opt-out: privacy controls for crowd feedback collection?
- Runtime API protocol: REST vs gRPC vs custom binary protocol?

---

_Maintained by: @xiaden & GitHub Copilot Agent_
_Last Updated: 2025-11-09_
