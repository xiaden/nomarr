# Versioning Strategy

Nomarr uses **semantic versioning** (SemVer): `MAJOR.MINOR.PATCH`

## Version Format

`MAJOR.MINOR.PATCH` (e.g., `1.2.3`)

- **MAJOR**: Breaking changes that require user action (API changes, data structure changes, config format changes)
- **MINOR**: New features that are backward compatible (new endpoints, new config options with defaults)
- **PATCH**: Bug fixes and improvements that are backward compatible

## Pre-Release Status

Current status: **Pre-Alpha (0.x.x)**

- `0.x.x` versions are considered unstable and may have breaking changes between minor versions
- Once stable: `1.0.0` will mark the first production-ready release
- After `1.0.0`: Strict SemVer adherence (no breaking changes without major bump)

## Version Location

**Single source of truth**: `nomarr/__version__.py`

```python
__version__ = "0.1.0"
```

This is imported by:

- `nomarr/services/config.py` → `tagger_version` config key
- CI/CD workflows for Docker image tagging
- Documentation generation

**Do not edit** `tagger_version` in `config.yaml` - it's overridden by code.

## Bumping Versions

### When to Bump

**MAJOR (Breaking Changes)**:

- Database schema changes requiring migration
- API endpoint signature changes (parameters removed/renamed)
- Config file format changes (keys removed/renamed)
- Tag format changes (namespace changes, key structure changes)

**MINOR (New Features)**:

- New API endpoints
- New config options (with sensible defaults)
- New tag categories
- New CLI commands
- New calibration metrics
- Library scanner features

**PATCH (Bug Fixes)**:

- Fix incorrect behavior
- Performance improvements
- Documentation updates
- Dependency updates (no breaking changes)
- Linting/formatting fixes

### How to Bump

1. **Edit `nomarr/__version__.py`**:

   ```python
   __version__ = "0.2.0"  # Increment version
   ```

2. **Update version history comment**:

   ```python
   # Version history:
   # 0.2.0 - Added XYZ feature
   #         - Fixed ABC bug
   # 0.1.0 - Initial pre-alpha release
   ```

3. **Commit with descriptive message**:

   ```bash
   git add nomarr/__version__.py
   git commit -m "Bump version to 0.2.0

   Added:
   - Feature X
   - Feature Y

   Fixed:
   - Bug Z"
   ```

4. **Push to trigger CI**:

   ```bash
   git push origin main
   ```

5. **CI automatically**:
   - Detects version change
   - Builds Docker image
   - Tags with version: `v0.2.0`, `latest`, and commit SHA
   - Publishes to GitHub Container Registry

## Docker Image Tags

When version changes are detected, CI publishes three tags:

1. **`latest`** - Always points to the most recent version
2. **`v{VERSION}`** - Specific version (e.g., `v0.2.0`)
3. **`{SHA}`** - Specific commit (for reproducibility)

**Note**: Docker images are **only published when version changes** (not on every commit).

## CI Behavior

### When CI Runs

CI runs when these files/directories change:

- `nomarr/**` - Source code
- `tests/**` - Tests
- `scripts/**` - Build/utility scripts
- `config/**` - Configuration files
- `dockerfile` - Docker build
- `requirements.txt` - Dependencies
- `pytest.ini`, `ruff.toml` - Tooling config

### When CI Skips

CI **does not run** when only these change:

- `docs/**` - Documentation
- `README.md`, `*.md` - Markdown files
- `.gitignore`, `.dockerignore` - Git metadata

This saves CI resources and avoids unnecessary Docker builds.

### What CI Does

1. **Detect version** from `nomarr/__version__.py`
2. **Check if version changed** (compare to previous commit)
3. **Build Docker image** (always, for testing)
4. **Run pytest** inside container (always)
5. **Publish to registry** (only if version changed)

## Tag Management

### Git Tags

Consider creating Git tags for releases:

```bash
# After bumping version to 0.2.0 and pushing
git tag -a v0.2.0 -m "Release 0.2.0: Feature X, Bug Fix Y"
git push origin v0.2.0
```

This creates a GitHub release that users can reference.

### Tag Cleanup

Old `:latest` Docker images are overwritten (not cumulative).
Versioned tags (`:v0.1.0`, `:v0.2.0`) persist indefinitely.

To clean up old tags:

```bash
# Delete local tag
git tag -d v0.1.0

# Delete remote tag
git push origin :refs/tags/v0.1.0
```

## Examples

### Example: Bug Fix (Patch)

Fixed a bug where calibration metrics were miscalculated.

```python
# Before: nomarr/__version__.py
__version__ = "0.1.0"

# After: nomarr/__version__.py
__version__ = "0.1.1"

# Version history:
# 0.1.1 - Fixed calibration JSD calculation (scipy.stats import error)
# 0.1.0 - Initial pre-alpha release
```

```bash
git commit -m "Bump version to 0.1.1 - Fix calibration JSD bug"
git push
# CI publishes: v0.1.1, latest, {sha}
```

### Example: New Feature (Minor)

Added Navidrome playlist generation feature.

```python
# Before: nomarr/__version__.py
__version__ = "0.1.1"

# After: nomarr/__version__.py
__version__ = "0.2.0"

# Version history:
# 0.2.0 - Added Navidrome Smart Playlist generation
#         - New /admin/navidrome/playlists/* endpoints
# 0.1.1 - Fixed calibration JSD calculation
```

```bash
git commit -m "Bump version to 0.2.0 - Add Navidrome integration"
git push
# CI publishes: v0.2.0, latest, {sha}
```

### Example: Breaking Change (Major, post-1.0)

Changed database schema (hypothetical future change).

```python
# Before: nomarr/__version__.py
__version__ = "1.5.3"

# After: nomarr/__version__.py
__version__ = "2.0.0"

# Version history:
# 2.0.0 - BREAKING: Database schema v2 (requires migration)
#         - Added library_files.genre_cache column
#         - Migration script: scripts/migrate_db_v2.py
```

**User action required**: Run migration script before updating.

## Checking Current Version

### In Code

```python
from nomarr.__version__ import __version__
print(__version__)  # "0.1.0"
```

### In Container

```bash
docker run --rm nomarr python3 -c "from nomarr.__version__ import __version__; print(__version__)"
```

### From Git

```bash
git describe --tags --always
```

## Future Enhancements

- [ ] Automated changelog generation from git commits
- [ ] GitHub Releases with attached binaries/docs
- [ ] Version check endpoint: `GET /api/v1/version`
- [ ] Migration scripts for major version bumps
- [ ] Rollback instructions in release notes
