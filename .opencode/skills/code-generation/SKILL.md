---
name: code-generation
description: Use when generating boilerplate code, __init__.py files, or test scaffolds. Provides scripts that generate consistent, convention-following code.
---

# Code Generation Tools

**When to use:** When creating new modules, updating exports, or scaffolding tests.

---

## generate_inits.py

**Purpose:** Auto-generate `__init__.py` files with proper `__all__` exports.

**Use when:**

- Adding new public functions/classes to a module
- Creating a new package
- Cleaning up exports after refactoring

**Usage:**

```bash
python scripts/human-scripts/generate_inits.py
```

**How it works:**

1. Recursively scans every package under `nomarr/` for public names (classes, functions, constants), skipping the config's `excluded_packages` and any `__init__.py` marked manually-managed
2. Generates `__init__.py` with `__all__` listing public exports
3. Uses config from `scripts/human-scripts/configs/generate_inits_config.yml`
4. Ruff-formats each generated file (best-effort)

**What it exports:**

- Top-level classes and functions (not private `_*`)
- Module-level constants (ALL_CAPS)
- Filters out banned exports per config

**Decision rule:** After adding public functions to a module, run this to update exports.

---

## generate_tests.py

**Purpose:** Generate test scaffolds with smart assertions and proper fixtures.

**Use when:**

- Adding tests for a new module
- Creating test structure for existing code
- Getting a head start on test implementation

**Usage:**

```bash
# Generate tests for a module
python scripts/human-scripts/generate_tests.py nomarr.components.tagging.tag_write_comp --output tests/unit/components/test_tag_write_comp.py

# Preview without writing
python scripts/human-scripts/generate_tests.py nomarr.components.tagging.tag_write_comp --preview

# Specify layer for auto-fixture selection (data | services | ml | interfaces)
python scripts/human-scripts/generate_tests.py nomarr.services.infrastructure.pipeline_svc --layer services
```

**CLI:** positional `module`, plus `--output/-o` (default auto-derives `tests/unit/<pkg>/test_<module>.py`), `--preview` (prints the scaffold without writing), and `--layer` with choices `data | services | ml | interfaces` (auto-detected from the module path if omitted).

**Generated tests include:**

- Proper pytest structure
- Fixtures for layer-appropriate mocks (DB, config, ML backends)
- Test functions for each public method
- Type-appropriate assertions

---

## Workflow: Adding a New Module

1. **Create the module** with your functions/classes

2. **Update exports:**

   ```bash
   python scripts/human-scripts/generate_inits.py
   ```

3. **Generate test scaffold:**

   ```bash
   python scripts/human-scripts/generate_tests.py nomarr.components.new_comp --output tests/unit/components/test_new_comp.py --preview
   
   # If preview looks good:
   python scripts/human-scripts/generate_tests.py nomarr.components.new_comp --output tests/unit/components/test_new_comp.py
   ```

4. **Fill in test implementations**

---

## Workflow: After Refactoring Exports

```bash
# After adding/removing public functions:
python scripts/human-scripts/generate_inits.py

# Review changes:
git diff nomarr/*/__init__.py
```

---

## Configuration

### generate_inits_config.yml

Located at `scripts/human-scripts/configs/generate_inits_config.yml`:

```yaml
# Names that should never be re-exported in generated __init__.py files
banned_exports:
  - get_config

# Marker that flags an __init__.py as manually-managed (never overwritten)
manual_init_marker: "# MANUAL_INIT"
manual_indicators:
  - APIRouter

# Max line length for single-line imports
max_import_line_length: 88

# Packages with custom __init__.py logic (paths relative to nomarr/)
excluded_packages:
  - nomarr/interfaces/api
  - nomarr/interfaces/cli
  - nomarr/services
  - nomarr/persistence
  - nomarr/helpers
  - nomarr/components/ml
  - nomarr/workflows
```

`generate_inits.py` writes an `__init__.py` for every package under `nomarr/` not in `excluded_packages` and not marked manually-managed. Review generated files with `git diff` before committing.

---

## Key Rules

- **Run `scripts/human-scripts/generate_inits.py` after adding public symbols** — keeps exports consistent; it skips `excluded_packages` and files marked `# MANUAL_INIT`
- **Use `--preview` before writing test files** — verify structure is correct
- **Generated tests are scaffolds** — you still need to fill in assertions and edge cases
- `--layer` only accepts `data | services | ml | interfaces`; pass a service/workflow module as `--layer services` where fixture selection applies
