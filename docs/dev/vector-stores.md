# Vector Stores (Hot/Cold Architecture)

Nomarr uses a two-tier vector storage model for track embeddings:

- **Hot collections** receive fresh writes and fast churn
- **Cold collections** serve long-lived ANN search

The live persistence API is class-based: vector collection templates are declared in `nomarr/persistence/collections.py`, wired by `Builder`, and registered at runtime through `db.register(resolved_name, template_name)`.

---

## Migration Path (m007)

Existing deployments (schema version 6) move to the hot/cold model via
`nomarr/migrations/V007_split_vectors_hot_cold.py`:

1. For each backbone, rename `vectors_track__{backbone}` to
   `vectors_track_cold__{backbone}` so that all existing vectors remain readable
   and keep their ANN index.
2. Create a fresh empty `vectors_track_hot__{backbone}` collection with the
   required `_key` and `file_id` persistent indexes.
3. Recreate persistent indexes on the cold collection (excluding vector indexes)
   to guarantee convergence and cascade-delete performance.
4. Operators must run promote & rebuild after the migration to rebuild the ANN
   index under the new naming scheme.

Schema version increments to 7, and bootstrap now provisions hot collections
only. The migration is idempotent; re-running it skips already-converted
backbones.

---

## Key Components

| Layer | Responsibilities |
| --- | --- |
| Components / Persistence | Class-based vector collection templates plus builder-wired verbs for hot/cold collections |
| Workflows | `promote_and_rebuild_workflow` orchestrates drain, rebuild, and convergence checks |
| Services | `VectorSearchService` (cold-only search + fallback reads), `VectorMaintenanceService` (promote + stats) |
| Interfaces | `/api/web/vector/*` exposes search and maintenance endpoints |

Subsequent sections describe operational guidance, search semantics, and upgrade
paths for existing deployments.

```text
[ ML Workers ] --upsert--> [ vectors_track_hot__* ] --promote & rebuild--> [ vectors_track_cold__* ] --search--> [ API Clients ]
```

---

## Runtime registration

The vector collection classes in `collections.py` are templates, not single physical collections.

At runtime, code resolves a concrete collection name and registers it through:

- `db.register(resolved_name, template_name)`

Examples of template names include `vectors_track_hot` and `vectors_track_cold`, while resolved names include physical collections such as `vectors_track_hot__discogs_effnet__main`.

The returned object is a builder-wired collection instance exposing the normal flat persistence verbs plus vector-specific helpers where applicable.