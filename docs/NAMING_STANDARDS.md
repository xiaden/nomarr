Nomarr enforces naming rules to ensure predictability, discoverability, and clean architecture.

This document defines **public-facing naming rules** for:
- Services
- Methods
- DTOs
- Modules

---

## 1. Service Names

A service name must be:

```
<Noun>Service
```

Examples:
- `LibraryService`
- `AnalyticsService`
- `QueueService`
- `WorkersCoordinator`

---

## 2. Service Method Names

Service methods follow strict rules.

### 2.1. Format

```
<verb>_<noun>
```

Examples:
- `get_library`
- `list_libraries`
- `scan_library`
- `tag_file`
- `queue_file_for_tagging`
- `enable_workers`

### 2.2. Allowed Verbs

**Read:** get_, list_, exists_, count_, fetch_

**Write:** create_, update_, delete_, set_, rename_

**Domain:** scan_, tag_, recalibrate_, queue_, start_, stop_, sync_, reindex_, import_, export_

**State:** enable_, disable_, activate_, deactivate_

**Complex Commands:** apply_, execute_

Adding new verbs requires justification and documentation.

### 2.3. Disallowed Patterns

- Prefixes: `api_`, `web_`, `cli_`, `sse_`
- Suffixes: `_for_admin`, `_internal`
- Transport semantics
- Error semantics

---

## 3. DTO Naming

DTOs must:

- Use `CamelCase`
- End in `DTO` or a domain-specific suffix (`Result`, `Response`)
- Be placed under `helpers/dto/` when cross-layer

Examples:
- `LibraryDTO`
- `ProcessFileResult`
- `QueueJobDTO`

---

## 4. Module Naming

Follow these rules:

### 4.1. Services
```
<domain>_svc.py
```

### 4.2. Workflows
```
<domain>_wf.py or <domain>_workflow.py
```

### 4.3. Queues/Workers
```
queue_svc.py
worker_pool_svc.py
workers/
```

### 4.4. Helpers
```
<name>_utils.py
<name>_helpers.py
```

---

## 5. File and Class Structure

Services must:
- Contain one main service class
- Put service-local DTOs at top of file
- Avoid splitting the same service across multiple files

---

## 6. Why These Standards Exist

Consistency improves:

- Readability
- Discoverability
- Tooling (Copilot, static analysis)
- Refactor safety
- Clean boundaries between layers

These naming standards apply to **all new code**, and any refactor should move toward compliance.

---

## 7. Quick Reference

```
Services:       <Domain>Service
Methods:        <verb>_<noun>
DTOs:           <Name>DTO or <Name>Result
Workflows:      <name>_workflow
Helpers:        <name>_utils.py
Queues:         <Domain>Queue
Workers:        <Domain>Worker
```

When in doubt: choose clarity, consistency, and predictability.