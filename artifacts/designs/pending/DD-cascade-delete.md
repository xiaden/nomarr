# Cascade Delete — Design Document

**Status:** Draft  
**Author:** Discussion synthesis  
**Created:** 2026-03-28

**Depends on:** [design-schema-refactor-v1.md](design-schema-refactor-v1.md) (edges must exist before cascades)

---

## Scope

This document covers implementing cascade delete logic using ArangoDB graph traversal, replacing the current pattern of "remembering" FK relationships in code.

**Prerequisites:** Schema refactor v1 must be complete (FK properties converted to edges, named graphs defined).

---

## Problem Statement

Current cascade delete implementation:

```python
# Current: code must "know" about FK relationships
def delete_library(library_id):
    # Must remember: library_files has library_id FK
    db.library_files.delete_by_library_id(library_id)
    # Must remember: library_folders has library_id FK  
    db.library_folders.delete_by_library_id(library_id)
    # Must remember: vectors have file_id FKs
    file_ids = db.library_files.get_file_ids_by_library(library_id)
    db.vectors.delete_by_file_ids(file_ids)
    # ... more manual tracking ...
    db.libraries.delete(library_id)
```

Problems:
1. **Fragile** — Adding new relationships requires updating delete code
2. **Incomplete** — Easy to miss relationships, leaving orphans
3. **Not self-documenting** — Relationships scattered across code
4. **No referential integrity** — ArangoDB doesn't enforce FK constraints

---

## Design Goals

| Goal | Rationale |
|------|----------|
| Graph-based cascades | Traverse edges to find related documents |
| Declarative relationships | Define once in graph, delete logic follows |
| Orphan prevention | Systematic traversal catches all descendants |
| Auditable | Clear delete order, can log what's being removed |

---

## Target Pattern

### Graph Traversal Delete

```python
# Target: traverse graph to find all descendants
def cascade_delete_library(library_id: str) -> CascadeResult:
    """Delete a library and all related documents via graph traversal."""
    
    # Define traversal order (deepest first to avoid dangling edges)
    traversals = [
        # Depth 3: vectors and segment stats (via files)
        ("library_graph", "library_contains_file", "file_graph", "file_has_vectors"),
        ("library_graph", "library_contains_file", "file_graph", "file_has_segment_stats"),
        # Depth 2: file states, tags (via files)
        ("library_graph", "library_contains_file", "file_graph", "file_has_state"),
        ("library_graph", "library_contains_file", "file_graph", "song_has_tags"),
        # Depth 1: files, folders, scans
        ("library_graph", "library_contains_file"),
        ("library_graph", "library_contains_folder"),
        ("library_graph", "library_has_scan"),
        # Depth 0: library itself
        ("libraries",),
    ]
    
    deleted = CascadeResult()
    for traversal in traversals:
        docs = traverse_and_collect(library_id, traversal)
        for doc in docs:
            delete_document(doc)
            deleted.add(doc)
    
    return deleted
```

### AQL Traversal Pattern

```aql
// Collect all documents to delete via multi-hop traversal
LET library = DOCUMENT(@library_id)

// Files in this library
LET files = (
    FOR file IN OUTBOUND library GRAPH 'library_graph'
        OPTIONS {edgeCollections: ['library_contains_file']}
        RETURN file
)

// Vectors for those files  
LET vectors = (
    FOR file IN files
        FOR vector IN OUTBOUND file GRAPH 'file_graph'
            OPTIONS {edgeCollections: ['file_has_vectors']}
            RETURN vector
)

// ... collect more descendants ...

// Delete in reverse dependency order
FOR v IN vectors REMOVE v IN vectors_hot_effnet
FOR f IN files REMOVE f IN library_files
REMOVE library IN libraries
```

---

## Cascade Definitions

### Library Delete Cascade

```
libraries/{id}
├── library_contains_file → library_files/*
│   ├── file_has_state → file_states/* (edges only, not vertices)
│   ├── song_has_tags → tags/* (edges only, orphan tags checked separately)
│   ├── file_has_vectors → vectors_*/*
│   └── file_has_segment_stats → segment_score_stats/*
├── library_contains_folder → library_folders/*
└── library_has_scan → library_scans/*
```

### File Delete Cascade

```
library_files/{id}
├── file_has_state → (edges only)
├── song_has_tags → (edges only)
├── file_has_vectors → vectors_*/*
├── file_has_segment_stats → segment_score_stats/*
└── worker_claims (by file_id property, not edge)
```

### ML Model Delete Cascade

```
ml_models/{id}
└── model_has_output → ml_model_outputs/*
    └── tag_model_output → (edges only, not tag vertices)
```

---

