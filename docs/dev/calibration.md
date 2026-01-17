# Calibration System

## Overview

The calibration system tracks statistical drift in ML model outputs to minimize unnecessary file re-tagging during model development. It uses industry-standard distribution drift metrics to detect when calibration parameters become unstable.

## Architecture

### Two Modes

**Production Mode (default)**: `calibrate_heads: false`

- Uses stable reference calibration files (`*-calibration.json`)
- Downloaded from pre-made calibration repository (nom-cal)
- Optimized for end users who just want stable tagging

**Development Mode**: `calibrate_heads: true`

- Generates versioned calibration files (`*-calibration-v{N}.json`)
- Tracks drift metrics in database (`calibration_runs` table)
- Automatically updates reference files when heads become unstable
- Used for model development and calibration tuning

### Database Schema

The `calibration_runs` collection tracks each calibration generation:

```json
// ArangoDB document structure
{
  "_key": "effnet_mood_happy_3",     // Composite key: model_head_version
  "model_name": "effnet",            // e.g., "effnet"
  "head_name": "mood_happy",         // e.g., "mood_happy"
  "version": 3,                      // Run number (increments together for all heads)
  "file_count": 1500,                // Number of files used to generate calibration
  "timestamp": 1737158400000,        // Unix timestamp (milliseconds)
  "p5": 0.15,                        // 5th percentile score
  "p95": 0.85,                       // 95th percentile score
  "range": 0.70,                     // p95 - p5
  "reference_version": 2,            // Version used as reference for drift comparison
  "apd_p5": 0.005,                   // Absolute Percentile Drift (p5)
  "apd_p95": 0.008,                  // Absolute Percentile Drift (p95)
  "srd": 0.02,                       // Scale Range Drift
  "jsd": 0.01,                       // Jensen-Shannon Divergence
  "median_drift": 0.003,             // Median drift (robust to outliers)
  "iqr_drift": 0.01,                 // IQR drift (spread measurement)
  "is_stable": true                  // Overall stability decision (boolean)
}
```

### File Management

**Versioned Files**: `mood_happy-calibration-v3.json`

- Generated during each calibration run
- Contains p5/p95 parameters per label
- Preserved for reproducibility

**Reference Files**: `mood_happy-calibration.json`

- Updated when head becomes unstable (or first run)
- Stable heads keep their existing reference (minimizes re-tagging)
- Used by production mode

### Drift Metrics

The system uses five complementary metrics from ML monitoring best practices:

#### 1. Absolute Percentile Drift (APD)

Measures how much percentiles shift between calibrations.

```python
APD_p5 = |new_p5 - ref_p5|
APD_p95 = |new_p95 - ref_p95|
```

**Threshold**: `0.01` (very stable)

- Values < 0.01 indicate minimal drift
- Sensitive to small changes in distribution tails

#### 2. Scale Range Drift (SRD)

Measures change in the spread of the distribution.

```python
SRD = |new_range - ref_range| / ref_range
```

**Threshold**: `0.05` (excellent stability)

- < 5% change in range indicates stable scaling
- Helps detect compression/expansion of score distributions

#### 3. Jensen-Shannon Divergence (JSD)

Measures similarity between score distributions using information theory.

```python
JSD = sqrt(0.5 * KL(P || M) + 0.5 * KL(Q || M))
where M = 0.5 * (P + Q)
```

**Threshold**: `0.1` (similar distributions)

- 0 = identical distributions
- 1 = completely different distributions
- More sophisticated than simple percentile comparison

#### 4. Median Drift

Measures shift in the central tendency (robust to outliers).

```python
median_drift = |new_median - ref_median|
```

**Threshold**: `0.05`

- Complements APD by focusing on center of distribution
- Less sensitive to extreme values

#### 5. IQR Drift

Measures change in distribution spread (robust alternative to range).

```python
IQR_drift = |new_IQR - ref_IQR| / ref_IQR
```

**Threshold**: `0.1`

- Interquartile range = Q3 - Q1
- More robust than range (ignores outliers)

### Stability Decision

A head is considered **stable** if ALL metrics pass their thresholds:

```python
is_stable = (
    apd_p5 < 0.01 and
    apd_p95 < 0.01 and
    srd < 0.05 and
    jsd < 0.1 and
    median_drift < 0.05 and
    iqr_drift < 0.1
)
```

If any metric fails, the head is **unstable** and its reference file is updated.

### Versioning Strategy

**Version = Run Number** (Option A)

- All heads increment version together (v1, v2, v3...)
- Stability tracked independently per head via `is_stable` flag
- `reference_version` pointer tracks which version is currently the reference

