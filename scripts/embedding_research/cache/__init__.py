"""Filesystem caches for raw array data.

DuckDB stores only derived metrics and scalar summaries.
Raw arrays (pooled vectors, head activations, per-bin embeddings) live here.

Cache layout: {OUTPUT_ROOT}/cache/{backbone}/{strategy}/{threshold}/{song_id}
"""
