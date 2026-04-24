# CI/CD Pipeline and Branching Strategy — Design Document

**Status:** Revised  
**Author:** rnd-manager  
**Created:** 2026-04-05  
**Revised:** 2026-04-05

**Related Documents:**

- [ADR-001](artifacts/decisions/ADR-001-use-onnx-runtime-for-ml-inference.md) — Use ONNX Runtime for ML Inference
- [ADR-016](artifacts/decisions/ADR-016-skip-ensure-schema-on-existing-databases.md) — Skip ensure_schema on Existing Databases

---

## Scope

GitHub Actions CI/CD workflows, branching model, Docker image versioning, branch protection rules, and bug fixes for existing workflow files.

---

## Problem Statement

Nomarr's CI/CD is a collection of ad-hoc workflows with hardcoded values, stale paths, missing lint gates, and no branch protection. The project has evolved past the "push to main and hope" phase but the infrastructure has not caught up. Specific problems:

1. **No branch protection.** Direct commits to main, no required reviews, no status checks.
2. **No lint/type gate.** Ruff and mypy exist in the project but CI never runs them. Errors slip to runtime.
3. **Frontend "tests" are fake.** `ci.yml` checks file timestamps instead of running vitest. This is a no-op gate.
4. **Hardcoded registry paths.** `build-base.yml` hardcodes `ghcr.io/xiaden/nomarr-base` — breaks forks and violates portability.
5. **Stale path references.** `ci.yml` triggers on `compose.yaml` (moved to `docker/compose.yaml`), `docs-check.yml` references nonexistent layers (`core`, `ml`).
6. **No base image versioning.** Base image only gets `:latest` and `:{SHA}`, making app builds non-reproducible.
7. **`ALWAYS_BUILD` bypass.** The version-change gate in `ci.yml` is permanently disabled by a hardcoded `true`.
8. **No branching convention.** No naming standard, no merge policy, 18 stale Dependabot PRs.
9. **Unpinned ArangoDB.** `docker/compose.yaml` uses `arangodb:latest`, risking surprise breaking changes.
10. **No development buffer.** No separation between "working on it" and "production-ready" states — contributing and releasing collide on the same branch.

---

## Opinion / Recommendation

### Why not pure trunk-based development onto `main`?

The initial proposal was trunk-based: all branches squash-merge directly to `main`. This is clean for solo work but creates friction for the contributor model. When an external contributor opens a PR, they need a target that:

- Reflects current development state, not just the last stable release
- Is separate from the production-grade `main` so the owner is not blocked while a contribution is under review
- Allows the owner to keep pushing without triggering full PR ceremony every time

Without `develop`, a contributor's PR targets `main` alongside the owner's own work. This conflates "actively changing" and "production stable."

### Why not versioned release branches (`release/v0.x`)?

Release branches exist to maintain multiple supported versions simultaneously — backporting security fixes to v1.x while main is on v2.x. For an alpha solo project:

- There are no concurrent supported versions to maintain
- Cherry-pick discipline for every backport adds overhead with zero benefit now
- CI running on multiple release branches is complexity the project cannot justify

**Version is in tags and the version file, not in branch names.** The `develop` branch is not "release work for v0.3.0" — it is just where development happens. What version is being built toward is recorded in the version file in the repo. Branch names are stable and semantic-version-agnostic.

### Why `main` + `develop`?

- **`develop` provides the buffer.** The owner can push feature work directly to `develop` without PR ceremony. `main` only receives squash-merged PRs that passed CI. "Working on it" and "production stable" are genuinely distinct.
- **Contributors PR to `develop`.** Their work flows into the active development stream and is visible in dev image tags before a release is cut.
- **Dev image tags with run numbers provide traceability.** `:v0.3.0.dev47` is immutable (PEP 440) — it is the 47th CI run building toward 0.3.0, traceable to a specific commit. This is more useful than `:develop` alone when debugging a regression.
- **`:develop` stays mutable.** Easy to pull the latest development image without knowing the run number. Both the mutable pointer and the immutable audit trail coexist.
- **`main` stays clean.** Only stable, fully-tested builds live here. `:latest` on GHCR always means the last production release.

---

## Architecture

### 1. Branching Strategy

#### Branch Model

 | Branch | Owner | Access | Merge Policy |
 | -------- | ------- | -------- | -------------- |
 | `main` | Protected — CI-gated squash PRs only | Nobody pushes directly | Squash merge from `develop` only, after all CI checks pass |
 | `develop` | Active development | Owner pushes directly; contributors open PRs | Owner: direct push. Contributors: squash PR with CI gates |

**Initial state:** Tag `main` as `v0.2.2` (current stable). Update `nomarr/__version__.py` on `develop` to `0.3.0.dev0` (PEP 440 dev release).

