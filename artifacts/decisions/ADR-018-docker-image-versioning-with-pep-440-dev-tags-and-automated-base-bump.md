# ADR-018: Docker Image Versioning with PEP 440 Dev Tags and Automated Base Bump

**Status:** Accepted  
**Date:** 2026-04-05  
**Tags:** docker, versioning, ci, release, pep440  

## Context

The CI workflow (`ci.yml`) currently publishes Docker images tagged with the SemVer from `nomarr/__version__.py`, the sanitized branch name, and the commit SHA. For non-`main` branches the primary tag is just the sanitized branch name (e.g., `develop`), which is opaque and gets overwritten on every build. This makes it impossible to pin a specific pre-release image. Additionally, `build-base.yml` triggers on `dockerfile.base` changes to `main` only; there is no mechanism to build a base image from `develop` for testing before landing on `main`.

## Decision

**Application image versioning:**

- **`main` builds → `latest` + `v{MAJOR}.{MINOR}.{PATCH}` + `{SHA}`**
  Example: `ghcr.io/xiaden/nomarr:latest`, `ghcr.io/xiaden/nomarr:v0.2.3`
- **`develop` builds → `{MAJOR}.{MINOR}.{PATCH}.dev{RUN_NUMBER}` + `{SHA}`**
  Example: `ghcr.io/xiaden/nomarr:0.2.3.dev42`

The `.dev{RUN_NUMBER}` suffix follows PEP 440 pre-release convention, clearly indicating a non-stable image.

**Base image versioning:**

- `build-base.yml` triggers on changes to `dockerfile.base` on both `main` and `develop`.
- `main` base builds tag `ghcr.io/xiaden/nomarr-base:latest`.
- `develop` base builds tag `ghcr.io/xiaden/nomarr-base:develop`.
- `ci.yml` application build passes `BASE_TAG=develop` when building from `develop`, and `BASE_TAG=latest` when building from `main`.

This ensures `develop` builds test against the most recent `develop` base layer rather than the stable `latest` base.

## Consequences

**Positive:**
- Docker tags on `develop` carry semantic meaning (`0.2.3.dev42`) rather than opaque branch-name tags.
- `main` images are always SemVer-tagged and also carry `:latest`, making upgrade path unambiguous for users.
- Automated base bump prevents stale base layers piling up.

**Negative:**
- PEP 440 dev tags are not standard Docker UX — users pulling `develop`-sourced images must understand the `.devN` suffix.
- Base bump workflow requires the `develop` branch to exist (dependency on ADR-017).
- SHA tags remain on all images for traceability but increase GHCR storage slightly.

## References

ADR-017
