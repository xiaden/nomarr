# CLI Commands

Standalone CLI command implementations for database maintenance and admin tasks.

## Responsibilities

- Provide offline database cleanup (orphaned entity removal)
- Manage admin password (show hash, verify, reset)

## Key Modules

| Module | Purpose |
|--------|--------|
| `cleanup_cli.py` | `cmd_cleanup` — remove orphaned entities (artists, albums, genres, labels, years) with no songs |
| `manage_password_cli.py` | `cmd_manage_password` — show/verify/reset admin password hash via `KeyManagementService` |

## Patterns

- **Standalone execution**: Commands run in a separate process from the server, using CLI-specific bootstrap to obtain service instances
- **No direct DB access**: Both commands delegate to services (`KeyManagementService` for passwords, component-level cleanup for entities)
- **Subcommand dispatch**: `manage_password` uses argparse subcommands (`show`, `verify`, `reset`)

## Dependencies

- **Calls**: `KeyManagementService` (password management), metadata cleanup via service/component layer
- **MUST NOT** import or access persistence directly
- **Imports**: `cli_ui` for Rich-based output formatting
