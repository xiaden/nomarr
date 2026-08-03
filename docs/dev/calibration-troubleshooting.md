# Calibration System Troubleshooting

## Overview

This guide explains common questions and potential confusion points when working with the per-label calibration system.

---

## Sample Count Interpretation

### Expected Behavior

**Per-label calibration uses file count, not prediction aggregation.**

For a library with 30,000 audio files:

- **Binary classification head** (e.g., `gender` with labels `male`, `female`):
  - Male calibration: ~30,000 samples
  - Female calibration: ~30,000 samples
  - Each sample represents one file's prediction for that specific label

### Why Not 60,000 Total?

**Binary predictions are complementary but calibrated independently.**

- Each file gets ML predictions for both `male` and `female` (e.g., `male=0.85`, `female=0.15`)
- Old per-head system: Aggregated both predictions → ~60,000 samples → single P5/P95 range
- New per-label system: Calibrates each label separately → ~30,000 samples each → independent P5/P95 ranges

**Rationale:**

- Male confidence distributions differ from female confidence distributions
- A song predicted as 85% male should use male-specific calibration curve
- Mixing complementary predictions (male=0.85, female=0.15) into one histogram obscures label-specific patterns

### Verification Query

```sql
-- Count samples per label for gender head
SELECT label, histogram->>'n' AS sample_count,
       histogram->'percentiles'->>'p5' AS p5,
       histogram->'percentiles'->>'p95' AS p95
FROM calibration_state
WHERE head = 'gender';

-- Expected output (for 30k file library):
--  label  | sample_count |  p5  | p95
-- --------+-------------+------+------
--  male   | ~30000      |  X   |  Y
--  female | ~30000      |  A   |  B
-- Note: X ≠ A and Y ≠ B (independent distributions)
```

---

## Calibration Document Count

### Expected State

**23 calibration documents total** (one per label across all heads):

 | Head Type | Head Name | Labels | Document Count |
 | ----------- | ----------- | -------- | ---------------- |
 | Binary | `gender` | male, female | 2 |
 | Binary | `voice_instrumental` | instrumental, voice | 2 |
 | Binary | `mood_acoustic` | acoustic, electric | 2 |
 | Binary | `mood_aggressive` | aggressive, relaxed | 2 |
 | Binary | `mood_electronic` | acoustic, electronic | 2 |
 | Binary | `mood_happy` | happy, sad | 2 |
 | Binary | `mood_party` | party, nonParty | 2 |
 | Binary | `mood_relaxed` | relaxed, energetic | 2 |
 | Regression | `approachability` | approachability | 1 |
 | Regression | `danceability` | danceability | 1 |
 | Regression | `engagement` | engagement | 1 |
 | Binary | `timbre` | bright, dark | 2 |
 | Binary | `tonal_atonal` | tonal, atonal | 2 |

**Total: 23 documents**

### Verification Query

```sql
-- Count documents per head
SELECT head, COUNT(*) AS label_count
FROM calibration_state
GROUP BY head
ORDER BY head;

-- Expected: Binary heads → 2 docs each, Regression heads → 1 doc each
```

---

## Common Issues

### Issue: "Sample count seems too low"

**Symptom:** Binary head shows ~30k samples per label instead of expected ~60k total

**Explanation:** This is correct behavior. Per-label calibration uses file count (30k files → 30k samples per label), not aggregated prediction count (30k files × 2 labels = 60k).

**Verification:**

1. Check library file count: `SELECT COUNT(*) FROM songs;`
2. Compare to calibration sample count: should match file count, not 2× file count

---

### Issue: "Male and female P5/P95 ranges are different"

**Symptom:** `gender:male` has P5=0.05, P95=0.95 but `gender:female` has P5=0.02, P95=0.88

**Explanation:** This is expected and desirable. Different labels have different confidence distributions:

- Male predictions may cluster tightly (high confidence): wide P5-P95 range
- Female predictions may be more uncertain: narrower P5-P95 range
- Independent calibration captures these label-specific patterns

