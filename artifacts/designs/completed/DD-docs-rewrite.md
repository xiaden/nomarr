# Design: Documentation Rewrite

**Status:** Draft
**Date:** 2026-03-23
**Scope:** Complete documentation overhaul — in-codebase layer docs, MkDocs site, user/dev docs, root README

---

## Problem Statement

Nomarr's documentation is ~3 months and hundreds of commits behind the codebase. Nearly every documentation surface contains stale references that actively mislead developers and AI agents. Key issues:

- **Stale tech references:** TensorFlow → ONNX, Essentia-as-ML-backend → custom Essentia build for audio loading only, SQL → AQL, queue-based processing → discovery-based workers
- **Missing codebase docs:** Most `nomarr/` subfolders lack any documentation. Existing layer docs (COMPONENTS.md, SERVICES.md, etc.) reference deleted files, removed patterns, and obsolete directory structures
- **Misleading dev docs:** `docs/dev/` describes architecture patterns that no longer exist (queue workflows, processing workers, event broker, etc.)
- **No documentation site:** The `docs/` folder structure is MkDocs-ready but no `mkdocs.yml` exists
- **Missing persistence rule:** The critical rule that "only components may call persistence" has vanished from all documentation
- **Missing subdomain docs:** Component subfolders (`ml/`, `library/`, `navidrome/`, etc.) have no documentation at all
- **Stale user docs:** API reference, deployment guide, and getting started guide reference non-existent endpoints and obsolete configuration

### What Changed (Known Stale Patterns)

| Old (in docs) | Current (in code) |
|---|---|
| TensorFlow ML backend | ONNX inference via `components/ml/onnx/` |
| `ml_backend_essentia_comp.py` as sole ML entry | Custom Essentia build for audio loading (`ml_audio_comp.py`) and preprocessing (`ml_preprocess_comp.py`) only |
| Queue-based job processing | Discovery-based workers claiming from `library_files` |
| `queue/` components and workflows | Removed entirely |
| `events/` components (event_broker, SSE) | Removed or restructured |
| `sql_helper.py` | Doesn't exist (AQL-only) |
| `base.py` worker class | `discovery_worker.py` only |
| Processing workers, calibration workers | Single discovery worker type |
| `scan_library_direct_wf.py`, `start_scan_wf.py` | `scan_library_full_wf.py`, `scan_library_quick_wf.py` |
| `entity_keys_comp.py` | Doesn't exist |
| `pages/` directory in frontend | `features/` directory |
| `shared/api.ts`, `shared/auth.ts` | Restructured under `shared/api/`, `shared/utils/` |

---

## Audiences

### 1. AI Agents / LLM Contexts (Primary for in-codebase docs)
- Consume `.md` files in `nomarr/` directories and `.github/instructions/`
- Need: accurate directory trees, clear rules, file-level descriptions, decision rationale
- Format: concise, structured, no prose fluff — facts and rules

### 2. End Users (Primary for `docs/user/`)
- Deploy via Docker, use web UI, configure integrations
- **Do NOT understand coding at all**
- Need: step-by-step guides, screenshots, troubleshooting, plain language
- Format: task-oriented with visual aids

### 3. Developers / Contributors (Primary for `docs/dev/`)
- Understand or want to understand Nomarr's architecture
- Need: philosophy, patterns, conventions, architectural decisions, roadmap
- Format: conceptual explanations with code examples, decision rationale

### 4. ML Models / Agent Contexts (Primary for `docs/upstream/`)
- Consume upstream technology documentation when making changes involving those technologies
- Need: reference material from Essentia, ArangoDB, ONNX, etc.
- Location question: currently in `docs/upstream/`, may be better in `build_resources/` or `nomarr/docs/`

---

## Documentation Surfaces

### Surface 1: In-Codebase Layer Documentation

**Location:** `nomarr/{layer}/{LAYER_NAME}.md` and `nomarr/{layer}/{subdomain}/README.md`

**Purpose:** Guide developers and AI agents on what lives in each folder, what the rules are, and how to add new code there.

**Existing files that need rewrite:**
- `nomarr/components/COMPONENTS.md` (443 lines, very stale)
- `nomarr/services/SERVICES.md` (259 lines, stale)
- `nomarr/workflows/WORKFLOWS.md` (247 lines, stale)
- `nomarr/interfaces/INTERFACES.md` (160 lines, stale)
- `nomarr/persistence/PERSISTENCE.md` (1015 lines, stale)
- `nomarr/helpers/HELPERS.md` (348 lines, stale)

