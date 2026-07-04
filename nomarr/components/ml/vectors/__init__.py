"""ML vector management — embedding pooling, storage, and retrieval.

Components for vector operations:
- Hot/cold track vector storage and retrieval
- Embedding pooling and dimension extraction
- Vector index maintenance and idle promotion
- Genre backfill for vector documents

These components are used by processing and platform workflows;
they are not re-exported through the parent ``ml`` package.
"""
