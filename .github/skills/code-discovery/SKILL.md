---
name: code-discovery
description: Use when exploring codebase structure, discovering module APIs, understanding imports, or checking what functions exist. Provides scripts that replace manual file reading with structured discovery.
---

# Code Discovery Tools

**When to use:** Before writing code that calls existing modules, or when exploring unfamiliar parts of the codebase.

**Instead of:** Reading entire files to find function signatures, use these scripts.

---

## discover_api.py

**Purpose:** Inspect real module APIs—functions, classes, constants, signatures.

**Use when:**
- About to call a function but unsure of its parameters
- Exploring a module's public surface
- Verifying an API exists before using it

**Usage:**

```bash
# Text output (human-readable)
python scripts/discover_api.py nomarr.workflows.processing.process_file_wf

# JSON output (machine-readable)
python scripts/discover_api.py nomarr.components.ml --format=json

# Example output:
# ================================================================================
# Module: nomarr.components.ml.ml_embed_comp
# ================================================================================
#
# FUNCTIONS:
#
#   def compute_embeddings(file_path: str, models_dir: str, backbone: str) -> np.ndarray:
#       Compute embeddings for an audio file.
```

**Decision rule:** If you're about to `read_file` a module just to find what functions exist → use `discover_api.py` instead.

---

## discover_import_chains.py

**Purpose:** Trace import dependencies from a module and detect architecture violations.

**Use when:**
- Checking if a new import would violate layering rules
- Debugging circular imports
- Understanding what a module depends on

**Usage:**

```bash
# Trace imports from a module
python scripts/discover_import_chains.py nomarr.workflows.library.scan_library_wf

# JSON output
python scripts/discover_import_chains.py nomarr.services.domain.tagging_svc --format=json

# Can also accept file paths
python scripts/discover_import_chains.py nomarr/interfaces/api/v1/library.py
```

**Output shows:**
- Full import chain (what imports what)
- Architecture violations (e.g., "workflow imports service")
- Depth-limited to prevent infinite recursion

---

## build_code_graph.py

**Purpose:** Build a complete code graph for dead code detection and reachability analysis.

**Use when:**
- Checking if code is reachable from entrypoints
- Finding unused functions/classes
- Understanding call relationships

**Usage:**

```bash
python scripts/build_code_graph.py
```

**Output:** Writes to `scripts/outputs/code_graph.json` with:
- Nodes: All modules, classes, functions
- Edges: CONTAINS, IMPORTS, CALLS relationships
- Reachability from interface entrypoints

**Use with:** `check_dead_nodes.py` to analyze the graph.

---

## Workflow: Discovering an Unfamiliar Module

1. **Find the module's API:**
   ```bash
   python scripts/discover_api.py nomarr.components.tagging
   ```

2. **Check its dependencies:**
   ```bash
   python scripts/discover_import_chains.py nomarr.components.tagging
   ```

3. **Verify no violations before adding imports:**
   ```bash
   python scripts/discover_import_chains.py nomarr.workflows.new_workflow_wf
   ```

---

## Common Patterns

### Before calling a function

```bash
# Instead of reading the whole file:
python scripts/discover_api.py nomarr.persistence.db

# Get exact signature:
# def get_next_job(self, status: str = "pending") -> QueueJobDict | None:
```

### Before adding an import

```bash
# Check if it would violate architecture:
python scripts/discover_import_chains.py nomarr.services.domain.tagging_svc

# If you see "VIOLATION: services importing interfaces" → don't add that import
```

### Understanding a subsystem

```bash
# Get all public APIs in a package
python scripts/discover_api.py nomarr.components.ml
python scripts/discover_api.py nomarr.components.ml.ml_embed_comp
python scripts/discover_api.py nomarr.components.ml.ml_inference_comp
```

---

## Key Rule

**Never guess function names, parameters, or return types.**

Use `discover_api.py` to verify APIs before calling them. This prevents:
- Inventing non-existent functions
- Wrong parameter orders
- Type mismatches
