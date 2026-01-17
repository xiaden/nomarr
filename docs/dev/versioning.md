# Versioning Strategy

**How Nomarr manages versions, breaking changes, and CI/CD.**

---

## Overview

Nomarr uses **Semantic Versioning (SemVer)** with modifications for pre-alpha status.

**Current status: Pre-Alpha (0.x.x)**

- No backward compatibility guarantees
- Breaking changes allowed in minor versions
- Database schema can change without migrations
- Config format can change without migrations

**When 1.0.0 releases:**
- Strict SemVer enforced
- Migrations required for DB schema changes
- Backward compatibility maintained within major versions

---

## Semantic Versioning Format

```
MAJOR.MINOR.PATCH
```

### Version Components

**MAJOR (first number):**
- Breaking changes to public APIs
- Database schema changes requiring migrations
- Config format changes requiring manual updates
- Incompatible upgrades

**MINOR (second number):**
- New features (backward compatible)
- New API endpoints
- New CLI commands
- Performance improvements

**PATCH (third number):**
- Bug fixes only
- No new features
- No API changes
- Security patches

---

## Pre-Alpha Rules (0.x.x)

**Current version scheme: `0.MINOR.PATCH`**

### What the `0.x.x` prefix means:

- **No stability guarantees:** Breaking changes can happen in any release
- **No migrations:** Users may need to rebuild database or rescan library
- **No deprecation warnings:** Old features can be removed without notice
- **Rapid iteration:** Focus on architecture and features, not compatibility

### Version bumping in pre-alpha:

**0.x.0 (minor bump):**
- New major feature
- Significant architecture change
- Breaking database schema change
- Breaking config format change
- Breaking API change

**0.x.x (patch bump):**
- Bug fixes
- Small features
- Non-breaking improvements
- Documentation updates

### Examples:

```
0.1.0 → Initial release
0.2.0 → Added calibration system (new feature)
0.2.1 → Fixed calibration race condition (bug fix)
0.3.0 → Restructured queue system (breaking change)
0.3.1 → Fixed queue concurrency bug (bug fix)
```

---

## Post-1.0 Rules (Stable)

**When Nomarr reaches 1.0.0, strict SemVer applies:**

### Major version (1.x.x → 2.x.x):

**Allowed:**
- Remove endpoints
- Change response formats
- Rename database tables
- Remove config options
- Change CLI command syntax

**Required:**
- Migration guide
- Deprecation warnings in previous major version
- Clear upgrade path documented

### Minor version (1.1.x → 1.2.x):

**Allowed:**
- Add new endpoints
- Add optional config fields
- Add database columns (with defaults)
- Add CLI commands
- Performance improvements

**Not allowed:**
- Remove endpoints
- Remove config options
- Change required parameters
- Break existing workflows

### Patch version (1.1.1 → 1.1.2):

**Allowed:**
- Bug fixes only
- Security patches
- Documentation corrections
- Internal refactoring (no behavior change)

**Not allowed:**
- New features
- API changes
- Config changes
- New dependencies

---

## Version Bumping Process

### How to decide what version to bump:

**Step 1: Identify changes**

Classify each change:
- **Breaking:** Existing code/config/data will fail
- **Feature:** New capability added
- **Fix:** Bug corrected, no new behavior

**Step 2: Apply rules**

Pre-alpha (0.x.x):
- Any breaking change → bump MINOR
- Multiple fixes/small features → bump PATCH

Post-1.0:
- Any breaking change → bump MAJOR
- New features → bump MINOR
- Only fixes → bump PATCH

**Step 3: Update version**

Edit `nomarr/__version__.py`:

```python
__version__ = "0.3.1"
```

**Step 4: Tag release**

```bash
git tag -a v0.3.1 -m "Release 0.3.1: Fix queue concurrency bug"
git push origin v0.3.1
```

---

## Docker Image Tags

### Tagging Strategy

**Version tags:**
- `ghcr.io/nomarr/nomarr:0.3.1` - Specific version
- `ghcr.io/nomarr/nomarr:0.3` - Latest patch in 0.3.x
- `ghcr.io/nomarr/nomarr:0` - Latest version in 0.x.x
- `ghcr.io/nomarr/nomarr:latest` - Latest release

**Branch tags:**
- `ghcr.io/nomarr/nomarr:main` - Latest commit on main branch
- `ghcr.io/nomarr/nomarr:dev` - Latest commit on dev branch

### When CI creates tags:

**On version tag push (v0.3.1):**
- Build and push `0.3.1`
- Update `0.3` alias
- Update `0` alias
- Update `latest` alias

**On main branch push:**
- Build and push `main` tag

**On dev branch push:**
- Build and push `dev` tag

### Usage recommendations:

**Development:**
```yaml
# compose.yaml
services:
  nomarr:
    image: ghcr.io/nomarr/nomarr:main
```

**Production:**
```yaml
# compose.yaml
services:
  nomarr:
    image: ghcr.io/nomarr/nomarr:0.3.1  # Pin to specific version
```

**Adventurous users:**
```yaml
# compose.yaml
services:
  nomarr:
    image: ghcr.io/nomarr/nomarr:latest  # Always get latest release
```

---

## CI/CD Behavior

### GitHub Actions Workflows

