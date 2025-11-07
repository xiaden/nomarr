# Model Wiring Validation Report

**Date:** October 26, 2025  
**Status:** ✅ ALL CHECKS PASSED

## Summary

Validated all 19 head models against `modelsinfo.md` documentation. All models are correctly wired with proper:
- Backbone detection (folder-based)
- Embedding predictor selection
- Output node names
- Head predictor configuration

## Test Results

### Discovered Models
- **Backbones:** effnet, vggish, yamnet
- **Head Types:** identity, multiclass, softmax
- **Total Heads:** 19

### Validation Checks

✅ **Embedding Output Nodes** - All correct per documentation:
- `yamnet`: `embeddings`
- `vggish`: `model/vggish/embeddings`  
- `effnet`: `PartitionedCall:1`

✅ **Head Output Nodes** - All correct:
- `softmax` heads: `model/Softmax`
- `identity` heads: `model/Identity`
- `multiclass` heads: Schema-specified (e.g., `PartitionedCall` for moods_mirex)

✅ **No Orphan Embeddings** - All backbones with embeddings have at least one head model

## Key Findings

### YAMNet Special Case
YAMNet uses `TensorflowPredictVGGish` with **special parameters**:
```python
TensorflowPredictVGGish(
    graphFilename="audioset-yamnet-1.pb",
    input="melspectrogram",  # ← Required for YAMNet
    output="embeddings"
)
```

This is correctly implemented in `processor.py`.

### Schema Priority
The code correctly prioritizes schema-specified output nodes over type-based defaults. Example:
- `moods_mirex` (multiclass) uses `PartitionedCall` (from schema) instead of the typical `model/Softmax`

### Two-Stage Pipeline
All heads correctly use:
1. **Embedding Extractor** (backbone-specific predictor)
   - YAMNet → `TensorflowPredictVGGish(input="melspectrogram")`
   - VGGish → `TensorflowPredictVGGish()`
   - Effnet → `TensorflowPredictEffnetDiscogs()`
   
2. **Head Predictor** (always `TensorflowPredict2D`)
   - Uses output node from schema or inferred from head_type

## Processing Behavior

✅ **Correct:** Only processes heads (classification/regression models)  
✅ **Correct:** Does NOT process standalone embeddings  
✅ **Correct:** Embeddings are intermediate outputs, not written as tags

## Files Validated

- ✅ `essentia_autotag/discovery.py` - Folder-based discovery logic
- ✅ `essentia_autotag/processor.py` - Two-stage predictor instantiation
- ✅ `essentia_autotag/heads.py` - Decision logic (inference-agnostic)

## Test Execution

Run validation test:
```bash
python test_model_wiring.py
```

Expected output: All 19 heads discovered and validated against documentation patterns.

## Next Steps

Ready for container testing:
```bash
docker compose exec autotag python3 cli.py process /music/TestTrack.mp3
```

Expected logs should show:
```
[processor] Built predictor for <head>: <backbone> (<emb_output>) -> <head_type> (<head_output>)
```

No TensorFlow node name errors should occur.
