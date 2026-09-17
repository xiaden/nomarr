# ADR-049: uv is the sole Python package/environment manager for every active Nomarr-owned installation path, including the Docker base image

**Status:** Accepted  
**Date:** 2026-09-14  
**Tags:** dependencies, packaging, uv, ci, docker, tooling  
**Source Log:** rnd-ddauthor#L1  

## Context

Nomarr currently resolves its Python environment along three independent paths that can silently diverge:

1. **Local dev** — `scripts/human-scripts/tools/ensure_venv.py` creates `.venv` with `python -m venv`, then `pip install --upgrade pip` and `pip install -e ".[dev]"`, tracking `.venv/.deps_hash`. It is already broken against the uv-created `.venv` in this environment (uv environments have no `pip` module). CONTRIBUTING.md and agents.md document this path.
2. **CI** — all five backend jobs in `.github/workflows/backend-quality.yml` (`lint`, `deptry`) and `backend-tests.yml` (`test`, `architecture-qc`, `database-tests`) run `python -m venv .venv`, `pip install --upgrade pip`, `pip install -e ".[dev]"`, and cache `.venv` keyed on `pyproject.toml`/`uv.lock`.
3. **Docker base image** — `dockerfile.base` installs a manually hand-pinned `python3 -m pip install --break-system-packages` manifest into the Ubuntu 24.04 system Python 3.12, with exact pins that have drifted from `pyproject.toml` (including `pytest`/`pytest-cov` present in production, `onnxruntime-gpu` vs `onnxruntime`, and `pychromaprint` missing from the manifest although the image sanity-imports `chromaprint`).

A `uv.lock` exists and is current (100 packages, resolved for both CPU `onnxruntime` and GPU `onnxruntime-gpu` forks), but nothing in CI or Docker uses it: the lock is not load-bearing. `pyproject.toml` declares dev dependencies in `[project.optional-dependencies].dev`, so a plain sync prunes the dev toolchain unless an extra is requested — the documented cause of the previously observed `uv sync --frozen` pruning pytest/ruff/mypy/import-linter. No `.python-version` exists, so a host `python3` of 3.13 is selectable even though `requires-python = ">=3.12"` and CI pins 3.12.

The result is that local, CI, and shipped Docker can each resolve a different Python package architecture from the same repository. ADR-042 consolidated enforcement but did not address package management; ADR-019/ADR-018 govern CI gates and Docker base versioning respectively and are unaffected by this decision.

## Decision

Adopt **uv as the single package and environment manager** for `pyproject.toml` direct-dependency intent, `uv.lock` resolved-graph, and `uv`-owned create/sync/lock/install across every active Nomarr-owned Python installation path, including the Docker base image.

Concretely:

- **Single authority.** `pyproject.toml` is the sole source of direct dependency intent; `uv.lock` is the single resolved graph that must hold both the CPU and GPU ONNX variants. No active installation path may independently resolve a second package graph.
- **Development dependencies** move from `[project.optional-dependencies].dev` to uv's normal development dependency group (`[dependency-groups] dev`), so a plain `uv sync --locked` yields the complete dev environment (pytest, ruff, mypy, import-linter, deptry, …) and dev-toolchain pruning is eliminated structurally.
- **CPU/GPU ONNX variants** are modeled as mutually exclusive uv groups (`cpu`, `gpu`) with `default-groups = ["dev", "cpu"]` and `[tool.uv] conflicts`; both are represented by the same `uv.lock`; CPU is the local/CI default, GPU is selected only for the Docker production sync; GPU is capped `<1.27` in `pyproject.toml`; no install-then-replace. Deptry is configured with `non_dev_dependency_groups` and a `package_module_name_map` (`onnxruntime-gpu` → module `onnxruntime`) so the mapping is accurate.
- **Python 3.12** is made explicit with a committed `.python-version = 3.12`; `requires-python = ">=3.12"` is kept so no supported Python architecture changes, and local selection can no longer accidentally pick 3.13.
- **Local bootstrap** deletes the custom env machinery in `scripts/human-scripts/tools/ensure_venv.py` (and `.deps_hash`); uv owns `.venv` creation/sync/lock/reconciliation and `uv sync --locked` is the documented default. No thin pip-delegating wrapper is retained.
- **CI** migrates every active backend Python environment install to uv via the official `astral-sh/setup-uv` integration with `actions/setup-python` reading `.python-version`, and runs an explicit `uv sync --locked` that fails on any `pyproject.toml`/`uv.lock` disagreement; tools run from the uv-controlled environment with no hidden repeated sync; `python -m venv`, `pip install --upgrade pip`, `pip install -e ".[dev]"`, and pip-only `.venv` caching are removed. Required workflow job names `lint`, `deptry`, `test`, `architecture-qc`, `database-tests` are preserved unchanged.
- **Docker base image** derives the production GPU / no-dev package set from `pyproject.toml` + `uv.lock` via a single pinned-uv exact sync into the existing Ubuntu 24.04 system Python 3.12 (`uv export --frozen --no-default-groups --group gpu` → `uv pip sync --system --break-system-packages`), with no committed generated requirements file as a second authority. uv is version-pinned (no unbounded `latest`); `python3-pip` and pip-specific environment configuration are removed when no longer required. The runtime contract is preserved: Ubuntu 24.04 system Python 3.12, unchanged CUDA/cuDNN, Essentia compiled against the existing system Python/headers, no uv-managed standalone CPython and no isolated Docker `.venv`, system `python3` retained for the app, and setuptools remains the build backend.
- **Docker/project divergence** is reconciled by encoding genuine functional constraints in `pyproject.toml` (not Docker-only): onnxruntime-gpu for production, pychromaprint/chromaprint, pyacoustid, removal of pytest/pytest-cov from production, and elimination of Docker-only exact pins.
- **Base-image CI triggers** are updated so dependency inputs (`pyproject.toml`, `uv.lock`, Python/uv version config) rebuild the base; a base with an older locked environment is never published or reused after dependency metadata changes. The app image consumes the uv-managed base and adds no other Python package-management path.
- **Dependabot** is reconciled to the uv architecture (uv ecosystem; dead pip-oriented config removed; stale CI path filters for deleted dependency files removed), with no change to unrelated dependency automation.
- **Isolated research/ vendored paths** are not forced into the app dependency graph: active Nomarr-owned install routes migrate to uv; isolated research may keep its own requirements declaration but its active install instructions use uv where practical; vendored third-party pip references are not edited.
- **Active documentation** (CONTRIBUTING.md, readme.md, devcontainer/OpenCode docs, CI/Docker comments, troubleshooting/setup) documents `uv sync --locked` as the default local setup.

