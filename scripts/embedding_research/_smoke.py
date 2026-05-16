"""Smoke test — run inside devcontainer to verify all imports and DB initialise."""

import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/workspace")

import numpy as np

from scripts.embedding_research.config import BACKBONES, DB_PATH, HEADS, discover_audio
from scripts.embedding_research.db import connect
from scripts.embedding_research.pooling import STRATEGIES
from scripts.embedding_research.similarity import ANNIndex

print("Backbones:", list(BACKBONES))
print("Heads effnet:", list(HEADS.get("effnet", {})))
print("Heads musicnn:", list(HEADS.get("musicnn", {})))
print("Strategies:", list(STRATEGIES))
print("DB path:", DB_PATH)

files = discover_audio()
print("Audio files:", len(files))

with connect() as con:
    tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
    print("DB tables:", [t[0] for t in tables])

v = np.random.randn(10, 8).astype("float32")
idx = ANNIndex(v, metric="cosine")
print("ANNIndex backend:", idx._built_with)
top = idx.query(v[0], k=3)
print("ANN query result:", top)

# Quick nomarr audio load test
from nomarr.components.ml.audio.ml_audio_comp import load_audio_mono

first = files[0]
result = load_audio_mono(str(first), target_sr=16000)
print(
    f"Audio load OK: {first.name} -> {len(result.waveform)} samples @ {result.sample_rate}Hz ({result.duration:.1f}s)"
)

print("\nAll checks passed.")
