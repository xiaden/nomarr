# Automated Slop & Drift Detection - Setup Complete!

## ✅ What's Installed

The following tools are now part of your QC suite:

1. **radon** - Complexity metrics (cyclomatic, maintainability index)
2. **import-linter** - Architecture violation detection  
3. **wily** - Track complexity trends over time (git history)
4. **flake8** + plugins - Code smell detection:
   - `flake8-cognitive-complexity` - Understandability metrics
   - `flake8-simplify` - Overcomplicated pattern detection
   - `flake8-eradicate` - Commented-out code finder
   - `flake8-variables-names` - Generic variable name detection

## 🎯 What We Discovered (First Run)

Running `python scripts/detect_slop.py` revealed these patterns in your codebase:

### **Critical Complexity Issues** (Functions that are too complex)

| File | Function | Complexity | Status |
|------|----------|------------|--------|
| `core/processor.py` | `process_file()` | **42** 😱 | Needs refactoring |
| `core/library_scanner.py` | `_extract_metadata()` | **29** | Needs refactoring |
| `core/library_scanner.py` | `scan_library()` | **20** | Needs refactoring |
| `data/db.py` | `get_tag_summary()` | **21** | Needs refactoring |

**Target:** Cyclomatic complexity should be < 10 for maintainability.

### **AI Slop Patterns Found**

#### 1. **Single-Letter Variables** (lazy AI naming)
- `h` - appears in `processor.py`, `endpoints/admin.py`, `endpoints/public.py`  
  Likely means: "head" (ML model head)
- `s` - appears throughout `endpoints/web.py` (30+ occurrences!)  
  Likely means: "service" 
- `g` - appears in admin/public endpoints  
  Likely means: "g" global context (FastAPI dependency)
- `j` - job
- `y` - audio samples
- `S` - ??

**Fix:** Use descriptive names: `head`, `service`, `job`, `audio_samples`

#### 2. **Generic Variable Names**
- `val` - Should be `tag_value`, `threshold`, `setting`, etc.
- `file` - Shadows Python built-in, should be `file_path` or `audio_file`

#### 3. **Commented-Out Code** (should be deleted)
- `core/processor.py:155`
- `interfaces/api/endpoints/public.py:166`
- `interfaces/api/endpoints/web.py:546`

**Action:** Delete these or move to git history.

#### 4. **Over-Complicated Exception Handling**
Multiple places using:
```python
try:
    value = float(tag)
except (ValueError, IndexError):
    pass
```

**Should be:**
```python
from contextlib import suppress

with suppress(ValueError, IndexError):
    value = float(tag)
```

### **Architecture Violations**

Import-linter failed to run (command issue), but will detect:
- Services importing from interfaces ❌
- Core importing from services ❌  
- Data importing from business logic ❌

**Status:** Need to fix command, see `.importlinter` config file.

## 📊 Maintainability Scores

Most files scored **A** (excellent maintainability), but watch these:

- Files with **D** or **F** ratings need immediate attention
- Files with **C** rating should be on your refactoring list

## 🚀 How to Use

### Run Full Detection
```bash
# Activate venv
.venv\Scripts\Activate.ps1

# Run all checks
python scripts/detect_slop.py
```

Output saved to:
- `qc_reports/slop_detection_TIMESTAMP.txt` - Human-readable report
- `qc_reports/slop_detection_TIMESTAMP.json` - Machine-readable data

### Check Single File Complexity
```bash
radon cc nomarr/core/processor.py -s
```

### Check Architecture Rules
```bash
lint-imports
```

### Find Commented Code
```bash
eradicate nomarr/ --recursive
```

## 🎯 Priority Actions

Based on first run, here's what to tackle:

### **P0 - Critical** (Do First)
1. **Refactor `process_file()`** in `core/processor.py`
   - Complexity 42 → Target < 10
   - Extract helper functions for each phase (load audio, run inference, write tags)
   
2. **Refactor `_extract_metadata()`** in `core/library_scanner.py`
   - Complexity 29 → Target < 10
   - Extract tag parsing logic to separate functions

### **P1 - High** (Do Soon)
3. **Rename single-letter variables**
   - `h` → `head`
   - `s` → `service`
   - `g` → `state` or `context`
   - `j` → `job`
   
4. **Delete commented-out code** (3 locations found)

5. **Fix import-linter command** so architecture checks work

### **P2 - Medium** (Do Eventually)
6. **Simplify exception handling** with `contextlib.suppress()`
7. **Refactor complex CLI commands** (`admin_reset`, `remove`)
8. **Review `get_tag_summary()` complexity** in `db.py`

## 📈 Tracking Over Time

Use **wily** to track complexity trends:

```bash
# Initialize (first time only)
wily build

# Check complexity diff
wily diff nomarr/core/processor.py

# Report on trends
wily report nomarr/
```

This shows if refactoring is making things better or worse!

## 🔧 Configuration

### Adjust Thresholds

Edit `scripts/detect_slop.py` to tune sensitivity:

```python
"--max-complexity", "10",  # Default: 15, Strict: 10
"--max-cognitive-complexity", "10",  # Default: 15, Strict: 10
```

### Architecture Rules

Edit `.importlinter` to define/modify layer contracts:

```ini
[importlinter:contract:1]
name = Services cannot import from interfaces
type = forbidden
source_modules = nomarr.services
forbidden_modules = nomarr.interfaces
```

## 💡 What This Teaches You

By running these tools regularly, you'll:

1. **Learn slop patterns** - Once you see "single letter variable" flagged 50 times, you'll recognize it instantly
2. **Understand complexity** - See which functions are too complex BEFORE they become unmaintainable
3. **Catch architecture drift** - Know immediately when layers are violated
4. **Build quality habits** - The more you see these reports, the less you'll create these patterns

## 🎓 Next Steps

1. ✅ Run `python scripts/detect_slop.py` (DONE - you just did this!)
2. ⏳ Fix P0 issues (complexity refactoring)
3. ⏳ Fix import-linter command  
4. ⏳ Add to CI pipeline (fail PR if complexity increases)
5. ⏳ Set up wily for trend tracking
6. ⏳ Create git pre-commit hook to block slop

---

**TL;DR:** These tools found **real patterns** in your code - high complexity functions, single-letter variables, commented-out code, and overcomplicated exception handling. Now you know what to look for!
