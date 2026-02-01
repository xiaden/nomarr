# python-mcp-devtools

Model Context Protocol (MCP) tools for Python development - a collection of generic, reusable tools for code analysis and navigation.

## Overview

`python-mcp-devtools` provides MCP tools designed to work with any Python codebase. The tools use static analysis (no code execution) to discover APIs, trace call chains, and analyze integration between backend and frontend components.

## Features

- **API Route Discovery**: Discover backend API routes via static AST analysis
- **Call Chain Tracing**: Trace function call chains through the codebase
- **Integration Analysis**: Check which backend API endpoints are used by frontend code
- **Dependency Injection Resolution**: Trace API endpoints through DI to service methods
- **Configuration-Driven**: All patterns are configurable via JSON configuration

## Architecture

The package is organized into:
- `src/mcp_devtools/` - Main source code
- `tests/` - Unit tests for all tools
- `docs/` - Documentation
- `examples/` - Example configurations for different frameworks

## Configuration

All tools support optional configuration to work with your project's patterns. Configuration is loaded from `mcp_config.json` in the workspace root or `.mcp/config.json`.

See `config_schema.json` for full schema documentation.

## Installation

(To be filled in after package is published)

## Development

See `CONTRIBUTING.md` for contribution guidelines.

## License

MIT
