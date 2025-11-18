# API Discovery Tools

**Audience:** Developers, documentation writers, and AI agents working with Nomarr's codebase.

Nomarr provides two utility scripts to help explore module APIs and dependencies without guessing or reading full source files.

## Overview

These tools are particularly useful for:

- **Updating documentation** to reflect actual APIs
- **Writing tests** - see what needs to be mocked
- **Understanding module structure** - what functions/classes are available
- **Avoiding guesswork** - get real function signatures instead of assumptions

Both tools automatically mock heavy ML dependencies (essentia, tensorflow, scipy) so they're safe to run on development machines without GPU or ML libraries installed.

## discover_api.py

Shows the public API of any Python module in Nomarr.

### Usage

```bash
python scripts/discover_api.py <module.path>
```

### Examples

**Discover database operations:**

```bash
python scripts/discover_api.py nomarr.persistence.db
```

**Discover web endpoints:**

```bash
python scripts/discover_api.py nomarr.interfaces.api.endpoints.web
```

**Discover workflow functions:**

```bash
python scripts/discover_api.py nomarr.workflows.process_file
```

**Discover ML inference API:**

```bash
python scripts/discover_api.py nomarr.ml.inference
```

### Output Format

The tool displays:

- **Functions** - Name, parameters, return type, and docstring summary
- **Classes** - Name, methods, and docstring summary
- **Constants** - Module-level constants and their values

Example output:

```
================================================================================
Module: nomarr.ml.inference
================================================================================

🔧 FUNCTIONS:

  def compute_embeddings_for_backbone(backbone: 'str', emb_graph: 'str',
      target_sr: 'int', segment_s: 'float', hop_s: 'float', path: 'str',
      min_duration_s: 'int', allow_short: 'bool') -> 'tuple[np.ndarray, float]':
      Compute embeddings for an audio file using a specific backbone...

  def make_head_only_predictor_batched(head_info: 'HeadInfo',
      embeddings_2d: 'np.ndarray', batch_size: 'int' = 11) -> 'Callable[[], np.ndarray]':
      Create a batched predictor that processes segments in fixed-size batches...

📌 CONSTANTS:

  HAVE_TF = True
  TYPE_CHECKING = False
```

### Important Notes

- **Do NOT use the `--summary` flag** - it only shows function/class names without signatures, which is not helpful for documentation or development work
- Always run without flags to get full API details
- The tool handles import errors gracefully by mocking unavailable dependencies

## discover_imports.py

Shows what a module imports and uses, helping identify test mocking requirements.

### Usage

```bash
python scripts/discover_imports.py <module.path>
```

### Examples

**Check what process_file workflow imports:**

```bash
python scripts/discover_imports.py nomarr.workflows.process_file
```

**Check service dependencies:**

```bash
python scripts/discover_imports.py nomarr.services.processing
```

**Check interface dependencies:**

```bash
python scripts/discover_imports.py nomarr.interfaces.api.endpoints.public
```

### Output Format

The tool displays:

- **Direct imports** - `import X` statements
- **From imports** - `from X import Y` statements
- **Function calls** - Functions called within the module
- **Class instantiations** - Classes instantiated in the code

Example output:

```
Module: nomarr.workflows.process_file

Direct Imports:
  import logging

From Imports:
  from pathlib import Path
  from nomarr.persistence.db import Database
  from nomarr.ml.inference import compute_embeddings_for_backbone
  from nomarr.tagging.aggregation import aggregate_tags

Function Calls:
  - compute_embeddings_for_backbone
  - aggregate_tags
  - Path.resolve
  - logging.info

Class Instantiations:
  - Path
```

### Use Cases

**Writing tests:**

```python
# After running discover_imports.py, you know what to mock:
@patch('nomarr.workflows.process_file.compute_embeddings_for_backbone')
@patch('nomarr.workflows.process_file.aggregate_tags')
def test_process_file_workflow(mock_aggregate, mock_compute):
    # Test implementation
    pass
```

**Verifying architecture boundaries:**
Check that workflows don't import from services or interfaces, maintaining clean architecture separation.

## Best Practices

1. **Before writing documentation** - Run `discover_api.py` to verify actual function signatures
2. **Before writing tests** - Run `discover_imports.py` to see what needs mocking
3. **After refactoring** - Verify API changes haven't broken expected interfaces
4. **When exploring unfamiliar code** - Use these tools instead of reading full source files

## Technical Details

### Mock Handling

Both tools automatically mock:

- `essentia` and `essentia_tensorflow`
- `tensorflow` and related TF modules
- `scipy` (when needed)

This allows the scripts to safely import and inspect modules without requiring ML dependencies or GPU hardware.

### Limitations

- **Only shows public APIs** - Private functions (starting with `_`) are excluded
- **Static analysis only** - Does not execute code, so dynamic behavior isn't captured
- **Import-time dependencies** - Modules must be importable for inspection

### Location

- `scripts/discover_api.py` - API discovery tool
- `scripts/discover_imports.py` - Import/call discovery tool

Both are standalone Python scripts with no additional dependencies beyond the standard library.
