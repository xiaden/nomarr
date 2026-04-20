# python-arango API Reference

Last updated: 2026-04-01  
Based on: python-arango ≥8.0.0 (Nomarr's pinned minimum)  
Source: <https://github.com/arangodb/python-arango>

---

## Purpose

This document is an agent-consumable reference for the python-arango driver API surface.
It exists to support Nomarr's AQL layer rewrite — favoring python-arango API calls over
raw AQL wherever the driver provides equivalent functionality.

**Decision rule:** If the driver has a method that does what your AQL query does, use the
method. Reserve raw AQL for queries that require joins, graph traversals, computed
projections, or multi-collection logic that the API cannot express.

---

## Table of Contents

1. [Client & Connection](#client--connection)
2. [Database Management](#database-management)
3. [Collection Management](#collection-management)
4. [Document CRUD (Single)](#document-crud-single)
5. [Document CRUD (Bulk)](#document-crud-bulk)
6. [Simple Queries (No AQL)](#simple-queries-no-aql)
7. [AQL Execution](#aql-execution)
8. [AQL Query Cache](#aql-query-cache)
9. [Cursors](#cursors)
10. [Indexes](#indexes)
11. [Transactions](#transactions)
12. [Graph Management](#graph-management)
13. [Vertex Collections](#vertex-collections)
14. [Edge Collections](#edge-collections)
15. [Views & Analyzers](#views--analyzers)
16. [Users & Permissions](#users--permissions)
17. [Error Handling](#error-handling)
18. [Batch API (Deprecated)](#batch-api-deprecated)
19. [Backup](#backup)
20. [Serialization](#serialization)
21. [HTTP Client Customization](#http-client-customization)
22. [AQL-vs-API Decision Matrix](#aql-vs-api-decision-matrix)

---

## Client & Connection

### Initialization

```python
from arango import ArangoClient

# Single host
client = ArangoClient(hosts='http://localhost:8529')

# Multiple coordinators (cluster)
client = ArangoClient(hosts=['http://host1:8529', 'http://host2:8529'])
# or comma-separated
client = ArangoClient(hosts='http://host1:8529,http://host2:8529')

# Custom serialization
import json
client = ArangoClient(
    hosts='http://localhost:8529',
    serializer=json.dumps,
    deserializer=json.loads
)

# TLS with verification disabled (self-signed certs)
client = ArangoClient(hosts='https://localhost:8529', verify_override=False)
```

### ArangoClient API

```
ArangoClient(hosts, serializer=None, deserializer=None, ...)
  .db(name, username, password, ...) -> StandardDatabase
```

### Authentication

```python
# Username/password
db = client.db('test', username='root', password='passwd')

# JWT token (user-level)
db = client.db('test', user_token='token')

# JWT token (superuser)
db = client.db('test', superuser_token='superuser_token')

# Update token dynamically
db.conn.set_token('new_token')
```

---

## Database Management

Requires connection to `_system` database.

```python
sys_db = client.db('_system', username='root', password='passwd')

sys_db.databases()                    # -> list[str]
sys_db.has_database('test')           # -> bool
sys_db.create_database('test')        # -> bool
sys_db.create_database(              
    name='test',
    users=[
        {'username': 'jane', 'password': 'foo', 'active': True},
    ]
)
sys_db.delete_database('test')        # -> bool
```

### Database Info

```python
db = client.db('test', username='root', password='passwd')

db.name                               # str
db.username                           # str
db.version()                          # -> dict
db.status()                           # -> dict
db.details()                          # -> dict
db.engine()                           # -> dict
db.collections()                      # -> list[dict]
db.graphs()                           # -> list[dict]
```

---

## Collection Management

### StandardDatabase Methods

 | Method | Returns | Description |
 | -------- | --------- | ------------- |
 | `db.collections()` | `list[dict]` | List all collections |
 | `db.has_collection(name)` | `bool` | Check existence |
 | `db.collection(name)` | `StandardCollection` | Get API wrapper (no creation) |
 | `db.create_collection(name, **kwargs)` | `StandardCollection` | Create collection |
 | `db.delete_collection(name)` | `bool` | Delete collection |

### Create with Options

```python
# Standard collection
students = db.create_collection('students')

# With JSON schema validation
schema = {
    'rule': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string'},
            'email': {'type': 'string'}
        },
        'required': ['name', 'email']
    },
    'level': 'moderate',
    'message': 'Schema Validation Failed.'
}
employees = db.create_collection(name='employees', schema=schema)

# Edge collection
edges = db.create_collection('edges', edge=True)
```

### StandardCollection Properties

 | Method / Property | Returns | Description |
 | ------------------- | --------- | ------------- |
 | `.name` | `str` | Collection name |
 | `.db_name` | `str` | Database name |
 | `.properties()` | `dict` | Full collection properties |
 | `.revision()` | `str` | Collection revision |
 | `.statistics()` | `dict` | Collection statistics |
 | `.checksum()` | `dict` | Collection checksum |
 | `.count()` | `int` | Document count |
 | `len(collection)` | `int` | Same as `.count()` |

### Collection Operations

```python
students.load()                       # Load into memory
students.unload()                     # Unload from memory
students.truncate()                   # Remove all documents
students.configure(schema={})         # Reconfigure (e.g. remove schema)
```

---

## Document CRUD (Single)

### Via Collection Wrapper (preferred)

```python
students = db.collection('students')

# INSERT
metadata = students.insert({'_key': 'lola', 'GPA': 3.5, 'first': 'Lola'})
# Returns: {'_id': 'students/lola', '_key': 'lola', '_rev': '...'}

# EXISTS
students.has('lola')                  # -> bool
'lola' in students                    # -> bool (same)

# GET (by key, by ID, by body)
students.get('lola')                  # by key
students.get('students/lola')         # by ID
students.get({'_id': 'students/lola'})  # by body with _id
students.get({'_key': 'lola'})        # by body with _key

# GET MANY
students.get_many(['abby', 'students/lola', {'_key': 'john'}])

# UPDATE (merge-patch — keeps unspecified fields)
students.update({'_key': 'lola', 'GPA': 3.8})

# REPLACE (full replacement — removes unspecified fields)
students.replace({'_key': 'lola', 'GPA': 3.8, 'first': 'Lola'})

# DELETE (by key, ID, or body)
students.delete('lola')
students.delete('students/lola')
students.delete({'_key': 'lola'})
```

### Via Database API (requires `_id`)

```python
db.insert_document('students', {'_id': 'students/lola', 'GPA': 3.5})
db.has_document({'_id': 'students/lola'})    # -> bool
db.document('students/lola')                  # -> dict
db.update_document({'_id': 'students/lola', 'GPA': 3.8})
db.replace_document({'_id': 'students/lola', 'GPA': 3.4})
db.delete_document('students/lola')
```

---

## Document CRUD (Bulk)

**These are the preferred methods for multi-document operations** (not the deprecated Batch API).

```python
# Bulk insert
students.import_bulk([doc1, doc2, doc3])
students.insert_many([doc1, doc2, doc3])

# Bulk update
students.update_many([
    {'_key': 'lola', 'GPA': 4.0},
    {'_key': 'john', 'GPA': 3.9}
])

# Bulk replace
students.replace_many([full_doc1, full_doc2])

# Bulk delete (by key, ID, or body)
students.delete_many(['lola', 'john', 'students/emma'])
```

### Match-Based Bulk Operations

```python
# Update all matching documents
students.update_match({'last': 'Park'}, {'GPA': 3.0})

# Replace all matching documents
students.replace_match({'first': 'Emma'}, {'first': 'Becky', 'last': 'Solis'})

# Delete all matching documents
students.delete_match({'name': 'John'})
```

### Iteration

```python
# Iterate all documents (automatic batching under the hood)
for student in students:
    student['GPA'] = 4.0
    students.update(student)
```

---

## Simple Queries (No AQL)

**These replace common single-collection AQL patterns without writing any AQL.**

 | Method | Replaces AQL Pattern | Description |
 | -------- | --------------------- | ------------- |
 | `collection.ids()` | `FOR d IN c RETURN d._id` | All document IDs |
 | `collection.keys()` | `FOR d IN c RETURN d._key` | All document keys |
 | `collection.all(skip, limit)` | `FOR d IN c LIMIT skip,limit RETURN d` | All docs with pagination |
 | `collection.find(filters, skip, limit)` | `FOR d IN c FILTER d.x==v RETURN d` | Filter by equality |
 | `collection.find(filters, sort=[...])` | `FOR d IN c FILTER ... SORT ... RETURN d` | Find with sort |
 | `collection.get_many(ids_or_keys)` | `FOR d IN c FILTER d._key IN [...] RETURN d` | Batch get by IDs/keys |
 | `collection.random()` | N/A | Random document |
 | `collection.update_match(filters, body)` | `FOR d IN c FILTER ... UPDATE d WITH {...} IN c` | Conditional update |
 | `collection.replace_match(filters, body)` | `FOR d IN c FILTER ... REPLACE d WITH {...} IN c` | Conditional replace |
 | `collection.delete_match(filters)` | `FOR d IN c FILTER ... REMOVE d IN c` | Conditional delete |
 | `collection.count()` | `RETURN LENGTH(c)` | Document count |
 | `collection.has(key)` | `RETURN DOCUMENT(c, key) != null` | Existence check |

### find() Details

```python
# Simple filter
for doc in students.find({'first': 'John'}):
    print(doc)

# Filter with sort
for doc in students.find(
    {'first': 'John'},
    sort=[{'sort_by': 'GPA', 'sort_order': 'DESC'}]
):
    print(doc)

# With pagination
for doc in students.find({'status': 'active'}, skip=0, limit=100):
    print(doc)
```

---

## AQL Execution

### Execute Queries

```python
aql = db.aql

# Simple query → Cursor
cursor = aql.execute('FOR doc IN students RETURN doc')
results = [doc for doc in cursor]

# Parameterized query (ALWAYS use bind_vars, never string interpolation)
cursor = aql.execute(
    'FOR doc IN students FILTER doc.age < @value RETURN doc',
    bind_vars={'value': 19}
)

# With options
cursor = aql.execute(
    'FOR doc IN students RETURN doc',
    batch_size=100,
    count=True,
    allow_retry=True
)
```

### Query Management

```python
aql.explain(query)                    # Execution plan without running
aql.validate(query)                   # Syntax validation without running
aql.queries()                         # List running queries
aql.slow_queries()                    # List slow queries
aql.clear_slow_queries()              # Clear slow query log
aql.kill(query_id)                    # Kill a running query
```

### Query Tracking

```python
aql.tracking()                        # Get tracking properties
aql.set_tracking(
    max_slow_queries=10,
    track_bind_vars=True,
    track_slow_queries=True
)
```

### AQL User Functions

```python
aql.create_function(
    name='functions::temperature::converter',
    code='function (celsius) { return celsius * 1.8 + 32; }'
)
aql.functions()                       # List all user functions
aql.delete_function('functions::temperature::converter')
```

---

## AQL Query Cache

```python
aql.cache.properties()                # Get cache settings
aql.cache.configure(mode='demand', max_results=10000)
aql.cache.clear()                     # Clear cached results
```

---

## Cursors

### Automatic Iteration (preferred)

```python
cursor = db.aql.execute('FOR doc IN students RETURN doc', batch_size=100)
results = [doc for doc in cursor]
```

### Manual Fetch/Pop

```python
cursor = db.aql.execute('FOR doc IN students RETURN doc', batch_size=1)

# Fetch all server-side batches
while cursor.has_more():
    cursor.fetch()

# Pop all client-side items
while not cursor.empty():
    cursor.pop()
```

### Allow Retry (for unreliable connections)

```python
cursor = db.aql.execute(
    'FOR doc IN students FILTER doc.age > @val RETURN doc',
    bind_vars={'val': 17},
    batch_size=2,
    count=True,
    allow_retry=True
)
while cursor.has_more():
    cursor.fetch()
# IMPORTANT: manually close when allow_retry is enabled
cursor.close()
```

### Cursor Properties

```
cursor.id              # Server-side cursor ID
cursor.has_more()      # More batches on server?
cursor.empty()         # Client buffer empty?
cursor.count()         # Total result count (if count=True in execute)
cursor.statistics()    # Query execution statistics
cursor.batch()         # Current batch data
cursor.close()         # Explicitly close server-side cursor
```

---

## Indexes

### Add Index

```python
cities = db.collection('cities')

# Persistent (replaces hash/skiplist in modern ArangoDB)
cities.add_index({'type': 'persistent', 'fields': ['name'], 'unique': True})
cities.add_index({'type': 'persistent', 'fields': ['continent', 'country'], 'unique': True})
cities.add_index({'type': 'persistent', 'fields': ['population'], 'sparse': False})

# Fulltext
cities.add_index({'type': 'fulltext', 'fields': ['description']})

# Geo-spatial
cities.add_index({'type': 'geo', 'fields': ['coordinates']})

# TTL (time-to-live)
cities.add_index({'type': 'ttl', 'fields': ['expires_at'], 'expireAfter': 3600})

# MDI (multi-dimensional)
cities.add_index({'type': 'mdi', 'fields': ['x', 'y'], 'fieldValueTypes': 'double'})

# Named index (can be referenced in AQL hints)
cities.add_index({
    'type': 'persistent',
    'fields': ['country'],
    'unique': True,
    'name': 'idx_country'
})
```

### List & Delete

```python
cities.indexes()                      # -> list[dict]
cities.delete_index(index_id)         # -> bool
```

### Index Types Summary

 | Type | Use Case | Key Options |
 | ------ | ---------- | ------------- |
 | `persistent` | Equality/range lookups, sorting | `unique`, `sparse`, `name`, `deduplicate` |
 | `fulltext` | Text search (legacy — prefer ArangoSearch) | `fields` (single field) |
 | `geo` | Geospatial queries | `geoJson` |
 | `ttl` | Auto-expiring documents | `expireAfter` (seconds) |
 | `mdi` | Multi-dimensional range queries | `fieldValueTypes` |

---

## Transactions

### Stream Transactions (preferred)

```python
col = db.collection('students')

# Begin — must declare read/write collections upfront
txn_db = db.begin_transaction(read=col.name, write=col.name)

# Transaction-scoped wrappers
txn_col = txn_db.collection('students')
txn_aql = txn_db.aql

# Operations return results immediately (not jobs)
txn_col.insert({'_key': 'Abby'})
txn_col.insert({'_key': 'John'})

# Check status
txn_db.transaction_status()

# Commit
txn_db.commit_transaction()

# --- Or abort ---
txn_db.abort_transaction()
```

### Fetch Existing Transaction

```python
# Useful when transaction ID comes from another system
original_txn = db.begin_transaction(write='students')
txn_db = db.fetch_transaction(original_txn.transaction_id)
```

### Transaction Rules

- Wrappers are **single-use** — create new ones for each transaction
- `txn_db.context == 'transaction'` always
- Read/write collections must be declared at `begin_transaction()`
- After commit/abort, the `txn_db` cannot be reused

---

## Graph Management

### Database-Level Graph API

```python
db.graphs()                           # List all graphs
db.has_graph('school')                # -> bool
db.create_graph('school')             # -> Graph
db.graph('school')                    # -> Graph (existing)
db.delete_graph('school')             # -> bool
```

### Graph Properties

```python
school = db.graph('school')
school.name                           # str
school.db_name                        # str
school.vertex_collections()           # -> list[str]
school.edge_definitions()             # -> list[dict]
```

### Edge Definitions

```python
# Create
school.create_edge_definition(
    edge_collection='teach',
    from_vertex_collections=['teachers'],
    to_vertex_collections=['lectures']
)

# List
school.edge_definitions()

# Replace
school.replace_edge_definition(
    edge_collection='teach',
    from_vertex_collections=['teachers'],
    to_vertex_collections=['lectures']
)

# Delete (purge=True removes the collection too)
school.delete_edge_definition('teach', purge=True)
```

### Edge Definition Structure

```python
{
    'edge_collection': str,
    'from_vertex_collections': list[str],
    'to_vertex_collections': list[str]
}
```

---

## Vertex Collections

### Via Graph Wrapper (preferred for graph-managed data)

```python
school = db.graph('school')

school.has_vertex_collection('teachers')  # -> bool
school.vertex_collections()               # -> list[str]
teachers = school.create_vertex_collection('teachers')  # -> VertexCollection
teachers = school.vertex_collection('teachers')         # get existing

# VertexCollection has the same interface as StandardCollection
teachers.insert({'_key': 'jon', 'name': 'Jon'})
teachers.update({'_key': 'jon', 'age': 35})
teachers.replace({'_key': 'jon', 'name': 'Jon', 'age': 36})
teachers.get('jon')
teachers.has('jon')
teachers.delete('jon')
teachers.properties()
```

### Via Graph API (uses `_id` instead of `_key`)

```python
school.insert_vertex('lectures', {'_key': 'CSC101'})
school.update_vertex({'_id': 'lectures/CSC101', 'difficulty': 'easy'})
school.replace_vertex({'_id': 'lectures/CSC101', 'difficulty': 'hard'})
school.has_vertex('lectures/CSC101')
school.vertex('lectures/CSC101')
school.delete_vertex('lectures/CSC101')
```

---

## Edge Collections

### Via Edge Collection Wrapper

```python
teach = school.edge_collection('teach')

# CRUD — same as standard collection but edges require _from/_to
teach.insert({
    '_key': 'jon-CSC101',
    '_from': 'teachers/jon',
    '_to': 'lectures/CSC101'
})
teach.update({'_key': 'jon-CSC101', 'online': True})
teach.replace({
    '_key': 'jon-CSC101',
    '_from': 'teachers/jon',
    '_to': 'lectures/CSC101',
    'online': False
})
teach.has('jon-CSC101')
teach.get('jon-CSC101')
teach.delete('jon-CSC101')

# Convenience: link two vertices
teach.link('teachers/jon', 'lectures/CSC101', data={'online': False})

# Get edges in/out of a vertex
teach.edges('teachers/jon', direction='in')   # -> list[dict]
teach.edges('teachers/jon', direction='out')  # -> list[dict]
```

### Via Graph API (uses `_id`)

```python
school.insert_edge(collection='teach', edge={
    '_id': 'teach/jon-CSC101',
    '_from': 'teachers/jon',
    '_to': 'lectures/CSC101'
})
school.update_edge({'_id': 'teach/jon-CSC101', 'online': True})
school.replace_edge({'_id': 'teach/jon-CSC101', '_from': '...', '_to': '...', 'online': False})
school.has_edge('teach/jon-CSC101')
school.edge('teach/jon-CSC101')
school.delete_edge('teach/jon-CSC101')
school.link('teach', 'teachers/jon', 'lectures/CSC101')
school.edges('teach', 'teachers/jon', direction='in')
```

### Edge Document Structure

```python
{
    '_id': 'friends/001',
    '_key': '001',
    '_rev': '_Wm3d4le--_',
    '_from': 'students/john',    # Required: source vertex ID
    '_to': 'students/jane',      # Required: target vertex ID
    'closeness': 9.5             # Custom fields
}
```

---

## Views & Analyzers

### ArangoSearch Views

```python
# Create
db.create_arangosearch_view(
    name='my_view',
    properties={'cleanupIntervalStep': 0}
)

# Update (partial)
db.update_arangosearch_view(
    name='my_view',
    properties={'cleanupIntervalStep': 1000}
)

# Replace (full — unspecified props reset to defaults)
db.replace_arangosearch_view(
    name='my_view',
    properties={'cleanupIntervalStep': 2000}
)
```

### Generic Views

```python
db.views()                            # List all views
db.create_view(name='foo', view_type='arangosearch', properties={...})
db.rename_view('foo', 'bar')
db.view('bar')                        # Get properties
db.update_view(name='bar', properties={...})
db.replace_view(name='bar', properties={...})
db.delete_view('bar')
```

### Analyzers

```python
db.analyzers()                        # List all analyzers
db.create_analyzer(
    name='my_analyzer',
    analyzer_type='identity',         # or 'ngram', 'text', etc.
    properties={},
    features=[]
)
db.delete_analyzer('my_analyzer', ignore_missing=True)
```

---

## Users & Permissions

Requires `_system` database connection.

```python
sys_db = client.db('_system', username='root', password='passwd')

# User CRUD
sys_db.users()
sys_db.has_user('johndoe@gmail.com')
sys_db.user('johndoe@gmail.com')
sys_db.create_user(username='johndoe@gmail.com', password='pass', active=True, extra={...})
sys_db.update_user(username='johndoe@gmail.com', password='new_pass', extra={...})
sys_db.replace_user(username='johndoe@gmail.com', password='pass', active=True, extra={...})

# Permissions
sys_db.permissions('johndoe@gmail.com')                                    # All
sys_db.permission(username='johndoe@gmail.com', database='test')           # DB-level
sys_db.permission(username='johndoe@gmail.com', database='test', collection='students')  # Collection-level

# Grant/update
sys_db.update_permission(username='johndoe@gmail.com', permission='rw', database='test')
sys_db.update_permission(username='johndoe@gmail.com', permission='ro', database='test', collection='students')

# Reset
sys_db.reset_permission(username='johndoe@gmail.com', database='test')
sys_db.reset_permission(username='johndoe@gmail.com', database='test', collection='students')
```

---

## Error Handling

### Exception Hierarchy

```
ArangoError
├── ArangoClientError          # Client-side errors (bad input, parse failures)
│   └── DocumentParseError
│   └── ...
└── ArangoServerError          # Server-side errors (HTTP non-2xx)
    └── DocumentInsertError
    └── AQLQueryExecuteError
    └── AQLQueryKillError
    └── OverloadControlExecutorError
    └── ...
```

### Server Error Properties

```python
from arango import ArangoServerError, DocumentInsertError

try:
    students.insert({'_key': 'John'})
    students.insert({'_key': 'John'})     # duplicate key
except DocumentInsertError as exc:
    exc.source          # 'server'
    exc.message         # Human-readable message
    exc.error_message   # Raw ArangoDB error message
    exc.error_code      # ArangoDB error code (int)
    exc.url             # API endpoint URL
    exc.http_method     # e.g. 'POST'
    exc.http_code       # e.g. 409
    exc.http_headers    # Response headers

    exc.response        # Full Response object
    exc.request         # Full Request object
```

### Client Error Properties

```python
from arango import ArangoClientError, DocumentParseError

try:
    students.get({'_id': 'invalid_id'})
except DocumentParseError as exc:
    exc.source          # 'client'
    exc.message         # Error description
    # All HTTP/server fields are None
```

### Error Code Constants

```python
from arango import errno

errno.DOCUMENT_NOT_FOUND    # 1202
errno.DOCUMENT_REV_BAD      # 1239
errno.NOT_IMPLEMENTED        # 9
# ... many more
```

---

## Batch API (Deprecated)

> **⚠️ Deprecated since ArangoDB 3.8.0.** Use `insert_many`, `update_many`,
> `replace_many`, `delete_many` instead.

The batch API now uses `ThreadPoolExecutor` internally (default `max_workers=1`).
It sends parallel HTTP requests, NOT a single batched HTTP call.

```python
# Context manager (auto-commit)
with db.begin_batch_execution(return_result=True) as batch_db:
    batch_col = batch_db.collection('students')
    job1 = batch_col.insert({'_key': 'Kris'})
    job2 = batch_col.insert({'_key': 'Rita'})
# Results available after context exit
metadata = job1.result()

# Explicit commit
batch_db = db.begin_batch_execution(return_result=False)
batch_db.collection('students').insert({'_key': 'Jake'})
batch_db.commit()
```

### Rules

- `BatchDatabase` and `BatchJob` are **stateful** — not thread-safe
- `BatchDatabase` cannot be reused after commit
- Prefer `collection.*_many()` methods for all new code

---

## Backup

Requires `_system` database with JWT auth.

```python
sys_db = client.db('_system', username='root', password='passwd', auth_method='jwt')
backup = sys_db.backup

backup.create(label='daily', allow_inconsistent=True, timeout=30000)
backup.get()                          # All backups
backup.get(backup_id='...')           # Specific backup
backup.restore(backup_id)
backup.delete(backup_id)

# Remote upload/download
result = backup.upload(backup_id=bid, repository='local://tmp/backups', config={...})
backup.upload(upload_id=result['upload_id'])           # Check status
backup.upload(upload_id=result['upload_id'], abort=True)  # Abort

result = backup.download(backup_id=bid, repository='local://tmp/backups', config={...})
backup.download(download_id=result['download_id'])     # Check status
```

---

## Serialization

Override JSON serialization globally at client init:

```python
import json
client = ArangoClient(
    hosts='http://localhost:8529',
    serializer=json.dumps,
    deserializer=json.loads
)
```

---

## HTTP Client Customization

```python
from arango.http import HTTPClient
from arango.response import Response

class CustomHTTPClient(HTTPClient):
    def create_session(self, host):
        session = Session()
        session.headers.update({'x-custom': 'true'})
        # Add retry strategy, custom timeouts, etc.
        return session

    def send_request(self, session, method, url, params=None, data=None, headers=None, auth=None):
        response = session.request(method=method, url=url, params=params, data=data,
                                    headers=headers, auth=auth, verify=False, timeout=5)
        return Response(
            method=response.request.method,
            url=response.url,
            headers=response.headers,
            status_code=response.status_code,
            status_text=response.reason,
            raw_body=response.text,
        )

client = ArangoClient(hosts='http://localhost:8529', http_client=CustomHTTPClient())
```

---

## Overload Control

```python
controlled_db = db.begin_controlled_execution(max_queue_time_seconds=7.5)
controlled_col = controlled_db.collection('students')
controlled_col.insert({'_key': 'Neal'})

controlled_db.last_queue_time         # Last recorded queue time
controlled_db.max_queue_time          # Current max setting
controlled_db.adjust_max_queue_time(0.5)   # Change limit
controlled_db.adjust_max_queue_time(None)  # Disable limit
```

---

## AQL-vs-API Decision Matrix

Use this to decide when to use the python-arango API vs raw AQL during the rewrite.

### ✅ Use API (no AQL needed)

 | Operation | API Method |
 | ----------- | ----------- |
 | Get document by key | `collection.get(key)` |
 | Check document exists | `collection.has(key)` |
 | Insert single document | `collection.insert(doc)` |
 | Update single document | `collection.update(doc)` |
 | Replace single document | `collection.replace(doc)` |
 | Delete single document | `collection.delete(key)` |
 | Bulk insert | `collection.insert_many(docs)` |
 | Bulk update | `collection.update_many(docs)` |
 | Bulk replace | `collection.replace_many(docs)` |
 | Bulk delete | `collection.delete_many(keys)` |
 | Find by equality filter | `collection.find(filters)` |
 | Update matching docs | `collection.update_match(filters, body)` |
 | Delete matching docs | `collection.delete_match(filters)` |
 | Get all document keys | `collection.keys()` |
 | Get all document IDs | `collection.ids()` |
 | Paginate all docs | `collection.all(skip, limit)` |
 | Get random document | `collection.random()` |
 | Count documents | `collection.count()` |
 | Get many by keys | `collection.get_many(keys)` |
 | Edge CRUD | `edge_collection.insert/update/delete/get` |
 | Link vertices | `edge_collection.link(from, to)` |
 | Edges of vertex | `edge_collection.edges(vertex, direction)` |
 | Transaction wrapping | `db.begin_transaction(...)` |

### ⚠️ Use AQL (API insufficient)

 | Operation | Why AQL? |
 | ----------- | ---------- |
 | Multi-collection joins | API operates on single collections |
 | Graph traversals | `FOR v, e, p IN 1..N OUTBOUND ...` |
 | Computed projections | `RETURN {name: d.first, score: d.x * 2}` |
 | Aggregations (GROUP BY) | `COLLECT ... AGGREGATE ...` |
 | Subqueries | Nested `FOR` loops |
 | Conditional logic | `LET x = (cond ? a : b)` |
 | Upsert (insert-or-update) | `UPSERT ... INSERT ... UPDATE ...` |
 | Complex filters | `FILTER d.age > 20 AND d.name LIKE '%son'` |
 | ArangoSearch queries | `FOR d IN view SEARCH ANALYZER(...)` |
 | Full-text search | `FOR d IN FULLTEXT(collection, field, query)` |
 | Geo queries | `FOR d IN collection FILTER GEO_DISTANCE(...)` |
 | Sorted + filtered + limited | When sort/filter/limit interact beyond `find()` |

### 🔄 Gray Area (prefer API, fall back to AQL)

 | Operation | Guidance |
 | ----------- | ---------- |
 | Filter by range (`age > 20`) | Use AQL — `find()` only does equality |
 | Filter by multiple fields | `find({'a': 1, 'b': 2})` works for AND-equality; use AQL for OR / range |
 | Sorted results | `find(filters, sort=[...])` works for simple sorts; AQL for complex |
 | Count with filter | `find()` + `len(list(...))` for small sets; AQL `COLLECT WITH COUNT` for large |

---

## Threading Notes

- `ArangoClient` and `StandardDatabase` are **stateless and thread-safe**
- `BatchDatabase`, `BatchJob`, and `Cursor` are **stateful** — lock or don't share
- `TransactionDatabase` is **stateful** — one transaction per wrapper instance
