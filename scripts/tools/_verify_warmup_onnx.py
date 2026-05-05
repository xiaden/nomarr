"""Verify tests/fixtures/ml_cuda_warmup.onnx loads correctly with onnxruntime."""

import pathlib

import numpy as np
import onnxruntime as ort

fixture = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ml_cuda_warmup.onnx"
sess = ort.InferenceSession(str(fixture), providers=["CPUExecutionProvider"])
out = sess.run(None, {"X": np.zeros((1, 16000), dtype=np.float32)})
print("OK, output shape:", out[0].shape)
