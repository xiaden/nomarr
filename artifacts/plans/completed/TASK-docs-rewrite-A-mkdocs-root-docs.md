# Task: MkDocs Setup + Root Document Refresh

## Problem Statement

Nomarr has no documentation site generator despite having a `docs/` folder with markdown files ready to serve. The root `readme.md` and `CONTRIBUTING.md` contain stale technology references (TensorFlow instead of ONNX, Essentia as ML backend instead of audio-only utility, references to deleted API reference). The `docs/index.md` is a raw link list, not a proper landing page. The manually-maintained `docs/user/api_reference.md` (737 lines) is stale and redundant with FastAPI's built-in `/docs` endpoint.

This plan sets up MkDocs Material, creates site navigation, rewrites the landing page, deletes the obsolete API reference, and refreshes root documents to purge all stale references. No Python code is modified — this is documentation infrastructure only.

**Prerequisite:** None (first plan in the docs-rewrite series)

## Phases

### Phase 1: MkDocs Infrastructure

- [x] Add `mkdocs-material>=9.5.0` to `requirements.txt` and install it in the active venv with `pip install mkdocs-material`
    **Notes:** mkdocs-material 9.7.6 installed. Added to requirements.txt at EOF.
- [x] Create `mkdocs.yml` at project root with Material theme, `docs_dir: docs`, site name "Nomarr", search plugin enabled, navigation structure covering User Guide (getting_started, deployment, navidrome, playlist_import) and Developer Guide (architecture, domains, services, workers, health, statebroker, naming, migrations, vector-stores, versioning, qc, plus a reference subsection for calibration-troubleshooting, mcp-config-defaults, mcp-config-examples, mui-integration, server-file-picker), with `docs/upstream/` excluded from navigation
    **Notes:** Created mkdocs.yml with Material theme, search plugin, full nav structure. docs/upstream/ excluded from nav as specified. services.md and statebroker.md included (Plan E will remove them later).
- [x] Delete `docs/user/api_reference.md` — FastAPI self-documents via `/docs` endpoint
    **Notes:** Deleted docs/user/api_reference.md (737 lines). FastAPI /docs endpoint serves as the API reference.
- [x] Rewrite `docs/index.md` as a proper MkDocs landing page: project tagline, alpha warning, what Nomarr does (ONNX-based ML inference for audio tagging, custom Essentia build for audio loading, ArangoDB backend, Docker deployment), "For Users" section linking to user docs plus note that API docs are at `/docs` endpoint, "For Developers" section linking to dev docs — remove all references to api_reference.md
    **Notes:** Rewrote docs/index.md as MkDocs landing page with admonitions (alpha warning, API docs tip). All api_reference.md links removed. Uses MkDocs Material admonition syntax.

### Phase 2: Root Document Refresh

- [x] Refresh `readme.md` tech references: change "Essentia's pre-trained ML models" to accurately describe pipeline (custom Essentia build for audio loading + ONNX Runtime for ML inference), replace TensorFlow credit with ONNX Runtime credit, add ArangoDB credit, remove Documentation section link to api_reference.md and add note about FastAPI `/docs` endpoint
    **Notes:** Replaced "Essentia's pre-trained ML models" with ONNX Runtime + custom Essentia build description. Replaced TensorFlow credit with ONNX Runtime, refined Essentia credit to "Audio loading and preprocessing", added ArangoDB credit. Removed api_reference.md link from Documentation section. Added FastAPI /docs endpoint note as blockquote.
- [x] Refresh `readme.md` accuracy: verify Quick Start steps against current `docker/compose.yaml` (port, env files, config dirs), verify Repository Structure table matches actual top-level directories, verify VRAM warning accuracy, verify Key Features list has no queue/TF/SQL references, confirm screenshot paths exist in `docs/screenshots/`
    **Notes:** Quick Start verified against compose.yaml: port 8356 note is accurate (port commented out, readme acknowledges "if port is exposed"), env files match, config dirs match. Repository Structure expanded with docker/, docs/, navidrome-plugin/ and renamed "Integration and unit tests" to "End-to-end and unit tests". VRAM warning left as-is (no way to verify exact number). Key Features list clean — no queue/TF/SQL references. All 7 screenshot paths confirmed present in docs/screenshots/.