Non-goals: no pgvector change, no application-layer refactor, no frontend package-manager change, no setuptools migration solely for uv, no CUDA base replacement, no Essentia redesign, no Docker topology change, no CI gate renaming, no unrelated dependency updates, no unrelated tech-debt cleanup.

Design detail, per-fork resolutions (F1–F8), affected files, sequencing, validation plan, and the R1–R20 conformance map live in `artifacts/designs/pending/DD-uv-sole-package-manager.md`.

## Consequences

**Positive**

- One resolved Python package graph across local dev, CI, and shipped Docker; the three paths can no longer silently diverge.
- `uv.lock` becomes load-bearing: `uv sync --locked` / `--frozen` fail on drift instead of silently re-resolving.
- Dev tooling is structurally guaranteed: a plain `uv sync --locked` yields the complete dev environment; the "sync pruned pytest/mypy/ruff" class of failure disappears.
- Faster, deterministic installs locally and in CI; the production image no longer carries pytest/pytest-cov or pip-specific configuration.
- CPU/GPU ONNX variants are explicit and mutually exclusive in one lock, removing the install-then-replace and hand-pinned-manifest divergence.

**Negative / costs**

- uv becomes a required toolchain dependency for contributors and CI; uv must be version-pinned everywhere to avoid lock-schema drift.
- Converting dev dependencies from an extra to a dependency group changes the invocation model (`uv sync` includes `dev` by default; `uv sync --no-dev`/`--no-default-groups` excludes it) and requires updating any command that assumed `.[dev]`.
- The Docker base image change is only provable on GitHub-hosted runners (no local Docker in this environment); the authoritative validation and any repair loop run through GitHub Actions, and each required-check recovery requires a new commit.
- Forced lock re-resolution may churn unrelated packages or flip the onnxruntime-gpu fork; this must be reviewed rather than accepted blindly.
- The base image now rebuilds as an ordered dependency of the app image build, so a base failure blocks app publication until a new commit is pushed.

**Neutral / follow-on**

- `ensure_venv.py` is deleted rather than wrapped; the OpenCode activation path remains compatible with a uv-created `.venv`.
- Isolated research environments and vendored third-party pip references remain intentionally separate and are out of the app graph.
- CI required-check identity (job names and `scripts/validate_commit.py` contract) is unchanged, so branch protection semantics remain valid.

## References

- Design document: `artifacts/designs/pending/DD-uv-sole-package-manager.md` (brief, 8-turn adversarial log, architecture/tradeoff matrix, complexity review, estimate, and PatternEnforcer gate are sibling artifacts in the same directory)
- ADR-042 — Simplification Program (enforcement consolidation; pyproject.toml as dependency source)
- ADR-019 — CI Pipeline Gates
- ADR-018 — Docker Image Versioning with PEP 440 Dev Tags and Automated Base Bump
- ADR-035 — Essentia as the Audio DSP and Preprocessing Backend
- ADR-046 — Allow Thin Persistence Intent-Facade Calls from Services and Workflows