**Missing files (need creation):**
- Subdomain README.md files for each component subfolder:
  - `components/analytics/README.md`
  - `components/infrastructure/README.md`
  - `components/library/README.md`
  - `components/metadata/README.md`
  - `components/ml/README.md` (plus subfolders: `audio/`, `calibration/`, `inference/`, `onnx/`, `resources/`, `vectors/`)
  - `components/navidrome/README.md`
  - `components/platform/README.md`
  - `components/playlist_import/README.md`
  - `components/processing/README.md`
  - `components/tagging/README.md`
  - `components/workers/README.md`
- Service subdomain docs:
  - `services/domain/README.md`
  - `services/infrastructure/README.md`
  - `services/infrastructure/workers/README.md`
- Workflow subdomain docs:
  - `workflows/calibration/README.md`
  - `workflows/library/README.md`
  - `workflows/metadata/README.md`
  - `workflows/navidrome/README.md`
  - `workflows/platform/README.md`
  - `workflows/playlist_import/README.md`
  - `workflows/processing/README.md`
  - `workflows/vectors/README.md`
- Interface subdomain docs:
  - `interfaces/api/README.md`
  - `interfaces/api/types/README.md`
  - `interfaces/api/v1/README.md`
  - `interfaces/api/web/README.md`
  - `interfaces/cli/README.md`
- Persistence subdomain docs:
  - `persistence/database/README.md`
  - `persistence/database/library_files_aql/README.md`
  - `persistence/database/tags_aql/README.md`
- Helpers subdomain docs:
  - `helpers/dto/README.md`

**Template for subdomain README.md:**
```markdown
# {Subdomain Name}

{1-2 sentence summary of what this folder contains}

## Files

| File | Purpose |
|---|---|
| `file_name.py` | {One-line description} |

## Key Rules
- {Rule specific to this subdomain}

## Relationships
- Called by: {upstream callers}
- Calls: {downstream dependencies}
```

**Key rule that must be restored across ALL layer docs:**
> Components are the ONLY layer that should call persistence or otherwise use the database for ANY reason. Workflows, services, and interfaces must NEVER import or call persistence directly.

### Surface 2: .github/instructions/ Layer Files

**Location:** `.github/instructions/*.instructions.md`

**Purpose:** Provide Copilot/agent auto-context when editing files in specific directories.

**Existing files (15):** All need review for the persistence rule and stale references. Primary fix: ensure the persistence-only-via-components rule is present in every layer instruction file that might tempt someone to use the DB directly.

**Scope:** Light refresh, not rewrite. Focus on:
- Adding missing persistence access rule to `services.instructions.md`, `workflows.instructions.md`, `interfaces.instructions.md`
- Removing any stale references (queues, TensorFlow, SQL)
- Cross-checking that directory structures mentioned are current

### Surface 3: docs/ Folder (MkDocs Site)

**Location:** `docs/`

**Structure (target):**
```
docs/
├── index.md                    # Landing page, navigation hub
├── mkdocs.yml                  # MkDocs Material configuration (new, placed at project root)
├── user/
│   ├── getting_started.md      # Installation, first steps (complete rewrite)
│   ├── deployment.md           # Docker deployment, GPU setup (complete rewrite)
│   ├── navidrome.md           # Navidrome integration guide (rewrite)
│   ├── playlist_import.md     # Playlist import guide (rewrite)
│   └── troubleshooting.md     # New — common issues, logs, debugging
├── dev/
│   ├── architecture.md         # System design, layers, dependency rules (complete rewrite)
│   ├── domains.md             # Domain boundaries, data ownership (rewrite)
│   ├── services.md            # Service responsibilities and APIs (rewrite)
│   ├── workers.md             # Worker system, health monitoring (rewrite)
│   ├── health.md              # Health table invariants (rewrite)
│   ├── statebroker.md         # Real-time state management (rewrite)
│   ├── naming.md              # Naming conventions (rewrite)
│   ├── migrations.md          # Database migration system (rewrite)
│   ├── vector-stores.md       # Vector hot/cold architecture (review, may be current)
│   ├── versioning.md          # Versioning strategy (review)
│   └── qc.md                  # Quality control system (rewrite)
├── upstream/                   # ML model reference (keep, possibly relocate)
│   ├── modelsinfo.md
│   ├── navidrome_integration.md
│   └── navidrome_smart_playlists.md
└── screenshots/                # New screenshots of live UI
```

**Removed:** `docs/api/` — FastAPI is self-documenting via `/docs` endpoint.

**New file:** `docs/user/troubleshooting.md`

**API reference decision:** Remove the standalone `docs/user/api_reference.md` in favor of FastAPI's auto-generated docs. Add a brief "API" section in getting_started.md pointing users to `http://your-host:8356/docs`.

**MkDocs configuration:** New `mkdocs.yml` at project root with Material theme, navigation structure, and search.