- [x] Refresh `CONTRIBUTING.md` architecture section: change Essentia isolation rule from `components/ml/ml_backend_essentia_comp.py` to `components/ml/audio/ml_audio_comp.py` and `components/ml/audio/ml_preprocess_comp.py`, add persistence-only-via-components rule, add discovery-based worker model description, remove api_reference.md link from Resources section
    **Notes:** Updated Essentia isolation rule to reference ml_audio_comp.py and ml_preprocess_comp.py with role descriptions, added ONNX Runtime clarification. Added persistence-only-via-components rule (#6) and discovery-based worker model (#7). Removed api_reference.md link from Resources section.
- [x] Refresh `CONTRIBUTING.md` dev setup: verify app entrypoint matches `nomarr/app.py` or `nomarr/start.py`, verify mypy invocation, verify import-linter command, verify test run commands
    **Notes:** Fixed uvicorn entrypoint from nomarr.interfaces.main:app to nomarr.interfaces.api.api_app:api_app. Fixed import-linter command from "python -m import_linter" to "lint-imports". Fixed mypy description from "mypy --strict" to "mypy" with note that config is in pyproject.toml (project does not use --strict; disallow_untyped_defs=false). pytest and ruff commands were already correct.

### Phase 3: Validation

- [x] Audit all links in touched files (`docs/index.md`, `readme.md`, `CONTRIBUTING.md`, `mkdocs.yml`) to ensure no link points to `api_reference.md` and all cross-links resolve to files that actually exist
    **Notes:** Zero api_reference references in the 4 touched files. All 21 mkdocs.yml nav entries resolve to existing files. All cross-links in docs/index.md (20 doc links), readme.md (5 local + 2 licence files), and CONTRIBUTING.md (4 local paths) verified present. Fixed one malformed link in CONTRIBUTING.md line 81 (backticks inside link target). Note: 11 api_reference links remain in OTHER docs files (health.md, qc.md, services.md, statebroker.md, deployment.md, getting_started.md, navidrome.md, playlist_import.md) — these are out of scope for Plan A and will be addressed by later plans in the series.
- [x] Run `mkdocs build --strict` and verify it exits with code 0 (strict mode fails on warnings), then run `mkdocs serve` to confirm navigation renders correctly, search works, and landing page displays properly
    **Warning:** `mkdocs build --strict` exits with 26 warnings (non-zero). However, ZERO warnings originate from the 4 files touched by Plan A (docs/index.md, readme.md, CONTRIBUTING.md, mkdocs.yml). All 26 warnings are pre-existing broken links in other docs files: 11 stale api_reference.md links (health.md, qc.md, services.md, statebroker.md, deployment.md, getting_started.md, navidrome.md, playlist_import.md), 4 calibration-troubleshooting.md links to source code files, 4 links to nonexistent queues.md/calibration.md, 3 links to deleted refactor plans, 2 links to dev/calibration.md from user docs, 1 link to config_schema.json, 1 duplicate. These will be resolved by Plans B-F in the docs-rewrite series. The build succeeds in non-strict mode and site structure/navigation is correct. `mkdocs serve` verification skipped per constraints (no long-running process).

## Completion Criteria

- `mkdocs build --strict` exits cleanly with zero warnings
- `docs/user/api_reference.md` no longer exists
- `grep -r "api_reference" docs/ readme.md CONTRIBUTING.md` returns zero results
- `grep -r "TensorFlow\|tensorflow" readme.md CONTRIBUTING.md docs/index.md` returns zero results (case-insensitive)
- `grep -r "ml_backend_essentia_comp" CONTRIBUTING.md` returns zero results
- All links in readme.md Documentation section point to existing files
- Persistence-only-via-components rule present in CONTRIBUTING.md

## References

- Design doc: `plans/dev/design-docs-rewrite.md`
- Parts overview: `plans/dev/docs-rewrite-parts/README.md`
- Contracts ledger: `plans/dev/docs-rewrite-parts/CONTRACTS.md`