**Contributor branch prefixes:**

 | Prefix | Purpose |
 | -------- | --------- |
 | `feat/` | New functionality |
 | `fix/` | Bug fixes |
 | `chore/` | Maintenance, deps, CI changes |
 | `refactor/` | Code restructuring, no behavior change |
 | `docs/` | Documentation only |
 | `dependabot/*` | Automated dependency updates (leave as-is) |

**Merge policy:** Squash merge only everywhere. Every PR becomes one commit on its target with the PR title as the commit message. History stays linear and bisectable.

#### Branch Protection Rules

**`main`:**

 | Rule | Setting |
 | ------ | --------- |
 | Require PR before merging | Yes |
 | Required approvals | 0 (escalate when team grows) |
 | Require status checks to pass | Yes |
 | Required checks | `lint`, `test`, `frontend-test` |
 | Require branches up to date | Yes |
 | Allow squash merging only | Yes |
 | Allow force pushes | No |
 | Allow deletions | No |
 | Auto-delete head branches | Yes |

**`develop`:**

 | Rule | Setting |
 | ------ | --------- |
 | Require PR before merging | Yes (for contributors; owner bypasses with direct push) |
 | Required checks on PRs | `lint`, `test`, `frontend-test` |
 | Allow direct push from owner | Yes |

#### Dependabot Handling

The 18 existing stale PRs should be triaged manually (close or merge). Going forward:

- Dependabot PRs target `develop`, not `main`
- Group minor/patch updates by ecosystem (Python, npm) via `dependabot.yml` groups
- Major version bumps remain individual PRs for review

#### Version File Lifecycle

`nomarr/__version__.py` contains the target version for the current development cycle. Format follows PEP 440:

 | Branch | Version format | Example |
 | -------- | ---------------- | --------- |
 | `develop` | `N.N.N.devN` — dev release targeting next version | `0.3.0.dev0` |
 | `main` | `N.N.N` — stable release | `0.2.2` |

**Develop branch:** The version file holds the TARGET version with a `.dev0` suffix — meaning "we are working toward X.Y.Z." The `0` is a placeholder; Docker tags replace it with the CI run number (e.g., `.dev47`). The version file itself stays at `.dev0` between pushes.

**Release flow (squash develop → main):**

1. Update `nomarr/__version__.py` on `develop` to the clean release version (e.g., `0.3.0`)
2. Squash-merge `develop` → `main`
3. Tag `main` as `vN.N.N` (e.g., `v0.3.0`)
4. Immediately update `nomarr/__version__.py` on `develop` to the next target with `.dev0` suffix (e.g., `0.4.0.dev0` or `0.3.1.dev0`)

**Version bump guide (pre-1.0 alpha norms):**

- Minor bump (`0.3.0 → 0.4.0`): new user-facing features, breaking API or schema changes
- Patch bump (`0.3.0 → 0.3.1`): bug fixes, internal refactors, dependency updates
- Breaking changes are expected pre-1.0 — minor bumps are the norm

**Migration system note:** Migrations run all available sequential migrations at startup regardless of the app version string. The version string is for Docker tags and human identification only. Any code that couples app version to expected schema state must have that coupling broken.

---

### 2. CI Pipeline Architecture

Three distinct scenarios drive the workflow configuration:

#### Scenario A — PR to `develop`

**Purpose:** Gate contributor work before it enters the development stream. No image build.

```
PR to develop
├── lint          (~1 min, no deps)
└── frontend-test (~2 min, no deps)
        │
        └── test  (depends: lint)
```

#### Scenario B — Push/merge to `develop`

**Purpose:** Build and publish a traceable dev image after every successful push to `develop`.

```
push to develop
├── lint
└── frontend-test
        │
        └── test
                │
                └── build-and-push  (tags: :develop, :v{next}-dev.{run})
```

#### Scenario C — Squash-merge to `main`

**Purpose:** Publish a stable release image.

```
squash-merge to main
├── lint
└── frontend-test
        │
        └── test
                │
                └── build-and-push  (tags: :latest, :v{semver})
```

`lint` and `frontend-test` always run in parallel. `test` depends on `lint` — no point running slow tests if code fails basic checks. `build-and-push` depends on both `test` and `frontend-test`, and uses default `if: success()` — it must not run when upstream jobs fail.

#### Job Definitions

**`lint` — Fast Static Analysis**

```yaml
steps:
  - ruff check .
  - ruff format --check .
  - mypy nomarr/ --config-file pyproject.toml
```

Catches syntax errors, import issues, type mismatches, and formatting drift before anything else runs.

**`test` — Backend Unit Tests (depends: lint)**

```yaml
steps:
  - pip install -e ".[dev]"
  - pytest -m "not container_only and not requires_database and not code_smell"
```

