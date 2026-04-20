# CLI Interface

Command-line interface for Nomarr administration tasks that run outside the server process.

## Responsibilities

- Provide `argparse`-based CLI entry point with subcommand dispatch
- Offer Rich-based UI helpers for spinners, panels, colored output
- Enable standalone database operations without a running server

## Key Modules

 | Module | Purpose |
 | -------- | -------- |
 | `cli_main.py` | `build_parser()` — argparse setup; `main()` — CLI entry point |
 | `cli_ui.py` | `InfoPanel`, `show_spinner`, `print_success/error/warning/info` — Rich UI helpers |

## Subfolder

 | Folder | Purpose |
 | -------- | -------- |
 | `commands/` | Individual CLI command implementations (cleanup, password management) |

## Patterns

- **Standalone bootstrap**: CLI commands use their own lightweight bootstrap (no full Application startup)
- **Service delegation**: Commands obtain service instances and delegate operations — no direct DB access
- **Exit codes**: All commands return `int` exit codes (0 = success)

## Dependencies

- **Calls**: services (`KeyManagementService`, component-level utilities via CLI bootstrap)
- **MUST NOT** import or access persistence directly
- **Imports**: `helpers/dto` for shared types, `Rich` for terminal formatting