### Surface 4: Root README.md

**Location:** `readme.md`

**Scope:** Refresh, not rewrite. Fix:
- Stale feature descriptions
- VRAM warning (verify accuracy)
- Quick start steps (verify against current docker setup)
- Repository structure table (verify directories)
- Remove references to TensorFlow
- Update example output if tag format changed
- Verify screenshot paths

### Surface 5: Other Root Documents

**Files:** `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`

**Scope:** Light review. `CONTRIBUTING.md` has stale architecture references (queue_service, Essentia isolation rule is wrong). Others may be fine.

### Surface 6: Frontend Documentation

**Location:** `frontend/README.md`

**Scope:** The directory structure is completely stale. Needs rewrite to reflect current `features/` structure.

---

## Confirmed Decisions

1. **API reference:** Delete `docs/user/api_reference.md`. Point users to FastAPI's built-in `/docs` endpoint instead.
2. **Upstream docs:** Keep in `docs/upstream/`, exclude from MkDocs navigation. Agents find it by searching `docs/`, users don't see it in site nav.
3. **docs/api/ folder:** Already deleted by user.
4. **Subdomain READMEs:** Create ALL of them (~35-40 files). Every folder with code gets a README — it's the pattern.
5. **Screenshots:** Manual capture by user. Excluded from implementation plans.
6. **Frontend README:** Excluded from this scope. Frontend docs handled separately.

---

## Implementation Decomposition

Given the scale (~50+ files to create/rewrite), this splits into three implementation rounds with 6 parts:

### Round 1: Infrastructure Foundation
**Parts A + B** (no dependencies, can be parallel)

**Part A: MkDocs Setup + Root Documents**
- Install mkdocs-material, create `mkdocs.yml` at project root
- Create target folder structure in `docs/`
- Delete `docs/user/api_reference.md`
- Rewrite `docs/index.md` as MkDocs landing page
- Refresh `readme.md` (fix stale refs, verify accuracy)
- Refresh `CONTRIBUTING.md` (fix stale architecture refs)
- Verify site builds and serves

**Part B: Instruction Files Refresh**
- Audit all 15 `.github/instructions/` files for stale references
- Add persistence-only-via-components rule to all relevant instruction files
- Remove references to queues, TensorFlow, SQL, Essentia-as-backend
- Verify directory structures mentioned are current

### Round 2: In-Codebase Documentation
**Parts C + D** (depend on Round 1 for accurate rules established in instruction files)

**Part C: Layer Document Rewrites**
- Rewrite all 6 `{LAYER}.md` files with accurate directory trees, rules, patterns
- Ensure persistence-only-via-components rule in every relevant doc
- Ensure every stale reference (queues, TF, SQL, Essentia-as-backend) is removed

**Part D: Subdomain README.md Files**
- Create ~35-40 README.md files across all subfolders
- Each follows the template: summary, files table, rules, relationships

### Round 3: Public Documentation
**Parts E + F** (depend on Round 2 for architecture accuracy)

**Part E: Developer Documentation Rewrite**
- Rewrite all `docs/dev/` files
- Must reference current architecture from Round 2's layer docs for consistency

**Part F: User Documentation Rewrite**
- Rewrite all `docs/user/` files except removed api_reference.md
- Create `troubleshooting.md`
- Write for non-technical end users

---

## Completion Criteria

- [ ] `mkdocs serve` renders a navigable documentation site
- [ ] Every `nomarr/` subfolder with Python code has a README.md
- [ ] All 6 layer docs reflect current directory structure and rules
- [ ] Persistence-only-via-components rule appears in all relevant docs
- [ ] Zero references to: TensorFlow, SQL, queues, `ml_backend_essentia_comp.py` as ML entry point, `entity_keys_comp.py`, `sql_helper.py`, `base.py` worker class
- [ ] `docs/user/` is written for non-technical end users
- [ ] `docs/dev/` accurately describes current architecture
- [ ] Root README reflects current features and setup
- [ ] `CONTRIBUTING.md` references current patterns
- [ ] Frontend README reflects current structure
- [ ] `docs/api/` removed
- [ ] `.github/instructions/` files have no stale references
- [ ] All docs pass a coherence check (no cross-document contradictions)

---

## Out of Scope

- Writing new documentation for features that don't exist yet (roadmap items are noted, not documented)
- Automated API doc generation (FastAPI handles this)
- Screenshot capture (manual task by user)
- Frontend README rewrite (handled separately — frontend needs dedicated attention)
- `code-intel/` documentation (separate project)
- `navidrome-plugin/` documentation (separate project)
- Upstream doc content changes (we don't author those — just organize them)
- `copilot-instructions.md` rewrite (it's maintained separately and is mostly current)