Example:

```
Run 1 (1000 files):
  mood_happy: unstable → update reference to v1
  danceability: unstable → update reference to v1

Run 2 (2000 files):
  mood_happy: STABLE → keep reference at v1
  danceability: unstable → update reference to v2

Run 3 (3000 files):
  mood_happy: unstable → update reference to v3
  danceability: STABLE → keep reference at v2
```

Result: `mood_happy` uses v3 calibration, `danceability` uses v2.

## Configuration

In `config/config.yaml`:

```yaml
# Calibration mode (dev feature)
calibrate_heads: false

# Repository for downloading pre-made calibrations
calibration_repo: "https://github.com/xiaden/nom-cal"

# Drift detection thresholds
calibration_drift_apd: 0.01 # Absolute Percentile Drift
calibration_drift_srd: 0.05 # Scale Range Drift
calibration_drift_jsd: 0.1 # Jensen-Shannon Divergence
calibration_drift_median: 0.05 # Median drift
calibration_drift_iqr: 0.1 # IQR drift
```

## API Endpoints

All calibration endpoints require `calibrate_heads: true` (return 403 otherwise).

### POST /admin/calibration/run

Generate calibration from all library files.

**Request**: Empty body

**Response**:

```json
{
  "status": "ok",
  "calibration": {
    "version": 3,
    "library_size": 3500,
    "heads": {
      "effnet/mood_happy": {
        "model_name": "effnet",
        "head_name": "mood_happy",
        "labels": {
          "happy": { "p5": 0.1, "p95": 0.9, "method": "minmax" }
        },
        "drift_metrics": {
          "apd_p5": 0.023,
          "apd_p95": 0.015,
          "srd": 0.067,
          "jsd": 0.142,
          "median_drift": 0.031,
          "iqr_drift": 0.089,
          "is_stable": false,
          "failed_metrics": ["apd_p5", "jsd"]
        },
        "is_stable": false,
        "reference_version": 2
      }
    },
    "saved_files": {
      "effnet/mood_happy": "/app/models/effnet/heads/mood_happy-calibration-v3.json"
    },
    "reference_updates": {
      "effnet/mood_happy": "updated"
    },
    "summary": {
      "total_heads": 17,
      "stable_heads": 12,
      "unstable_heads": 5
    }
  }
}
```

### GET /admin/calibration/history

Query calibration run history.

**Query Parameters**:

- `model`: Filter by model name (optional)
- `head`: Filter by head name (optional)
- `limit`: Max results (default: 50)

**Response**:

```json
{
  "status": "ok",
  "count": 1,
  "runs": [
    {
      "id": 42,
      "model_name": "effnet",
      "head_name": "mood_happy",
      "version": 3,
      "file_count": 3500,
      "timestamp": 1704067200000,
      "p5": 0.12,
      "p95": 0.89,
      "range": 0.77,
      "reference_version": 2,
      "apd_p5": 0.023,
      "apd_p95": 0.015,
      "srd": 0.067,
      "jsd": 0.142,
      "median_drift": 0.031,
      "iqr_drift": 0.089,
      "is_stable": false
    }
  ]
}
```

Note: `is_stable` is a boolean (true/false). `timestamp` is Unix milliseconds.

### POST /admin/calibration/retag-all

Bulk enqueue all tagged files for re-tagging with final stable calibration.

**Request**: Empty body

**Response**:

```json
{
  "enqueued": 8423,
  "message": "Enqueued 8423 tagged files for re-tagging"
}
```

## Workflow

### Development Workflow (calibrate_heads=true)

1. **Tag initial batch** (e.g., 1000 files):

   ```bash
   # Files are tagged and stored in library_files table
   # Raw scores stored in library_tags table
   ```

2. **Generate first calibration**:

   ```bash
   curl -X POST http://localhost:8356/admin/calibration/run \
     -H "Authorization: Bearer <API_KEY>"
   ```

   - Creates v1 calibration for all heads
   - All heads marked unstable (first run)
   - Reference files updated to v1

3. **Tag more files** (e.g., 2000 total):

   ```bash
   # Continue tagging with v1 calibration
   ```

4. **Generate second calibration**:

   ```bash
   curl -X POST http://localhost:8356/admin/calibration/run \
     -H "Authorization: Bearer <API_KEY>"
   ```

   - Creates v2 calibration
   - Compares to v1 (reference)
   - Some heads stable (keep v1), others unstable (update to v2)

5. **Repeat until convergence**:

   - Tag more files
   - Run calibration
   - Check history for stability trends
   - Once all heads stable, proceed to final re-tag