**Action:** No fix needed. This is the intended behavior of per-label calibration.

---

### Issue: "Calibration generation produces fewer than 23 documents"

**Possible Causes:**

1. **No predictions for label:** If no files have predictions for a label (e.g., no `tonal` predictions), no calibration document is created
2. **Generation interrupted:** Check logs for errors during workflow execution
3. **Filter bug:** Verify label extraction query in `get_sparse_histogram`

**Verification:**

```sql
-- Check which labels have predictions
SELECT label, EXISTS(
  SELECT 1 FROM songs
  WHERE song->'predictions'->'effnet_discogs'->>label IS NOT NULL
  LIMIT 1
) AS has_predictions
FROM unnest(ARRAY['male','female','voice','instrumental', /* ... all 23 labels ... */]) AS label;
```

---

## Schema Reference

### Calibration State Document Structure

```typescript
{
  id: string;          // Format: "model:head:label" (e.g., "effnet-20220825:gender:male")
  model: string;       // "effnet-20220825"
  head: string;        // "gender", "danceability", etc.
  label: string;       // "male", "female", "danceability", etc.
  histogram: {
    bins: number[];    // Sparse histogram bins (0-100 range)
    counts: number[];  // Sample counts per bin
    n: number;         // Total samples (should equal file count for binary heads)
    percentiles: {
      p5: number;      // 5th percentile (lower bound for "significant" predictions)
      p95: number;     // 95th percentile (upper bound)
    }
  },
  created_at: string;  // ISO timestamp
  updated_at: string;  // ISO timestamp
}
```

### Query Pattern: Get Calibration for Specific Label

```sql
SELECT * FROM calibration_state
WHERE model = @model
  AND head = @head
  AND label = @label;  -- Single label filter (not array aggregation)
```

---

## Development Workflow

### Regenerating Calibration After Schema Changes

1. **Delete old documents:**

   ```sql
   DELETE FROM calibration_state;
   ```

2. **Trigger regeneration via API:**

   ```powershell
   # Login
   $login = Invoke-RestMethod -Uri "http://127.0.0.1:8356/api/web/authentication/login" `
     -Method Post -ContentType "application/json" `
     -Body '{"password":"<admin_password>"}'
   $token = $login.session_token
   
   # Generate calibration
   $headers = @{Authorization="Bearer $token"}
   Invoke-RestMethod -Uri "http://127.0.0.1:8356/api/web/calibration/histogram/start" `
     -Method Post -Headers $headers -TimeoutSec 120
   ```

3. **Verify result:**

   ```sql
   SELECT COUNT(*) FROM calibration_state;  -- Should be 23
   ```

### Testing Calibration Changes

Use Docker environment (`.docker/compose.yaml`) to test with realistic data:

1. Start services: `docker compose -f .docker/compose.yaml up -d`
2. Wait for PostgreSQL initialization (~30 seconds)
3. Trigger library scan (first-time setup creates predictions)
4. Generate calibration histograms via API
5. Query calibration_state to verify expectations
6. Test frontend display (Settings → Calibration page)

**Performance note:** Queries against `song_has_tags` (~200k docs) or calibration generation can take 30-120 seconds. Use generous timeouts (120s minimum) when testing.

---

## Related Files

- **Constructor-backed persistence implementation:** [nomarr/components/ml/calibration/ml_calibration_state_comp.py](../../nomarr/components/ml/calibration/ml_calibration_state_comp.py)
- **Workflow orchestration:** [nomarr/workflows/calibration/generate_calibration_wf.py](../../nomarr/workflows/calibration/generate_calibration_wf.py)
- **API endpoints:** [nomarr/interfaces/api/web/calibration_if.py](../../nomarr/interfaces/api/web/calibration_if.py)
- **Frontend display:** [frontend/src/features/calibration/CalibrationPage.tsx](../../frontend/src/features/calibration/CalibrationPage.tsx)