Same markers as current CI. Container and database tests require the Docker environment and do not belong in PR gates.

**`frontend-test` — Real Frontend Tests**

```yaml
steps:
  - npm ci --prefix frontend
  - npx --prefix frontend vitest run
```

Replaces the current timestamp-comparison hack. Runs actual vitest test suites.

**`build-and-push` — Docker Image Build (depends: test + frontend-test)**

On `develop` push:

- Tags: `:develop` (mutable, overwritten each run), `:v{next}.dev{run}` (immutable, PEP 440)
- `{next}` read from `nomarr/__version__.py`
- `{run}` = `${{ github.run_number }}` — monotonically increasing
- Example: `:develop`, `:v0.3.0.dev47`

On `main` push:

- Tags: `:latest`, `:v{semver}`
- `{semver}` read from `nomarr/__version__.py`
- Example: `:latest`, `:v0.2.2`

Registry: `ghcr.io/${{ github.repository_owner }}/nomarr` — dynamic, not hardcoded.

`ALWAYS_BUILD="true"` removed entirely. Every push to `develop` or `main` triggers a build after CI passes — no additional condition needed.

#### Separate Workflows

**`build-base.yml` — Base Image Build**

Triggers: Manual (`workflow_dispatch`), push when `dockerfile.base` or `build_resources/essentia/**` change.

Tags: `:latest`, `:v{BASE_VERSION}` (read from `BASE_VERSION` file at repo root), `:sha-{short}`

Registry: `ghcr.io/${{ github.repository_owner }}/nomarr-base` — no hardcoded `xiaden`.

`BASE_TAG` build arg set explicitly — no floating `:latest` dependency in app builds.

**`docs-check.yml` — Documentation Freshness Gate**

Triggers: PR to `develop` only.

Fix: Update path regex from `nomarr/(interfaces|core|services|ml)/.+\.py` to `nomarr/(interfaces|services|workflows|components|persistence|helpers)/.+\.py`.

**`prune-images.yml` — Image Cleanup**

No changes. Weekly untagged image cleanup works correctly.

**`base-version-bump.yml` — Automated BASE_VERSION PR**

Triggers: Push to `develop` when `dockerfile.base` or base-affecting deps change (path filter: `dockerfile.base`, `build_resources/essentia/**`, `build_resources/scripts/**`).

Action: Opens a PR on `develop` bumping `BASE_VERSION` to the next semantic version. Reduces cognitive overhead and prevents forgotten version bumps after base image changes. Manual bump still possible by editing `BASE_VERSION` directly.

**`codeql.yml` — Daily Security Scan**

Triggers: Daily schedule at 10:00 AM UTC. Not triggered by PRs or pushes — not a CI gate.

Action: Runs CodeQL analysis using the existing `.github/codeql/codeql-config.yml` config. Reports findings to the GitHub Security tab without blocking merges or generating PR comments.

---

### 3. Docker Image Versioning Strategy

#### Two-Layer Strategy (Preserved)

The existing base + app image split is correct and preserved. Base images are expensive (essentia compilation from source, ~30+ min) and change rarely. App images are cheap and change on every release.

#### App Image Tag Scheme

 | Branch | Tags on Push | Example |
 | -------- | ------------- | --------- |
 | `main` | `:latest`, `:v{semver}` | `:latest`, `:v0.2.2` |
 | `develop` | `:develop`, `:v{next}.dev{run}` | `:develop`, `:v0.3.0.dev47` |

- `:develop` — mutable, always the newest dev build
- `:v0.3.0.dev47` — immutable, traceable to CI run number and its commit SHA (PEP 440 dev release)
- `:latest` and `:v{semver}` — only update on squash-merge to `main`
- `{run}` = `${{ github.run_number }}` — monotonically increasing, no gaps, no collisions

**Version source:** `nomarr/__version__.py`. The `develop` branch version file contains the TARGET version with a PEP 440 `.devN` suffix (e.g. `0.3.0.dev0`). CI reads this file and substitutes the run number to produce the immutable tag (e.g. `:v0.3.0.dev47`). The `main` branch version file contains the clean release version (e.g. `0.2.2`), used as-is.

#### BASE_VERSION Mechanism

`BASE_VERSION` file at repo root contains one line: the semantic version of the base image (e.g., `1.0.0`).

1. Read by `build-base.yml` to produce `:v{BASE_VERSION}` tags
2. Read by `ci.yml` to pass `ARG BASE_TAG=v{BASE_VERSION}` into the app `docker build`
3. Bumped automatically via `base-version-bump.yml` — CI opens a PR on `develop` when `dockerfile.base` or base-affecting deps change. Manual bump still possible.

App builds pin to `nomarr-base:v{BASE_VERSION}` — not `:latest`. Reproducible across all runs.

