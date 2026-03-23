# Nomarr

**Intelligent audio auto-tagging for your music library using state-of-the-art machine learning.**

!!! warning "Alpha Software"
    Nomarr is under active development. Breaking changes can occur in any release before 1.0.
    Database schema changes include forward-only migrations that auto-apply on startup.
    APIs and workflows may change. Back up before updating.

---

## What Is Nomarr?

Nomarr analyzes your music files with machine learning and writes rich metadata tags directly into your audio files — MP3, M4A, FLAC, OGG, Opus, WAV, AAC, AIFF, and more.

**Technology stack:**

- **ML Inference** — ONNX Runtime for fast, portable model execution (GPU-accelerated when available)
- **Audio Loading** — Custom Essentia build for audio decoding and mel spectrogram preprocessing
- **Database** — ArangoDB for graph-aware metadata storage and querying
- **Deployment** — Docker with optional GPU passthrough for production use

Perfect for organizing large libraries, discovering moods and genres, and enriching metadata for music servers like Navidrome and Plex.

---

## For Users

Get started with installation, configuration, and day-to-day usage:

- **[Getting Started](user/getting_started.md)** — Installation, configuration, and first-time setup
- **[Deployment Guide](user/deployment.md)** — Docker deployment, GPU setup, production configuration
- **[Navidrome Integration](user/navidrome.md)** — Smart playlists and web UI integration
- **[Playlist Import](user/playlist_import.md)** — Convert Spotify/Deezer playlists to M3U

!!! tip "API Documentation"
    Nomarr exposes interactive API docs via FastAPI's built-in Swagger UI.
    Once the server is running, visit **`/docs`** for the full endpoint reference.

---

## For Developers

Technical architecture and implementation details:

- **[Architecture Overview](dev/architecture.md)** — System design, layering, and dependency rules
- **[Domains](dev/domains.md)** — Domain boundaries and responsibilities
- **[Services Layer](dev/services.md)** — Service responsibilities and public APIs
- **[Workers & Lifecycle](dev/workers.md)** — Worker processes, health system, and lifecycle semantics
- **[Health System](dev/health.md)** — Health table invariants and state machine
- **[StateBroker](dev/statebroker.md)** — Real-time state management and DTO contracts
- **[Naming Standards](dev/naming.md)** — Enforced naming conventions for services, methods, and DTOs
- **[Migrations](dev/migrations.md)** — Database migration system architecture and conventions
- **[Vector Stores](dev/vector-stores.md)** — Embedding storage and similarity search
- **[Versioning](dev/versioning.md)** — Model and tag versioning strategy
- **[QC System](dev/qc.md)** — Quality control tools, linting, and architecture enforcement

**Reference:**

- [Calibration Troubleshooting](dev/calibration-troubleshooting.md)
- [MCP Config Defaults](dev/mcp-config-defaults.md)
- [MCP Config Examples](dev/mcp-config-examples.md)
- [MUI Integration](dev/mui-integration.md)
- [Server File Picker](dev/server-file-picker.md)

---

## Links

- **Repository:** [github.com/xiaden/nomarr](https://github.com/xiaden/nomarr)
- **Issues:** [GitHub Issues](https://github.com/xiaden/nomarr/issues)
- **Contributing:** See [CONTRIBUTING.md](https://github.com/xiaden/nomarr/blob/main/CONTRIBUTING.md) in the repository root
