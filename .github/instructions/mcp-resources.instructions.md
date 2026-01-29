---
name: MCP Resources
description: Guidelines for exposing data through MCP resources
applyTo: scripts/mcp/resources/**
---

# MCP Resources Implementation

**Purpose:** Expose Nomarr's data and files through URI-based resources that AI agents can read.

Resources are **data sources** that AI can access via URIs, like files, configs, or dynamic content.

---

## Resources vs Tools

| Aspect | Resources | Tools |
|--------|-----------|-------|
| **Purpose** | Data retrieval | Actions/computations |
| **Access Pattern** | URI-based | Function call |
| **Side Effects** | None (read-only) | Allowed |
| **Example** | `file://docs/api.md` | `generate_docs()` |
| **Use When** | Exposing existing data | Processing/transforming |

---

## Resource Definition Pattern

### Static Resource

Fixed URI, always returns same content:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nomarr")

@mcp.resource("config://settings")
def get_settings() -> str:
    """Application configuration settings.
    
    Returns:
        JSON string of current config
    """
    return json.dumps({
        "version": "0.1.0",
        "environment": "development",
        "db_path": str(DB_PATH)
    })
```

### Dynamic Resource

URI template with parameters:

```python
@mcp.resource("file://nomarr/{layer}/{module_name}")
def get_module_info(layer: str, module_name: str) -> str:
    """Get information about a Nomarr module.
    
    Args:
        layer: Layer name (services, workflows, components, etc)
        module_name: Module name without .py extension
    
    Returns:
        JSON with module metadata and API overview
    """
    module_path = f"nomarr/{layer}/{module_name}.py"
    
    if not Path(module_path).exists():
        raise FileNotFoundError(f"Module not found: {module_path}")
    
    api_info = discover_api_from_file(module_path)
    return json.dumps({
        "module": f"{layer}.{module_name}",
        "path": module_path,
        "api": api_info
    })
```

---

## URI Schemes

Use descriptive, consistent URI schemes:

### Common Schemes

```python
# Configuration
@mcp.resource("config://settings")
@mcp.resource("config://database")

# Files (use absolute paths or workspace-relative)
@mcp.resource("file://nomarr/{layer}/{module}")
@mcp.resource("file://docs/{category}/{doc_name}")

# Documentation
@mcp.resource("docs://api/endpoints")
@mcp.resource("docs://architecture/{layer}")

# Dynamic data
@mcp.resource("data://stats/api-coverage")
@mcp.resource("data://cache/{key}")

# Repository info
@mcp.resource("repo://structure")
@mcp.resource("repo://dependencies")
```

### Scheme Conventions

- Use lowercase
- Plural for collections: `docs://`, not `doc://`
- Hierarchical: `category/subcategory/item`
- Predictable patterns

---

## MIME Types

Specify MIME types for non-text resources:

```python
# Text (default)
@mcp.resource("file://README.md")
def get_readme() -> str:
    """Returns text/plain by default."""
    return Path("README.md").read_text()

# JSON
@mcp.resource("config://settings", mimeType="application/json")
def get_settings() -> str:
    """Explicitly JSON."""
    return json.dumps({...})

# Binary data
@mcp.resource("image://architecture-diagram", mimeType="image/png")
def get_diagram() -> bytes:
    """Binary resource."""
    return Path("docs/architecture.png").read_bytes()

# Markdown
@mcp.resource("docs://instructions/{topic}", mimeType="text/markdown")
def get_instructions(topic: str) -> str:
    """Markdown documentation."""
    return Path(f".github/instructions/{topic}.instructions.md").read_text()
```

---

## Resource Discovery

AI agents discover resources via listing:

```python
# Client calls list_resources()
# Should return all available resources

# Static resources auto-register
@mcp.resource("config://settings")
def get_settings() -> str:
    return json.dumps({...})

# Dynamic resources show templates
@mcp.resource("file://{layer}/{module}")
def get_module(layer: str, module: str) -> str:
    # Shows as template: file://{layer}/{module}
    return module_content
```

### Resource Metadata

Provide descriptions for better discovery:

```python
@mcp.resource(
    "docs://architecture/{layer}",
    description="Architecture documentation for a specific layer"
)
def get_layer_docs(layer: str) -> str:
    """Get architecture docs for services, workflows, etc."""
    return get_layer_documentation(layer)
```

---

## Nomarr Resource Categories

### Configuration Resources

```python
@mcp.resource("config://app", mimeType="application/json")
def get_app_config() -> str:
    """Current application configuration."""
    return json.dumps({
        "db_path": str(DB_PATH),
        "models_dir": str(MODELS_DIR),
        "cache_enabled": True
    })

@mcp.resource("config://dependencies", mimeType="application/json")
def get_dependencies() -> str:
    """Installed Python dependencies."""
    reqs = Path("requirements.txt").read_text().splitlines()
    return json.dumps({"dependencies": reqs})
```

### File Resources

```python
@mcp.resource("file://nomarr/{path:path}")
def get_file_content(path: str) -> str:
    """Get content of any file in nomarr package.
    
    Args:
        path: Path relative to nomarr/ directory
    
    Returns:
        File content as text
    """
    file_path = Path("nomarr") / path
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if not file_path.is_file():
        raise ValueError(f"Not a file: {file_path}")
    
    # Security: ensure path is within nomarr/
    if not file_path.resolve().is_relative_to(Path("nomarr").resolve()):
        raise ValueError(f"Access denied: {file_path}")
    
    return file_path.read_text()
```

### Documentation Resources

```python
@mcp.resource(
    "docs://instructions/{topic}",
    mimeType="text/markdown",
    description="Copilot instruction files for specific topics"
)
def get_instructions(topic: str) -> str:
    """Get instruction file content.
    
    Args:
        topic: Instruction topic (e.g., 'services', 'testing')
    
    Returns:
        Markdown content of instruction file
    """
    path = Path(f".github/instructions/{topic}.instructions.md")
    
    if not path.exists():
        available = [f.stem for f in Path(".github/instructions").glob("*.instructions.md")]
        raise FileNotFoundError(
            f"Instruction file '{topic}' not found. "
            f"Available: {', '.join(available)}"
        )
    
    return path.read_text()
```

### Repository Structure

```python
@mcp.resource("repo://structure", mimeType="application/json")
def get_repo_structure() -> str:
    """Repository directory structure.
    
    Returns:
        JSON tree of directories and files
    """
    def build_tree(path: Path, max_depth: int = 3, current_depth: int = 0):
        if current_depth >= max_depth:
            return {"...truncated": True}
        
        tree = {}
        for item in sorted(path.iterdir()):
            if item.name.startswith("."):
                continue
            
            if item.is_dir():
                tree[item.name + "/"] = build_tree(item, max_depth, current_depth + 1)
            else:
                tree[item.name] = {"type": "file"}
        
        return tree
    
    return json.dumps({
        "nomarr": build_tree(Path("nomarr")),
        "scripts": build_tree(Path("scripts")),
        "docs": build_tree(Path("docs")) if Path("docs").exists() else None
    })
```

---

## Parameter Validation

Validate resource parameters thoroughly:

```python
@mcp.resource("file://nomarr/{layer}/{module_name}")
def get_module(layer: str, module_name: str) -> str:
    """Get module with validated parameters."""
    
    # Valid layers
    VALID_LAYERS = ["interfaces", "services", "workflows", "components", "persistence", "helpers"]
    
    if layer not in VALID_LAYERS:
        raise ValueError(
            f"Invalid layer '{layer}'. "
            f"Valid layers: {', '.join(VALID_LAYERS)}"
        )
    
    # Sanitize module name (prevent path traversal)
    if ".." in module_name or "/" in module_name:
        raise ValueError(f"Invalid module name: {module_name}")
    
    # Check existence
    module_path = Path(f"nomarr/{layer}/{module_name}.py")
    if not module_path.exists():
        raise FileNotFoundError(
            f"Module not found: {layer}/{module_name}. "
            f"Use list_modules tool to see available modules."
        )
    
    return module_path.read_text()
```

---

## Security Considerations

### Path Traversal Prevention

```python
@mcp.resource("file://{path:path}")
def get_file(path: str) -> str:
    """Secure file access with path validation."""
    
    # Resolve to absolute path
    requested_path = Path(path).resolve()
    allowed_base = Path.cwd().resolve()
    
    # Ensure path is within workspace
    if not requested_path.is_relative_to(allowed_base):
        raise ValueError(f"Access denied: path outside workspace")
    
    # Deny sensitive files
    DENIED_PATTERNS = [".env", "*.key", "*.pem", ".git/*"]
    for pattern in DENIED_PATTERNS:
        if requested_path.match(pattern):
            raise ValueError(f"Access denied: sensitive file")
    
    return requested_path.read_text()
```

### Limit Resource Size

```python
MAX_RESOURCE_SIZE = 1_000_000  # 1MB

@mcp.resource("file://{path:path}")
def get_file(path: str) -> str:
    """Get file with size limit."""
    file_path = Path(path)
    
    # Check size before reading
    size = file_path.stat().st_size
    if size > MAX_RESOURCE_SIZE:
        raise ValueError(
            f"File too large: {size} bytes (max {MAX_RESOURCE_SIZE}). "
            "Use read_file tool with line ranges instead."
        )
    
    return file_path.read_text()
```

---

## Caching Resources

Cache expensive resource generation:

```python
from functools import lru_cache
from datetime import datetime, timedelta

# Cache with expiration
_cache: dict[str, tuple[str, datetime]] = {}
CACHE_TTL = timedelta(minutes=5)

@mcp.resource("repo://structure", mimeType="application/json")
def get_repo_structure() -> str:
    """Get cached repository structure."""
    
    cache_key = "repo_structure"
    now = datetime.now()
    
    # Check cache
    if cache_key in _cache:
        content, cached_at = _cache[cache_key]
        if now - cached_at < CACHE_TTL:
            return content
    
    # Generate new
    structure = build_repo_tree()
    content = json.dumps(structure)
    
    # Cache it
    _cache[cache_key] = (content, now)
    
    return content
```

---

## Resource Completion

Provide autocomplete for resource parameters:

```python
@mcp.completion("file://nomarr/{layer}/{module}")
def complete_module_path(
    argument: str,
    value: str,
    context: dict[str, str]
) -> list[str]:
    """Autocomplete suggestions for module resource."""
    
    if argument == "layer":
        # Suggest layer names
        layers = ["services", "workflows", "components", "persistence", "helpers"]
        return [layer for layer in layers if layer.startswith(value)]
    
    if argument == "module" and "layer" in context:
        # Suggest modules for selected layer
        layer = context["layer"]
        layer_path = Path(f"nomarr/{layer}")
        
        if layer_path.exists():
            modules = [f.stem for f in layer_path.glob("*.py") if f.stem != "__init__"]
            return [mod for mod in modules if mod.startswith(value)]
    
    return []
```

---

## Summary Checklist

Before committing a resource:

- [ ] Uses `@mcp.resource(uri)` decorator
- [ ] URI scheme is descriptive and consistent
- [ ] Specifies `mimeType` if not text/plain
- [ ] Includes `description` for discovery
- [ ] Validates all URI parameters
- [ ] Prevents path traversal attacks
- [ ] Enforces size limits for large content
- [ ] Returns consistent format (text/JSON/bytes)
- [ ] Helpful error messages for invalid URIs
- [ ] Completion provider if using templates
- [ ] Read-only operation (no side effects)
- [ ] Cached if expensive to generate
