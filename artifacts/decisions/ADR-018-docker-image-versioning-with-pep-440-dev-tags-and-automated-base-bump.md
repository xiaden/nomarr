# ADR-018: Docker Image Versioning with PEP 440 Dev Tags and Automated Base Bump

**Status:** Accepted — amended 2026-09-14 (A2, mechanism only)  
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

## Amendment (2026-09-14 — A2, mechanism only; intent preserved)

This bounded amendment is specified by DD-uv-sole-package-manager §13.9 (Amendment A2). It changes the
mechanism only; the intent of the original decision is preserved and the ADR is **not** superseded. The
original `## Decision` text above remains the historical record; where it conflicts with this amendment
(the `BASE_TAG=develop`/`latest` contract and the `build-base.yml` trigger description), this amendment
supersedes it.

### (a) Ref-selected `BASE_TAG` contract (supersedes the original `BASE_TAG=develop`/`latest` description)

The original Decision text described the old `ci.yml` contract (`BASE_TAG=develop` when building from
`develop`, `BASE_TAG=latest` when building from `main`) and described `build-base.yml` as triggering on
`dockerfile.base` changes to `main`/`develop`. That description is superseded by the following mechanism:

- There is exactly one push-triggered base-image orchestrator, `docker-publish.yml`. It invokes
  `build-base.yml` as a reusable workflow (`workflow_call`), so the base image is built in the SAME
  workflow run as the application image, from the same commit, before `build-and-push` (`needs: build-base`).
- `build-base` publishes tags per ref: `main` → `latest` + `v${BASE_VERSION}` + `sha-${SHORT_SHA}`;
  `develop` → `develop` + `preview-base` + `v${BASE_VERSION}` + `sha-${SHORT_SHA}`; every other ref →
  `preview-base` + `sha-${SHORT_SHA}`. The existing `latest`/`develop`/`preview-base`/`sha-*` tags are retained.
- `build-and-push` selects `BASE_TAG=v${BASE_VERSION}` on `main`/`develop` (where the same-run `build-base`
  republishes that tag) and `BASE_TAG=sha-${SHORT_SHA}` on every other ref (where `build-base` publishes
  `sha-${SHORT_SHA}`, unique to that commit).

The base tag scheme itself, the workflow/job identities, provenance/SBOM attestations, promote semantics,
and the required check names (`build-and-push`, `promote`) are unchanged.

### (b) `BASE_VERSION` is a base build-context revision, not lock-content-addressed

`BASE_VERSION` is declared a base BUILD-CONTEXT revision covering `dockerfile.base` + `build_resources/**`.
It is explicitly **NOT** content-addressed to `uv.lock` (nor to `pyproject.toml`/`.python-version`).
Consequently:

- Dependency inputs (`pyproject.toml`, `uv.lock`, `.python-version`) trigger a base REBUILD and republish the
  base — including the current `v${BASE_VERSION}` tag on `main`/`develop` — WITHOUT a `BASE_VERSION` bump.
- `sha-${SHORT_SHA}` is the commit-exact identity, published on every ref and consumed on non-`main`/`develop`
  refs, so the application image never resolves a base carrying dependency metadata older than the commit
  that produced it.

### (c) Bump triggers unchanged; `build_resources/**` predates this amendment

`base-version-bump.yml`'s `push.paths` remain exactly `dockerfile.base`, `build_resources/essentia/**`, and
`build_resources/scripts/**` (base-only; no dependency inputs, hence no self-retrigger). These paths were
**ALREADY** present in `build-base.yml` / `base-version-bump.yml` before Amendment A2 — the original ADR
text's omission of `build_resources/**` predates this amendment and is not a change introduced by A2.

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
