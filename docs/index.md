# Nomarr Documentation

**Audience:** Users, administrators, and developers working with Nomarr.

Nomarr is an AI-powered audio tagging system that automatically analyzes music files and writes mood, genre, and other descriptive tags. It integrates with music managers like Lidarr and Navidrome.

> **⚠️ Pre-Alpha Software**  
> Nomarr is under active development. APIs, schemas, and workflows may change without notice. See the main [README](../readme.md) for current status and roadmap.

## Documentation Structure

### Getting Started

- **[Getting Started Guide](getting_started.md)** - Installation, configuration, and basic usage
- **[Deployment Guide](deployment.md)** - Docker setup and production deployment

### API Reference

- **[API Overview](api/index.md)** - HTTP and CLI interfaces
- **[HTTP Endpoints](api/endpoints.md)** - REST API reference
- **[Lidarr Integration](integration/lidarr.md)** - Post-import hook setup

### Architecture

- **[Architecture Overview](architecture/overview.md)** - System design and layer responsibilities
- **[Workflows](architecture/workflows.md)** - Core processing workflows
- **[Naming Conventions](architecture/naming_conventions.md)** - Code and tag naming standards
- **[Versioning](architecture/versioning.md)** - Model and tag versioning system

### Integration

- **[Navidrome Integration](integration/navidrome.md)** - Smart playlists and web UI integration
- **[Lidarr Integration](integration/lidarr.md)** - Automated tagging for new imports

### Calibration

- **[Calibration System](calibration/index.md)** - Tag calibration and threshold tuning

### Quality Control

- **[QC System](qc/qc_system.md)** - Quality control framework
- **[QC Tools](qc/tools.md)** - Scripts and utilities for code quality

### Developer Tools

- **[API Discovery Tools](tools/api_discovery.md)** - Tools for exploring module APIs and imports

### Reference

- **[Essentia Models](upstream/modelsinfo.md)** - Upstream Essentia model documentation (reference only)

## Quick Links

- Main repository: [GitHub](https://github.com/xiaden/nomarr)
- Issue tracker: [GitHub Issues](https://github.com/xiaden/nomarr/issues)
- Root README: [../readme.md](../readme.md)

## Documentation Conventions

- **Configuration paths** are shown relative to the config directory (default: `/app/config`)
- **Tag examples** use `nom:` namespace by default, but the actual namespace is configurable
- **Code examples** assume you're in the repository root directory
- **Architecture diagrams** use → to show dependency direction (caller → callee)
