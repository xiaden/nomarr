# Vector APIs

## POST /api/v1/vectors/search

- **Auth**: Admin or library owner (API key)
- **Body**:
  - `backbone_id: str`
  - `vector: list[float]`
  - `limit: int (1-100)`
  - `min_score: float (>= 0)`
- **Response**: `{ "results": [{ "file_id": str, "score": float, "vector": list[float], ... }] }`
- **Semantics**: Queries **cold collections only**. Returns HTTP 503 if the cold
  collection lacks a vector index.

## GET /api/v1/admin/vectors/stats

- **Auth**: Admin only
- **Response**: `{ "stats": [{ "backbone_id": str, "hot_count": int, "cold_count": int, "index_exists": bool }] }`
- **Semantics**: Aggregates hot/cold counts using
  `VectorMaintenanceService.get_hot_cold_stats()` for every registered backbone.

## POST /api/v1/admin/vectors/promote

- **Auth**: Admin only
- **Body**:
  - `backbone_id: str`
  - `nlists: int | null`
- **Response**: `{ "status": "completed", "nlists": int }`
- **Semantics**: Runs the promote & rebuild workflow synchronously, draining hot
  vectors into cold and rebuilding the ANN index. Blocks the HTTP request until
  completion.
