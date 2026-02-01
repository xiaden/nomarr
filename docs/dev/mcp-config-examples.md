# MCP DevTools Configuration Examples

Complete configuration examples for different framework combinations.

## FastAPI + React (Nomarr's Stack)

```json
{
  "$schema": "./config_schema.json",
  "backend": {
    "framework": "fastapi",
    "routes": {
      "decorators": [
        "@router.get",
        "@router.post",
        "@router.put",
        "@router.patch",
        "@router.delete"
      ],
      "search_paths": ["nomarr/interfaces/api/**/*.py"],
      "exclude_paths": ["**/test_*.py"]
    },
    "modules": {
      "root_package": "nomarr",
      "search_paths": ["nomarr/**/*.py"]
    },
    "dependency_injection": {
      "patterns": ["Depends(", "Annotated["],
      "resolver_functions": ["get_", "provide_"]
    }
  },
  "frontend": {
    "framework": "react",
    "api_calls": {
      "patterns": [
        "api.get(",
        "api.post(",
        "api.put(",
        "api.patch(",
        "api.delete("
      ],
      "search_paths": ["frontend/src/**/*.{ts,tsx}"],
      "exclude_paths": ["frontend/node_modules/**", "frontend/dist/**"]
    }
  },
  "project": {
    "workspace_root": ".",
    "backend_path": "nomarr",
    "frontend_path": "frontend",
    "ignore_patterns": [
      "**/__pycache__/**",
      "**/node_modules/**",
      "**/.venv/**",
      "**/dist/**"
    ]
  },
  "tracing": {
    "max_depth": 15,
    "filter_external": true,
    "include_patterns": ["nomarr.*"]
  }
}
```

## Flask + Vue

```json
{
  "$schema": "https://raw.githubusercontent.com/your-repo/python-mcp-devtools/main/config_schema.json",
  "backend": {
    "framework": "flask",
    "routes": {
      "decorators": [
        "@app.route",
        "@blueprint.route",
        "@bp.route",
        "@api.route"
      ],
      "search_paths": ["app/**/*.py", "views/**/*.py"],
      "exclude_paths": ["tests/**"]
    },
    "modules": {
      "root_package": "app",
      "search_paths": ["app/**/*.py"]
    }
  },
  "frontend": {
    "framework": "vue",
    "api_calls": {
      "patterns": [
        "$http.get(",
        "$http.post(",
        "axios.get(",
        "axios.post(",
        "fetch("
      ],
      "search_paths": ["frontend/src/**/*.vue", "frontend/src/**/*.{js,ts}"],
      "exclude_paths": ["frontend/node_modules/**"]
    }
  },
  "project": {
    "backend_path": "app",
    "frontend_path": "frontend"
  }
}
```

## Django + Svelte

```json
{
  "$schema": "https://raw.githubusercontent.com/your-repo/python-mcp-devtools/main/config_schema.json",
  "backend": {
    "framework": "django",
    "routes": {
      "decorators": ["path(", "re_path(", "url("],
      "search_paths": ["**/urls.py", "apps/**/views.py"],
      "exclude_paths": ["venv/**", "tests/**"]
    },
    "modules": {
      "root_package": "myproject",
      "search_paths": ["apps/**/*.py", "myproject/**/*.py"]
    }
  },
  "frontend": {
    "framework": "svelte",
    "api_calls": {
      "patterns": [
        "fetch(",
        "get(",
        "post(",
        "axios.get(",
        "axios.post("
      ],
      "search_paths": ["frontend/src/**/*.svelte", "frontend/src/**/*.{js,ts}"],
      "exclude_paths": ["frontend/node_modules/**", "frontend/build/**"]
    }
  },
  "project": {
    "backend_path": ".",
    "frontend_path": "frontend"
  },
  "tracing": {
    "max_depth": 10,
    "include_patterns": ["myproject.*", "apps.*"]
  }
}
```

## Minimal Configuration

For a standard FastAPI + React project, you can use minimal config and rely on defaults:

```json
{
  "backend": {
    "modules": {
      "root_package": "myapp"
    }
  },
  "tracing": {
    "include_patterns": ["myapp.*"]
  }
}
```

All other settings use smart defaults.

## Monorepo Configuration

For projects with multiple services:

```json
{
  "backend": {
    "framework": "fastapi",
    "routes": {
      "search_paths": [
        "services/*/api/**/*.py",
        "packages/*/interfaces/**/*.py"
      ]
    },
    "modules": {
      "root_package": null,
      "search_paths": ["services/**/*.py", "packages/**/*.py"]
    }
  },
  "frontend": {
    "api_calls": {
      "search_paths": [
        "apps/*/src/**/*.{ts,tsx}",
        "packages/*/src/**/*.{ts,tsx}"
      ]
    }
  },
  "project": {
    "ignore_patterns": [
      "**/__pycache__/**",
      "**/node_modules/**",
      "**/dist/**",
      "**/.venv/**",
      "services/*/venv/**"
    ]
  },
  "tracing": {
    "include_patterns": ["services.*", "packages.*"]
  }
}
```

## Custom Framework

For non-standard frameworks or custom routing:

```json
{
  "backend": {
    "framework": "custom",
    "routes": {
      "decorators": [
        "@my_framework.route",
        "@custom.api",
        "route_handler("
      ],
      "search_paths": ["src/**/*.py"]
    }
  },
  "frontend": {
    "framework": "custom",
    "api_calls": {
      "patterns": [
        "myClient.request(",
        "callApi(",
        "dataService.fetch("
      ],
      "search_paths": ["client/**/*.ts"]
    }
  }
}
```

## Tool-Specific Overrides

Disable specific tools or customize behavior:

```json
{
  "tools": {
    "disabled": ["trace_endpoint"],
    "custom": {
      "project_list_routes": {
        "include_middleware": true,
        "show_internal_routes": false
      }
    }
  }
}
```

## Configuration in pyproject.toml

Alternative: embed config in `pyproject.toml`:

```toml
[tool.mcp]
backend.framework = "fastapi"
backend.modules.root_package = "myapp"
frontend.framework = "react"

[tool.mcp.tracing]
max_depth = 15
include_patterns = ["myapp.*"]
```

## Validation

All configs are validated against [config_schema.json](../../scripts/mcp/config_schema.json). Use JSON Schema validation in your editor for autocomplete and error checking.

Add to your workspace settings:
```json
{
  "json.schemas": [
    {
      "fileMatch": ["mcp_config.json", ".mcp/config.json"],
      "url": "./scripts/mcp/config_schema.json"
    }
  ]
}
```
