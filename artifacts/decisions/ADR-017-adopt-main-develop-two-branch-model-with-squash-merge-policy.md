# ADR-017: Adopt main + develop Two-Branch Model with Squash-Merge Policy

**Status:** Accepted  
**Date:** 2026-04-05  
**Tags:** git, workflow, branching, ci, release  

## Context

Nomarr currently uses a single `main` branch where all commits land directly. As CI matures and Docker images are published on every push, unfinished or experimental commits intermittently break the image stream and make `main` unstable. A two-branch model is the standard solution: `develop` acts as the integration branch for ongoing work, while `main` is kept stable and matches the latest shipped Docker image.

## Decision

Adopt a two-branch Git model:

- **`main`** — production-stable. Every commit on `main` must pass CI. Docker `:latest` and versioned images are published only from `main`.
- **`develop`** — integration branch. Feature branches are merged here first. CI runs on `develop` but failures do not block `main`. Docker dev images are published from `develop` under PEP 440 dev tags (see ADR-018).

**Merge policy:**
- Feature branches → `develop`: squash-merge. One logical commit per feature.
- `develop` → `main`: squash-merge. One release commit per integration cycle.
- Hotfixes: branch from `main`, merge directly to `main` with squash, then forward-merge to `develop`.

**Branch protection:**
- `main`: require CI pass, require PR, no direct push.
- `develop`: require CI pass, allow direct push for small fixes.

## Consequences

**Positive:**
- `main` remains stable and always reflects the published Docker image.
- Squash merges produce a clean, linear history on `main` where each commit corresponds to one release or hotfix.
- CI failures on `develop` do not affect `main` stability.

**Negative:**
- Slightly more ceremony for solo contributors: every change requires targeting `develop`, not `main`.
- Hotfix forward-merge to `develop` can conflict if `develop` has diverged.
- Existing CI workflows must update their `on.push.branches` and `on.pull_request.branches` targets to include `develop` (see ADR-019).