**On pull request:**
- Run linting (ruff)
- Run type checking (mypy)
- Run tests (pytest)
- Build Docker image (don't push)

**On push to main:**
- Run all checks
- Build Docker image
- Push to `ghcr.io/nomarr/nomarr:main`

**On version tag (v0.3.1):**
- Run all checks
- Build Docker image
- Push multiple tags:
  - `ghcr.io/nomarr/nomarr:0.3.1`
  - `ghcr.io/nomarr/nomarr:0.3`
  - `ghcr.io/nomarr/nomarr:0`
  - `ghcr.io/nomarr/nomarr:latest`

### Automatic Version Detection

CI reads version from `nomarr/__version__.py`:

```python
# nomarr/__version__.py
__version__ = "0.3.1"
```

No manual version specification in CI config needed.

---

## Breaking Changes

### What counts as breaking:

**API:**
- Remove endpoint
- Change response format (remove/rename fields)
- Change required parameters
- Change authentication requirements

**CLI:**
- Remove command
- Change command syntax
- Remove required argument
- Change output format (for scripts)

**Config:**
- Remove config option
- Rename config option
- Change config format (YAML → TOML)
- Change required fields

**Database:**
- Remove table or column
- Change column type (incompatible)
- Change schema without migration
- Change queue job format

**Behavior:**
- Change tag calculation logic (breaks reproducibility)
- Change default values (affects existing users)
- Change file naming/organization

### What is NOT breaking:

**API:**
- Add new endpoint
- Add optional parameters
- Add fields to response (additive only)
- Add new authentication method (alongside existing)

**CLI:**
- Add new command
- Add optional flags
- Improve help text
- Add output formats (alongside existing)

**Config:**
- Add optional config option
- Add config validation
- Improve error messages

**Database:**
- Add table or column (with defaults)
- Add index
- Add migration support

**Behavior:**
- Fix bugs
- Improve performance
- Better error messages

---

## Changelog

### Format

Use [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
# Changelog

All notable changes to Nomarr will be documented in this file.

## [Unreleased]

### Added
- New feature X

### Fixed
- Bug Y

## [0.3.1] - 2025-01-15

### Fixed
- Queue concurrency bug causing duplicate job processing

## [0.3.0] - 2025-01-10

### Added
- Calibration system for tag thresholding
- Analytics API for tag statistics

### Changed
- **BREAKING:** Restructured queue system (requires database rebuild)

### Removed
- Legacy processing mode
```

### Sections

- **Added:** New features
- **Changed:** Changes in existing functionality
- **Deprecated:** Features planned for removal
- **Removed:** Features removed
- **Fixed:** Bug fixes
- **Security:** Security patches

---

## Release Process

### Pre-Release Checklist

- [ ] All tests pass (`pytest tests/`)
- [ ] Linting clean (`ruff check .`)
- [ ] Type checking clean (`mypy nomarr/`)
- [ ] Documentation updated
- [ ] Changelog updated
- [ ] Version bumped in `nomarr/__version__.py`

### Release Steps

**1. Update version:**
```bash
# Edit nomarr/__version__.py
echo '__version__ = "0.3.1"' > nomarr/__version__.py
```

**2. Update changelog:**
```bash
# Edit CHANGELOG.md
# Move items from [Unreleased] to [0.3.1]
```

**3. Commit and tag:**
```bash
git add nomarr/__version__.py CHANGELOG.md
git commit -m "Release 0.3.1"
git tag -a v0.3.1 -m "Release 0.3.1: Fix queue concurrency bug"
git push origin main
git push origin v0.3.1
```

**4. CI builds and publishes:**
- GitHub Actions builds Docker image
- Pushes to GHCR with version tags
- Creates GitHub release (if configured)

**5. Verify:**
```bash
docker pull ghcr.io/nomarr/nomarr:0.3.1
docker pull ghcr.io/nomarr/nomarr:latest
```

---

## Version History

### Version Lifecycle

```
0.1.0 (2024-12-01) - Initial release
  ↓
0.2.0 (2024-12-15) - Calibration system
  ↓
0.2.1 (2024-12-20) - Calibration bug fixes
  ↓
0.3.0 (2025-01-10) - Queue system restructure (breaking)
  ↓
0.3.1 (2025-01-15) - Queue concurrency fix
  ↓
... (future releases)
  ↓
1.0.0 (TBD) - Stable release, strict SemVer begins
```

### Milestone: 1.0.0

**Requirements for 1.0.0:**
- [ ] Core features stable and tested
- [ ] Database schema finalized
- [ ] Migration system implemented
- [ ] Public API stable
- [ ] Documentation complete
- [ ] Production deployments running successfully
- [ ] No known critical bugs

**When 1.0.0 releases:**
- Strict SemVer enforced
- Backward compatibility guaranteed within major versions
- Deprecation warnings required before breaking changes
- Migration guides for major version upgrades

---

## Related Documentation

- [Deployment](../user/deployment.md) - Docker deployment guide
- [Getting Started](../user/getting_started.md) - Installation instructions
- [Architecture](architecture.md) - System design

---

## Summary

**Pre-Alpha (0.x.x):**
- Breaking changes allowed
- No migrations required
- Rapid iteration
- Version bumps: breaking/major feature → MINOR, fixes/small features → PATCH

**Post-1.0:**
- Strict SemVer
- Migrations required for breaking changes
- Backward compatibility within major versions
- Version bumps: breaking → MAJOR, features → MINOR, fixes → PATCH

**Docker tags:**
- Pin to specific version in production: `0.3.1`
- Use `main` for development
- Use `latest` for auto-updates (risky in pre-alpha)

**Release process:**
1. Update version in `nomarr/__version__.py`
2. Update `CHANGELOG.md`
3. Commit and tag
4. Push to trigger CI
5. Verify Docker images published
