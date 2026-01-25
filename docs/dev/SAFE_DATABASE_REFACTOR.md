# SafeDatabase Refactor: Complete JSON Sanitization

**Status:** Draft  
**Created:** 2026-01-25  
**Author:** Copilot + xiaden

---

## Problem Statement

`SafeDatabase` only sanitizes data for `aql.execute()` calls. Collection methods (`.insert()`, `.update()`, `.delete()`) bypass sanitization entirely.

### Current Architecture

```
SafeDatabase
├── .aql (SafeAQL)
│   └── .execute() → _jsonify_for_arango() ✓ SANITIZED
└── .collection(name) → StandardCollection (raw)
    ├── .insert() → NO sanitization ✗
    ├── .update() → NO sanitization ✗
    └── .delete() → NO sanitization ✗
```

### Usage Audit

| Pattern | Count | Sanitized? |
|---------|-------|------------|
| `self.db.aql.execute()` | 20+ | ✓ Yes |
| `self.collection.insert()` | 8 | ✗ No |
| `self.collection.update()` | 1 | ✗ No |
| `self.collection.delete()` | 2 | ✗ No |

### Full StandardCollection Write API (from python-arango docs)

These methods accept user data and should be wrapped:

| Method | Signature | Notes |
|--------|-----------|-------|
| `insert(doc, **kwargs)` | Single document insert | Returns metadata |
| `insert_many(docs, **kwargs)` | Bulk insert | Returns list of metadata |
| `update(doc, **kwargs)` | Single document update | Requires `_key` or `_id` |
| `update_match(filters, body, **kwargs)` | Update matching docs | Filter + update body |
| `update_many(docs, **kwargs)` | Bulk update | List of partial docs |
| `replace(doc, **kwargs)` | Single document replace | Full doc replacement |
| `replace_match(filters, body, **kwargs)` | Replace matching docs | Filter + replacement body |
| `replace_many(docs, **kwargs)` | Bulk replace | List of full docs |
| `delete(doc, **kwargs)` | Single delete | Can be key, id, or doc dict |
| `delete_match(filters, **kwargs)` | Delete matching docs | Filter dict |
| `delete_many(docs, **kwargs)` | Bulk delete | List of keys/ids/docs |
| `import_bulk(docs, **kwargs)` | Bulk import | High-performance bulk load |

Read methods (no sanitization needed, but consider for journaling):

| Method | Notes |
|--------|-------|
| `get(doc)` | Returns document |
| `get_many(docs)` | Returns list of documents |
| `has(doc)` | Returns bool |
| `find(filters)` | Returns cursor |
| `all()` | Returns cursor |

### Why Two Patterns Exist

| Method | Use Case | Pros | Cons |
|--------|----------|------|------|
| `aql.execute()` | Complex queries, UPSERT, bulk ops | Powerful, flexible | Verbose for simple CRUD |
| `collection.*()` | Single-doc CRUD | Simple, readable | No UPSERT, limited filtering |

---

## Decision Required

### Option A: Standardize on AQL Only

Convert all collection methods to AQL equivalents:

```python
# Before
self.collection.insert(doc)

# After
self.db.aql.execute(
    "INSERT @doc INTO @@collection RETURN NEW",
    bind_vars={"doc": doc, "@collection": "collection_name"}
)
```

**Pros:**
- Single code path, single sanitization point
- Consistent patterns across codebase
- Easier to add journaling later (one interception point)

**Cons:**
- More verbose for simple operations
- Breaking change to existing code
- AQL overhead for single-doc ops (minor)

### Option B: Wrap Collection Methods (SafeCollection)

Add `_SafeCollection` wrapper that sanitizes documents:

```python
class _SafeCollection:
    """Wrapper around StandardCollection that sanitizes documents before write operations."""
    
    def __init__(self, collection: StandardCollection) -> None:
        self._collection = collection
    
    # === Write operations (sanitize input) ===
    
    def insert(self, doc: dict[str, Any], **kwargs: Any) -> Any:
        return self._collection.insert(_jsonify_for_arango(doc), **kwargs)
    
    def insert_many(self, docs: list[dict[str, Any]], **kwargs: Any) -> Any:
        return self._collection.insert_many(_jsonify_for_arango(docs), **kwargs)
    
    def update(self, doc: dict[str, Any], **kwargs: Any) -> Any:
        return self._collection.update(_jsonify_for_arango(doc), **kwargs)
    
    def update_match(self, filters: dict[str, Any], body: dict[str, Any], **kwargs: Any) -> Any:
        return self._collection.update_match(
            _jsonify_for_arango(filters), 
            _jsonify_for_arango(body), 
            **kwargs
        )
    
    def update_many(self, docs: list[dict[str, Any]], **kwargs: Any) -> Any:
        return self._collection.update_many(_jsonify_for_arango(docs), **kwargs)
    
    def replace(self, doc: dict[str, Any], **kwargs: Any) -> Any:
        return self._collection.replace(_jsonify_for_arango(doc), **kwargs)
    
    def replace_match(self, filters: dict[str, Any], body: dict[str, Any], **kwargs: Any) -> Any:
        return self._collection.replace_match(
            _jsonify_for_arango(filters),
            _jsonify_for_arango(body),
            **kwargs
        )
    
    def replace_many(self, docs: list[dict[str, Any]], **kwargs: Any) -> Any:
        return self._collection.replace_many(_jsonify_for_arango(docs), **kwargs)
    
    def delete(self, doc: str | dict[str, Any], **kwargs: Any) -> Any:
        # doc can be key string or document dict
        safe_doc = _jsonify_for_arango(doc) if isinstance(doc, dict) else doc
        return self._collection.delete(safe_doc, **kwargs)
    
    def delete_match(self, filters: dict[str, Any], **kwargs: Any) -> Any:
        return self._collection.delete_match(_jsonify_for_arango(filters), **kwargs)
    
    def delete_many(self, docs: list[str | dict[str, Any]], **kwargs: Any) -> Any:
        return self._collection.delete_many(_jsonify_for_arango(docs), **kwargs)
    
    def import_bulk(self, docs: list[dict[str, Any]], **kwargs: Any) -> Any:
        return self._collection.import_bulk(_jsonify_for_arango(docs), **kwargs)
    
    # === Read operations (pass through) ===
    
    def get(self, doc: str | dict[str, Any], **kwargs: Any) -> Any:
        return self._collection.get(doc, **kwargs)
    
    def get_many(self, docs: list[str | dict[str, Any]], **kwargs: Any) -> Any:
        return self._collection.get_many(docs, **kwargs)
    
    def has(self, doc: str | dict[str, Any], **kwargs: Any) -> bool:
        return self._collection.has(doc, **kwargs)
    
    def find(self, filters: dict[str, Any], **kwargs: Any) -> Any:
        return self._collection.find(filters, **kwargs)
    
    def all(self, **kwargs: Any) -> Any:
        return self._collection.all(**kwargs)
    
    # === Proxy everything else ===
    
    def __getattr__(self, name: str) -> Any:
        return getattr(self._collection, name)
```

