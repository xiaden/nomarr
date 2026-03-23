# Infrastructure

Health monitoring and path resolution for filesystem–database coordination.

## Responsibilities

- Query worker health status from the database
- Build and validate `LibraryPath` objects from user input or stored database paths
- Resolve library root paths for filesystem operations

## Key Modules

| Module | Purpose |
|--------|----------|
| `health_comp` | `HealthComp` class — reads worker health records from DB, supports per-component lookup and listing all workers |
| `path_comp` | LibraryPath construction from user input (`build_library_path_from_input`) or DB-stored paths (`build_library_path_from_db`), validates against current library config, detects config drift |

## Patterns

- **Two path entry points:** `build_library_path_from_input` handles API/CLI input (validates against library roots). `build_library_path_from_db` re-validates stored paths against current config, catching library root moves.
- **Status-based validation:** LibraryPath carries a status (`valid`, `invalid_config`, `not_found`) so callers branch on the result rather than catching exceptions.
- **Class vs. functions:** `health_comp` uses a class with injected DB handle; `path_comp` uses stateless functions that accept DB as a parameter.

## Dependencies

- **Upstream:** Called by services and workflows for path validation and health checks
- **Downstream:** Calls persistence directly (ArangoDB queries for health records and library config)
- **External:** Standard library `pathlib`