#### Base Image Tag Scheme

 | Image | Tags | Example |
 | ------- | ------ | --------- |
 | `nomarr-base` | `:v{BASE_VERSION}`, `:latest`, `:sha-{short}` | `:v1.0.0`, `:latest`, `:sha-a1b2c3d` |

#### compose.yaml Pinning

Pin ArangoDB: `arangodb:3.12` instead of `arangodb:latest`.

---

### 4. Bug Inventory and Fixes

All 12 bugs catalogued with explicit fixes:

 | # | File | Bug | Fix |
 | --- | ------ | ----- | ----- |
 | 1 | `ci.yml` | `ALWAYS_BUILD="true"` permanently bypasses version-change gate | Remove entirely. Build on every develop/main push after CI passes. |
 | 2 | `ci.yml` | Push path filter `"compose.yaml"` (file moved) | Change to `"docker/compose.yaml"` |
 | 3 | `ci.yml` | No lint job — ruff and mypy never run in CI | Add `lint` job with ruff check + ruff format --check + mypy as required check |
 | 4 | `ci.yml` | Frontend "test" is file timestamp comparison, not vitest | Replace with `npm ci --prefix frontend && npx --prefix frontend vitest run` |
 | 5 | `docs-check.yml` | Path regex references `core` and `ml` — layers that no longer exist | Update regex to `interfaces\ | services\ | workflows\ | components\ | persistence\ | helpers` |
 | 6 | `pyproject.toml` vs `requirements.txt` | `onnxruntime` version inconsistency between the two files | Align versions; `requirements.txt` must pin the same version as `pyproject.toml` optional dep |
 | 7 | `build.ps1` | References `.docker/` (wrong path — moved) | Change to `docker/` |
 | 8 | `build-base.yml` | Hardcoded `ghcr.io/xiaden/nomarr-base` in registry URL and cache arg | Replace all occurrences with `ghcr.io/${{ github.repository_owner }}/nomarr-base` |
 | 9 | `.github/codeql/` | `codeql-config.yml` exists but no workflow references it | Add `codeql.yml` as a daily scheduled workflow at 10 AM UTC using the existing config. Not a CI gate — reports to GitHub Security tab without blocking PRs. |
 | 10 | `docker/compose.yaml` | `arangodb:latest` is unpinned | Pin to `arangodb:3.12` |
 | 11 | `ci.yml` | `if: always()` on `build-and-push` allows image builds to run even after test failures | Remove `if: always()`; default `if: success()` applies |
 | 12 | Dependabot PRs | ~18 unreviewed Dependabot PRs accumulating stale | Triage manually (close or merge); configure `dependabot.yml` groups going forward |

---

## Design Goals

1. **Every merge to `main` passes lint + tests.** No untested code reaches the stable branch.
2. **`develop` is always publishable.** Every push produces a traceable dev image — `:v0.3.0-dev.N` is immutable.
3. **Docker builds are reproducible.** Pinned base versions via `BASE_VERSION` file, no floating `:latest` in builds.
4. **CI is portable.** No hardcoded usernames or org names. Forks work without modification.
5. **Fast feedback on PRs.** Lint fails in ~1 minute. Developers do not wait for Docker builds to learn about a typo.
6. **Minimal ceremony for alpha.** No release branches, no complex versioning. Tags and the version file track versions; branch names do not.

---

## Constraints

- Base image builds are ~30+ minutes (essentia compiled from source in base image — intentional, must be preserved). Cannot be part of PR gates.
- ADR-001 constrains ML models to ONNX format — base image must include `onnxruntime`.
- ADR-016 constrains schema changes to forward-only migrations — CI tests must run migrations.
- Solo developer currently — 0 required approvals on all branches; escalate when team grows.
- GitHub Actions free tier limits — bounded parallel jobs and cache storage.
- Alpha software — right-sized process; no enterprise overhead.

---

## Resolved Decisions

All design questions from earlier drafts are now closed.

 | Question | Decision |
 | ---------- | ---------- |
 | mypy strictness | Use the project's existing `pyproject.toml` config. No CI override. Tighten over time if needed. |
 | Dependabot grouping | Keep grouped. More signal than actionable — owner reviews but rarely applies directly. Reduces noise. |
 | CodeQL | Not a CI gate. Daily scheduled workflow at 10 AM UTC (`codeql.yml`). Reports findings to GitHub Security tab. |
 | Test matrix/filtering | Test everything every time. Vitest and pytest are fast enough; no path filtering or matrix needed. |
 | BASE_VERSION auto-bump | Automated. `base-version-bump.yml` detects changes to `dockerfile.base` or base-affecting deps and opens a PR bumping `BASE_VERSION`. Manual override still possible. |
