"""ML inference pipeline — backbone embedding, segmentation, head execution.

Components that form the inference pipeline:
- Backbone embedding computation with ONNX models
- Waveform segmentation and score pooling
- Head execution (regression, multiclass, multilabel)
- Output stream persistence and lookup

These components are used directly by processing workflows; they are
not re-exported through the parent ``ml`` package.
"""