## Edge-Only vs Document Delete

Some cascades delete edges only, not the target documents:

| Edge Collection | Delete Target Document? | Reason |
|-----------------|------------------------|--------|
| `library_contains_file` | Yes | Files belong to one library |
| `library_contains_folder` | Yes | Folders belong to one library |
| `library_has_scan` | Yes | Scans are 1:1 with library |
| `file_has_state` | **No** | States are shared vertices |
| `song_has_tags` | **No** | Tags may be shared across files |
| `file_has_vectors` | Yes | Vectors are per-file |
| `tag_model_output` | **No** | ML outputs may be shared |

### Orphan Cleanup

After cascade, run orphan detection for shared entities:

```aql
// Find tags with no incoming edges
FOR tag IN tags
    LET edges = (FOR e IN song_has_tags FILTER e._to == tag._id LIMIT 1 RETURN 1)
    FILTER LENGTH(edges) == 0
    REMOVE tag IN tags
```

---

## Implementation Approach

### Option A: Decorator Pattern

```python
@cascade_delete(
    graph="library_graph",
    edges=["library_contains_file", "library_contains_folder", "library_has_scan"],
    nested={
        "library_contains_file": cascade_delete_file  # Recursive cascade
    }
)
def delete_library(db: Database, library_id: str) -> None:
    db.delete(library_id)
```

### Option B: Cascade Registry

```python
CASCADE_REGISTRY = {
    "libraries": [
        CascadeEdge("library_contains_file", delete_target=True, nested="library_files"),
        CascadeEdge("library_contains_folder", delete_target=True),
        CascadeEdge("library_has_scan", delete_target=True),
    ],
    "library_files": [
        CascadeEdge("file_has_state", delete_target=False),  # Edge only
        CascadeEdge("song_has_tags", delete_target=False),   # Edge only
        CascadeEdge("file_has_vectors", delete_target=True),
        CascadeEdge("file_has_segment_stats", delete_target=True),
    ],
}

def cascade_delete(db: Database, collection: str, doc_id: str):
    for edge_def in CASCADE_REGISTRY.get(collection, []):
        targets = traverse_edge(db, doc_id, edge_def.edge_collection)
        if edge_def.nested:
            for target in targets:
                cascade_delete(db, edge_def.nested, target._id)
        if edge_def.delete_target:
            for target in targets:
                db.delete(target._id)
        # Always delete the edges
        delete_edges_from(db, doc_id, edge_def.edge_collection)
    db.delete(doc_id)
```

### Option C: Pure AQL Transaction

```python
def delete_library_cascade(db: Database, library_id: str) -> int:
    """Single AQL transaction for atomic cascade delete."""
    return db.aql.execute("""
        LET library = DOCUMENT(@library_id)
        
        // Collect all files
        LET files = (FOR f IN OUTBOUND library library_contains_file RETURN f)
        LET file_ids = files[*]._id
        
        // Collect vectors via files
        LET vectors = (FOR f IN files FOR v IN OUTBOUND f file_has_vectors RETURN v)
        
        // Delete in order: deepest first
        LET d1 = (FOR v IN vectors REMOVE v IN vectors_hot_effnet RETURN 1)
        LET d2 = (FOR e IN file_has_vectors FILTER e._from IN file_ids REMOVE e RETURN 1)
        LET d3 = (FOR e IN song_has_tags FILTER e._from IN file_ids REMOVE e RETURN 1)
        LET d4 = (FOR e IN file_has_state FILTER e._from IN file_ids REMOVE e RETURN 1)
        LET d5 = (FOR f IN files REMOVE f IN library_files RETURN 1)
        LET d6 = (FOR e IN library_contains_file FILTER e._from == @library_id REMOVE e RETURN 1)
        LET d7 = (REMOVE library IN libraries RETURN 1)
        
        RETURN LENGTH(d1) + LENGTH(d2) + LENGTH(d3) + LENGTH(d4) + LENGTH(d5) + LENGTH(d6) + LENGTH(d7)
    """, bind_vars={"library_id": library_id})
```

**Recommended:** Option C (Pure AQL) for atomicity, with Option B registry for documentation.

---

## Migration Strategy

1. **After schema refactor v1 is complete** (edges exist)
2. Add cascade registry definitions
3. Implement AQL cascade functions
4. Replace existing manual cascade code
5. Add orphan cleanup job

---

## Success Criteria

- [ ] All delete operations use graph traversal cascades
- [ ] No manual FK tracking in delete code
- [ ] Atomic transactions for cascade deletes
- [ ] Orphan cleanup for shared entities (tags, states)
- [ ] Delete operations logged for audit
- [ ] Zero orphaned documents after library delete