**Pros:**
- Minimal code changes to call sites
- Covers both entry points
- Drop-in replacement
- Complete coverage of all write methods

**Cons:**
- Two interception points (AQL + Collection)
- Journaling needs to hook both
- More surface area to maintain

### Option C: Hybrid (Recommended)

1. Add `_SafeCollection` wrapper now (immediate fix)
2. Document that new code should prefer AQL for writes
3. Migrate collection methods to AQL over time (optional)

**Rationale:** Fixes the hole immediately without large refactor. Establishes clear direction for future code.

---

## Files Using Collection Methods

| File | Method | Line | Data Types |
|------|--------|------|------------|
| `calibration_history_aql.py` | `.insert()` | 62 | int, str, float |
| `calibration_state_aql.py` | `.insert()` | 160 | int, str, float, dict |
| `calibration_state_aql.py` | `.update()` | 156 | int, str, float, dict |
| `calibration_state_aql.py` | `.delete()` | 202 | str |
| `file_tags_aql.py` | `.insert()` | 54, 89, 94 | str |
| `libraries_aql.py` | `.insert()` | 49 | int, str, None |
| `library_tags_aql.py` | `.insert()` | 66 | str, bool |
| `sessions_aql.py` | `.insert()` | 31 | int, str |
| `worker_claims_aql.py` | `.insert()` | 48 | int, str |
| `worker_claims_aql.py` | `.delete()` | 76 | str |

**Current risk level:** LOW - all current usages pass primitives manually. But fragile - no enforcement.

---

## Implementation Plan

### Phase 1: Add SafeCollection Wrapper

1. Create `_SafeCollection` class in `arango_client.py`
2. Wrap all write methods: `insert`, `insert_many`, `update`, `update_match`, `update_many`, `replace`, `replace_match`, `replace_many`, `delete`, `delete_match`, `delete_many`, `import_bulk`
3. Pass through read methods: `get`, `get_many`, `has`, `find`, `all`
4. Proxy all other attributes via `__getattr__`
5. Update `SafeDatabase.collection()` to return `_SafeCollection`
6. Run existing tests - should pass unchanged

### Phase 2: Verify No Regressions

1. Run full test suite
2. Run layer validation scripts
3. Manual smoke test: create library, scan, verify tags written

### Phase 3: Update Documentation

1. Update `PERSISTENCE.md` or skill to document preferred patterns
2. Add note about sanitization guarantee

---

## Verification Summary

**Claims verified against python-arango v8.x documentation:**

| Claim | Status | Evidence |
|-------|--------|----------|
| `db.collection()` returns raw `StandardCollection` | ✓ Verified | Code line 119-121 |
| Collection methods bypass sanitization | ✓ Verified | `_jsonify_for_arango` only in `_SafeAQL.execute()` |
| AQL execute uses bind_vars | ✓ Verified | python-arango docs |
| `insert/update/delete` take doc dicts | ✓ Verified | python-arango docs |
| Additional bulk methods exist | ✓ Verified | `insert_many`, `update_many`, etc. in docs |

**Risk assessment:** Current code works because call sites manually pass primitives. But there's no enforcement - a future change passing a wrapper type to `.insert()` would fail at ArangoDB, not at our boundary.

---

## Implementation Checklist

- [ ] Read skill: `.github/skills/layer-persistence/SKILL.md`
- [ ] Create `_SafeCollection` class with all write method wrappers
- [ ] Update `SafeDatabase.collection()` to return `_SafeCollection`
- [ ] Run unit tests
- [ ] Run integration tests
- [ ] Run layer validation scripts
- [ ] Update documentation

---

## Relationship to Journaling

This refactor is a **prerequisite** for clean journaling:

- Journaling at SafeDatabase boundary requires intercepting ALL writes
- With Option B/C, we have two interception points (AQL + Collection)
- With Option A, single interception point (AQL only)

If we choose Option C (recommended), journaling will need to hook both `_SafeAQL.execute()` and `_SafeCollection.insert/update/delete()`.

---

*End of plan document.*
