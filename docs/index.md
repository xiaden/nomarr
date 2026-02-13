# Nomarr Documentation

**Intelligent audio auto-tagging for your music library using state-of-the-art machine learning.**

Nomarr is an alpha audio tagging system that analyzes your music files with Essentia's pre-trained ML models and writes rich metadata tags directly into your audio files (MP3, M4A, FLAC, OGG, Opus, WAV, AAC, AIFF, and more). Perfect for organizing large libraries, discovering moods, and enriching metadata for music servers like Navidrome and Plex.

> **⚠️ Alpha Software**  
> Nomarr is under active development with daily breaking changes. No backward compatibility guarantees exist until version 1.0. Database schemas, APIs, and workflows may change without notice or migration paths.

---

## Documentation Structure

### 📘 User Documentation

Start here if you're installing or using Nomarr:

- **[Getting Started](user/getting_started.md)** - Installation, configuration, and first-time setup
- **[Deployment Guide](user/deployment.md)** - Docker deployment, GPU setup, production configuration
- **[API Reference](user/api_reference.md)** - HTTP endpoints for automation and integration
- **[Navidrome Integration](user/navidrome.md)** - Smart playlists and web UI integration
- **[Playlist Import](user/playlist_import.md)** - Convert Spotify/Deezer playlists to M3U

### 🔧 Developer Documentation

Technical architecture and implementation details:

- **[Architecture Overview](dev/architecture.md)** - System design, layering, and dependency rules
- **[Services Layer](dev/services.md)** - Service responsibilities and public APIs
- **[Workers & Lifecycle](dev/workers.md)** - Worker processes, health system, and lifecycle semantics
- **[Health System](dev/health.md)** - Health table invariants and state machine
- **[StateBroker](dev/statebroker.md)** - Real-time state management and DTO contracts
- **[Naming Standards](dev/naming.md)** - Enforced naming conventions for services, methods, and DTOs
- **[QC System](dev/qc.md)** - Quality control tools, linting, and architecture enforcement
- **[Versioning](dev/versioning.md)** - Model and tag versioning strategy

### 📚 Reference

- **[Essentia Models (Upstream)](upstream/modelsinfo.md)** - Reference documentation from Essentia project (not canonical)

---

## Quick Links

**Getting Started:**
- [Install with Docker](user/deployment.md#docker-setup)
- [First Library Scan](user/getting_started.md#scanning-your-library)
- [Web UI Overview](user/getting_started.md#web-interface)

**Integration:**
- [Navidrome Smart Playlists](user/navidrome.md#smart-playlists)

**Development:**
- [Architecture Principles](dev/architecture.md#core-principles)
- [Worker Lifecycle](dev/workers.md#lifecycle-semantics)
- [Adding a New Service](dev/services.md#creating-services)

**Resources:**
- Main repository: [GitHub](https://github.com/xiaden/nomarr)
- Issue tracker: [GitHub Issues](https://github.com/xiaden/nomarr/issues)
- Root README: [../readme.md](../readme.md)

---

## Contributing

See the main [README.md](../readme.md) for:
- Current development status
- Alpha warnings and limitations
- GPU requirements and performance characteristics
- How to report issues and submit pull requests

All contributions undergo human review and may be refactored before merge.

---

## Documentation Conventions

- **Configuration paths** are shown relative to the config directory (default: `/app/config`)
- **Tag examples** use the `nom:` namespace prefix
- **Code examples** assume you're in the repository root directory
- **Architecture diagrams** use → to show dependency direction (caller → callee)