6. **Final re-tag with stable calibration**:
   ```bash
   curl -X POST http://localhost:8356/admin/calibration/retag-all \
     -H "Authorization: Bearer <API_KEY>"
   ```
   - Enqueues all tagged files
   - Uses final stable calibration (each head's reference version)
   - Files written with consistent, stable tags

### Production Workflow (calibrate_heads=false)

1. **Download pre-made calibrations** (manual for now):

   ```bash
   # Clone nom-cal repository
   git clone https://github.com/xiaden/nom-cal

   # Copy reference files to models directory
   cp nom-cal/essentia/effnet/*.cal.json models/effnet/heads/
   ```

2. **Tag files**:
   ```bash
   # Files automatically use reference calibration files
   # No drift tracking, just stable tagging
   ```

## Interpreting Results

### Drift Metrics Interpretation

| Metric       | Excellent | Good      | Acceptable | Unstable |
| ------------ | --------- | --------- | ---------- | -------- |
| APD (p5/p95) | < 0.01    | 0.01-0.02 | 0.02-0.05  | > 0.05   |
| SRD          | < 0.05    | 0.05-0.10 | 0.10-0.20  | > 0.20   |
| JSD          | < 0.1     | 0.1-0.2   | 0.2-0.3    | > 0.3    |
| Median       | < 0.05    | 0.05-0.10 | 0.10-0.20  | > 0.20   |
| IQR          | < 0.1     | 0.1-0.2   | 0.2-0.3    | > 0.3    |

### Common Patterns

**Early instability**: First 2-3 calibrations often unstable as distribution settles.

**Gradual stabilization**: As more files are tagged, drift metrics trend toward zero.

**Stubborn heads**: Some heads may take longer to stabilize (e.g., rare genres, edge cases).

**Reference version gaps**: Stable heads keep old references (e.g., mood_happy at v1, danceability at v5).

## Testing

### Manual Testing

1. Enable calibration mode:

   ```yaml
   # config/config.yaml
   calibrate_heads: true
   ```

2. Tag test batch (500-1000 files):

   ```bash
   python -m nomarr.interfaces.cli.main run /music/*.mp3
   ```

3. Generate calibration:

   ```bash
   curl -X POST http://localhost:8356/admin/calibration/run \
     -H "Authorization: Bearer <API_KEY>"
   ```

4. Check results in database:

   ```bash
   # Using arangosh
   docker exec -it nomarr-arangodb arangosh \
     --server.username nomarr \
     --server.password "<password>" \
     --server.database nomarr \
     --javascript.execute-string '
       db._query(`
         FOR run IN calibration_runs
           SORT run.version DESC, run.model_name, run.head_name
           RETURN KEEP(run, "model_name", "head_name", "version", "is_stable", "apd_p5", "apd_p95", "srd", "jsd")
       `).toArray().forEach(r => print(JSON.stringify(r)))
     '
   ```

5. Verify reference files created:

   ```bash
   ls -l models/effnet/heads/*-calibration.json
   ls -l models/effnet/heads/*-calibration-v*.json
   ```

6. Tag another batch (check uses new calibration):

   ```bash
   python -m nomarr.interfaces.cli.main run /music/more/*.mp3
   ```

7. Generate second calibration (should show stability):
   ```bash
   curl -X POST http://localhost:8356/admin/calibration/run \
     -H "Authorization: Bearer <API_KEY>"
   ```

### Automated Testing

See `tests/test_calibration.py` (TODO: create comprehensive test suite).

## Troubleshooting

### "Calibration API endpoints are disabled"

**Cause**: `calibrate_heads: false` in config.

**Solution**: Set `calibrate_heads: true` to enable dev mode.

### All heads unstable every run

**Cause**: Insufficient sample size or highly variable data.

**Solution**: Tag more files (aim for 1000+ per calibration run).

### Specific head never stabilizes

**Cause**: Inherent variability in that classification (e.g., rare labels, ambiguous concepts).

**Solution**:

- Check label distribution (too few examples?)
- Consider adjusting thresholds for that specific head
- May need more training data or model refinement

### Reference files not updating

**Cause**: All heads marked stable (expected behavior).

**Solution**: This is correct - stable heads keep existing references.

### Version numbers not incrementing

**Cause**: Database error or configuration issue.

**Solution**: Check logs for CalibrationService errors.

## Future Enhancements

- [ ] Automated calibration download from nom-cal repository
- [ ] Per-head threshold overrides in config
- [ ] Visualization of drift trends over time
- [ ] Calibration quality reports (label distribution analysis)
- [ ] Automatic triggering after N new files tagged
- [ ] Smart sample selection (diversity-aware sampling)
