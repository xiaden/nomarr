# ADR-025: Schema-Driven Persistence Constructor Supersedes Hand-Written AQL Conventions

**Status:** Accepted  
**Date:** 2026-04-11  
**Tags:** persistence, architecture, schema-constructor, aql  
**Source Log:** agent#L11  
**Supersedes:** ADR-024, ADR-010, ADR-014  

## Context

Three existing ADRs govern the hand-written AQL persistence layer that is being replaced by the schema-driven persistence constructor (DD-schema-driven-persistence-constructor):

**ADR-024** (AQL Subpackage Naming Convention and Collection Origination Principle) established rules for organizing hand-written AQL files: collection-prefixed filenames (`library_files_upsert.py`), standard operation categories (`_upsert`, `_delete`, `_get_one`, etc.), and the "Collection Origination Principle" for deciding which AQL module owns a query. The constructor eliminates hand-written AQL files entirely — operations are runtime-constructed from a schema definition. There are no AQL subpackages to name, no operation categories to enforce, and no origination ambiguity because every operation is accessed via `db.collection.verb()`.

**ADR-010** (Bulk Edit Commit Strategy — `set_song_tags_batch`) defined a 3-AQL-round-trip persistence primitive for bulk tag edits. Under the constructor model, multi-step orchestration cannot exist inside a persistence namespace — each persistence call is a single verb. The equivalent operation is a component-layer composition of `db.song_has_tags._from.delete()` + `db.tags.rel.upsert()` + `db.song_has_tags.insert()`.

**ADR-014** (Unified Re-link Persistence Primitive — `relink_tag_edges`) defined a 2-3 round-trip persistence primitive for tag curation (rename, merge, split). Same issue: this is multi-step orchestration that belongs in the component layer, composed from standard constructor verbs (`db.song_has_tags._to.get.many()` + `db.song_has_tags.insert()` + `db.song_has_tags._to.delete()` + `db.tags.cascade()`).

All three ADRs address organizational or API-design problems that the constructor solves structurally. A single supersession ADR is cleaner than three separate ones because the replacement (the constructor) is one unified system.

## Decision

Supersede ADR-024, ADR-010, and ADR-014. The schema-driven persistence constructor replaces all three:

### Replaces ADR-024 (AQL Naming & Origination)

The constructor eliminates the entire category of problems ADR-024 solved:

- **No AQL files to name.** Operations are runtime-constructed from `nomarr/persistence/schema.py`. There are no `library_files_upsert.py` files, no `_crud.py` / `_queries.py` modules, no naming conventions to enforce.
- **No origination ambiguity.** Every verb call is namespaced to its collection: `db.library_files.get(...)`, `db.tags.upsert(...)`. The schema *is* the origination map.
- **No orchestration in persistence.** The constructor's verb set (get, insert, upsert, update, delete, count, collect, aggregate, traversal, transition, cascade, ann_search) enforces single-operation semantics. Multi-step logic cannot be expressed in a namespace — it must live in components or workflows.

### Replaces ADR-010 (set_song_tags_batch)

The 3-step bulk tag edit operation moves to the component layer:

```python
# nomarr/components/tags/tag_write_comp.py
def set_song_tags(db, song_id, rel, values):
    db.song_has_tags._from.delete(song_id)
    db.tags.rel.upsert([{"rel": rel, "value": v} for v in values], match_field="value")
    db.song_has_tags.insert([{"_from": song_id, "_to": tid} for tid in tag_ids])
```

For bulk edits across N songs, the component iterates and applies this pattern per song. Idempotency is preserved (delete-before-insert).

### Replaces ADR-014 (relink_tag_edges)

The 4-step tag re-link operation moves to the component layer:

```python
# nomarr/components/tags/tag_curation_comp.py
def relink_tag_edges(db, source_tag_id, target_tag_id, song_ids=None):
    edges = db.song_has_tags._to.get.many(source_tag_id)
    if song_ids: edges = [e for e in edges if e["_from"] in song_ids]
    db.song_has_tags.insert([{"_from": e["_from"], "_to": target_tag_id} for e in edges])
    db.song_has_tags._to.delete(source_tag_id)
    db.tags.cascade([source_tag_id])
```

All four curation operations (rename, merge, split, single-song edit) continue to use this composition. The calling convention from services is unchanged.

### New Persistence Rules

1. **Single source of truth:** `nomarr/persistence/schema.py` defines all collections, fields, types, edges, cascades, and operators. No other file defines persistence structure.
2. **Verb-only access:** All persistence operations use the 12 standard verbs. No custom AQL methods on namespace objects.
3. **Component-layer compositions:** Any operation requiring multiple persistence calls is a component function, not a persistence method.
4. **No hand-written AQL:** New persistence operations are added by extending the schema and/or verb set, not by writing AQL files.

## Consequences

**Positive:**
- Three ADRs collapsed into one coherent decision — reduces cognitive overhead for contributors
- Eliminates an entire class of organizational debates (naming, origination, module boundaries) by making them structurally impossible
- Component-layer compositions are explicit, testable, and layer-compliant by construction
- Schema-as-source-of-truth enables automated testing (test_schema_output.py validates constructor output against schema)

**Negative:**
- ADR-024's origination principle was a useful mental model — now it's implicit in the schema rather than documented as a rule. Contributors must understand the schema to know "where does this query go?" (answer: it doesn't "go" anywhere, it's constructed)
- Component-layer compositions have slightly different error semantics than the old AQL primitives (each step is a separate DB call rather than a batched AQL query). For alpha with single-user, this is acceptable.

**Migration:**
- Old AQL files remain until Plan E (cleanup phase) deletes them
- Callers of `set_song_tags_batch` and `relink_tag_edges` migrate during Plan C (complex collections)
- ADR-024's naming convention becomes irrelevant as AQL files are deleted

## References

DD-schema-driven-persistence-constructor (governing design), agent#L1-L11 (decision log), ADR-003 (state graph — compatible, not superseded), ADR-004 (graph normalization — compatible, not superseded), ADR-016 (ensure_schema policy — compatible, not superseded)
