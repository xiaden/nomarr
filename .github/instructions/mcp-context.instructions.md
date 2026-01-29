---
name: MCP Context
description: Guidelines for managing MCP server context and state
applyTo: scripts/mcp/context/**
---

# MCP Context Management

**Purpose:** Manage server lifecycle, shared state, and session context for MCP server operations.

Context provides access to server state, configuration, and request-specific information.

---

## Context Types in MCP

### 1. Lifespan Context (Application State)

Shared across all requests, initialized at startup:

```python
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from mcp.server.fastmcp import FastMCP

@dataclass
class AppContext:
    """Application-wide context."""
    workspace_root: Path
    cache: dict[str, Any]
    config: dict[str, Any]
    
    def __post_init__(self):
        """Initialize resources."""
        self.cache = {}
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """Load configuration."""
        config_path = self.workspace_root / ".nomarr" / "config.json"
        if config_path.exists():
            return json.loads(config_path.read_text())
        return {}

@asynccontextmanager
async def app_lifespan():
    """Manage application lifecycle."""
    # Startup
    ctx = AppContext(
        workspace_root=Path.cwd()
    )
    
    print("MCP server starting...", file=sys.stderr)
    
    yield ctx
    
    # Shutdown
    print("MCP server shutting down...", file=sys.stderr)
    ctx.cache.clear()

# Create server with lifespan
mcp = FastMCP("nomarr", lifespan=app_lifespan)
```

### 2. Request Context (Per-Request State)

Available in tools via `Context` parameter:

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("nomarr", lifespan=app_lifespan)

@mcp.tool()
async def cached_operation(
    key: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Tool with access to app context.
    
    Args:
        key: Cache key
        ctx: Request context with session and app state
    """
    # Access lifespan context
    app_ctx = ctx.request_context.lifespan_context
    
    # Check cache
    if key in app_ctx.cache:
        return {
            "result": app_ctx.cache[key],
            "cached": True
        }
    
    # Compute result
    result = expensive_operation(key)
    
    # Store in cache
    app_ctx.cache[key] = result
    
    return {
        "result": result,
        "cached": False
    }
```

### 3. Session Context (Client Connection)

Information about the connected client:

```python
@mcp.tool()
async def get_session_info(
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Get information about current session."""
    
    session = ctx.request_context.session
    
    return {
        "initialized": session.initialized,
        "client_info": session.client_info,
        "capabilities": session.capabilities
    }
```

---

## Lifespan Management Patterns

### Database Connection

```python
from dataclasses import dataclass
import aiosqlite

@dataclass
class AppContext:
    """App context with database."""
    workspace_root: Path
    db: aiosqlite.Connection

@asynccontextmanager
async def app_lifespan():
    """Manage DB connection lifecycle."""
    # Startup
    workspace_root = Path.cwd()
    db_path = workspace_root / ".nomarr" / "mcp.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    db = await aiosqlite.connect(db_path)
    
    # Initialize schema
    await db.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.commit()
    
    ctx = AppContext(workspace_root=workspace_root, db=db)
    
    yield ctx
    
    # Shutdown
    await db.close()

# Use in tools
@mcp.tool()
async def get_cached(
    key: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Get value from persistent cache."""
    app_ctx = ctx.request_context.lifespan_context
    
    async with app_ctx.db.execute(
        "SELECT value FROM cache WHERE key = ?",
        (key,)
    ) as cursor:
        row = await cursor.fetchone()
        
        if row:
            return {"key": key, "value": json.loads(row[0])}
        
        return {"key": key, "value": None, "found": False}
```

### Configuration Loading

```python
@dataclass
class AppContext:
    """App context with configuration."""
    workspace_root: Path
    config: dict[str, Any]
    ast_cache: dict[str, ast.Module]
    
    @property
    def nomarr_path(self) -> Path:
        """Path to nomarr package."""
        return self.workspace_root / "nomarr"
    
    @property
    def max_file_size(self) -> int:
        """Max file size from config."""
        return self.config.get("max_file_size", 100_000)

@asynccontextmanager
async def app_lifespan():
    """Load configuration at startup."""
    workspace_root = Path.cwd()
    
    # Load config
    config_path = workspace_root / ".nomarr" / "mcp-config.json"
    config = {}
    if config_path.exists():
        config = json.loads(config_path.read_text())
    
    ctx = AppContext(
        workspace_root=workspace_root,
        config=config,
        ast_cache={}
    )
    
    yield ctx
```

### Background Tasks

```python
import asyncio
from typing import Optional

@dataclass
class AppContext:
    """Context with background task."""
    workspace_root: Path
    background_task: Optional[asyncio.Task] = None
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

async def background_worker(ctx: AppContext):
    """Background task example."""
    while not ctx.shutdown_event.is_set():
        try:
            # Periodic work (e.g., cache cleanup)
            await cleanup_old_cache_entries(ctx)
            await asyncio.sleep(300)  # Every 5 minutes
        except asyncio.CancelledError:
            break

@asynccontextmanager
async def app_lifespan():
    """Manage background task lifecycle."""
    ctx = AppContext(workspace_root=Path.cwd())
    
    # Start background task
    ctx.background_task = asyncio.create_task(background_worker(ctx))
    
    yield ctx
    
    # Cleanup
    ctx.shutdown_event.set()
    if ctx.background_task:
        ctx.background_task.cancel()
        try:
            await ctx.background_task
        except asyncio.CancelledError:
            pass
```

---

## Caching Strategies

### In-Memory Cache

```python
from datetime import datetime, timedelta

@dataclass
class CacheEntry:
    """Cached value with expiration."""
    value: Any
    expires_at: datetime

@dataclass
class AppContext:
    """Context with TTL cache."""
    workspace_root: Path
    cache: dict[str, CacheEntry] = field(default_factory=dict)
    
    def get_cached(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        if key in self.cache:
            entry = self.cache[key]
            if datetime.now() < entry.expires_at:
                return entry.value
            else:
                # Expired, remove
                del self.cache[key]
        return None
    
    def set_cached(self, key: str, value: Any, ttl_seconds: int = 300):
        """Cache value with TTL."""
        self.cache[key] = CacheEntry(
            value=value,
            expires_at=datetime.now() + timedelta(seconds=ttl_seconds)
        )

# Use in tools
@mcp.tool()
async def expensive_analysis(
    module_name: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Analysis with caching."""
    app_ctx = ctx.request_context.lifespan_context
    
    # Check cache
    cached = app_ctx.get_cached(f"analysis:{module_name}")
    if cached:
        return {"result": cached, "from_cache": True}
    
    # Compute
    result = perform_analysis(module_name)
    
    # Cache for 10 minutes
    app_ctx.set_cached(f"analysis:{module_name}", result, ttl_seconds=600)
    
    return {"result": result, "from_cache": False}
```

### AST Cache

```python
import hashlib

@dataclass
class AppContext:
    """Context with AST caching."""
    workspace_root: Path
    ast_cache: dict[str, tuple[str, ast.Module]] = field(default_factory=dict)
    
    def get_ast(self, file_path: Path) -> ast.Module:
        """Get cached AST or parse file."""
        # Compute file hash
        content = file_path.read_bytes()
        file_hash = hashlib.md5(content).hexdigest()
        
        cache_key = str(file_path)
        
        # Check cache
        if cache_key in self.ast_cache:
            cached_hash, cached_ast = self.ast_cache[cache_key]
            if cached_hash == file_hash:
                return cached_ast
        
        # Parse and cache
        parsed = ast.parse(content, filename=str(file_path))
        self.ast_cache[cache_key] = (file_hash, parsed)
        
        return parsed

@mcp.tool()
def analyze_module(
    module_path: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Analyze with cached AST parsing."""
    app_ctx = ctx.request_context.lifespan_context
    
    file_path = Path(module_path)
    tree = app_ctx.get_ast(file_path)
    
    # Analyze AST
    return extract_analysis(tree)
```

---

## Progress Reporting

For long-running operations:

```python
@mcp.tool()
async def trace_large_codebase(
    entry_point: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Trace with progress updates."""
    
    # Find all files to analyze
    files_to_trace = discover_call_chain(entry_point)
    total = len(files_to_trace)
    
    results = []
    for i, file_path in enumerate(files_to_trace):
        # Report progress (sends notification to client)
        await ctx.info(
            f"Tracing {file_path} ({i+1}/{total})"
        )
        
        result = trace_file(file_path)
        results.append(result)
    
    return {
        "entry_point": entry_point,
        "files_traced": total,
        "call_chain": results
    }
```

---

## Logging with Context

```python
import logging

logger = logging.getLogger(__name__)

@mcp.tool()
async def risky_operation(
    target: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Operation with context-aware logging."""
    
    # Log with context info
    logger.info(
        f"Starting risky operation",
        extra={
            "target": target,
            "session": ctx.request_context.session.initialized,
        }
    )
    
    try:
        result = perform_operation(target)
        
        logger.info(f"Operation completed successfully")
        
        return {"success": True, "result": result}
    
    except Exception as e:
        logger.error(
            f"Operation failed: {e}",
            extra={"target": target},
            exc_info=True
        )
        
        # Can also notify client
        await ctx.error(f"Operation failed: {e}")
        
        raise
```

---

## State Persistence

### Save/Load State

```python
@dataclass
class AppContext:
    """Context with state persistence."""
    workspace_root: Path
    state_file: Path = field(init=False)
    state: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.state_file = self.workspace_root / ".nomarr" / "mcp-state.json"
        self._load_state()
    
    def _load_state(self):
        """Load persisted state."""
        if self.state_file.exists():
            self.state = json.loads(self.state_file.read_text())
    
    def save_state(self):
        """Persist current state."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2))

@asynccontextmanager
async def app_lifespan():
    """Lifecycle with state persistence."""
    ctx = AppContext(workspace_root=Path.cwd())
    
    yield ctx
    
    # Save state on shutdown
    ctx.save_state()

@mcp.tool()
async def remember_preference(
    key: str,
    value: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Store user preference persistently."""
    app_ctx = ctx.request_context.lifespan_context
    
    app_ctx.state[key] = value
    app_ctx.save_state()
    
    return {"stored": True, "key": key}
```

---

## Resource Cleanup

```python
@dataclass
class AppContext:
    """Context with managed resources."""
    workspace_root: Path
    temp_files: list[Path] = field(default_factory=list)
    
    def create_temp_file(self, prefix: str = "mcp_") -> Path:
        """Create tracked temp file."""
        import tempfile
        fd, path = tempfile.mkstemp(prefix=prefix)
        os.close(fd)
        temp_path = Path(path)
        self.temp_files.append(temp_path)
        return temp_path
    
    def cleanup(self):
        """Remove all temp files."""
        for temp_file in self.temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception as e:
                logging.error(f"Failed to cleanup {temp_file}: {e}")
        self.temp_files.clear()

@asynccontextmanager
async def app_lifespan():
    """Lifecycle with resource cleanup."""
    ctx = AppContext(workspace_root=Path.cwd())
    
    yield ctx
    
    # Cleanup temp files
    ctx.cleanup()
```

---

## Context Access Patterns

### Read-Only Context

Most tools only need to read context:

```python
@mcp.tool()
def get_config_value(
    key: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Read configuration value."""
    app_ctx = ctx.request_context.lifespan_context
    
    value = app_ctx.config.get(key)
    
    return {"key": key, "value": value}
```

### Mutable Context

Some tools need to modify context:

```python
@mcp.tool()
async def update_cache(
    key: str,
    value: str,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Update cache entry."""
    app_ctx = ctx.request_context.lifespan_context
    
    app_ctx.cache[key] = value
    
    return {"updated": True, "cache_size": len(app_ctx.cache)}
```

### Thread-Safe Context

For concurrent access:

```python
from asyncio import Lock

@dataclass
class AppContext:
    """Thread-safe context."""
    workspace_root: Path
    cache: dict[str, Any] = field(default_factory=dict)
    cache_lock: Lock = field(default_factory=Lock)
    
    async def get_or_compute(self, key: str, compute_fn) -> Any:
        """Thread-safe get-or-compute pattern."""
        async with self.cache_lock:
            if key in self.cache:
                return self.cache[key]
            
            value = await compute_fn()
            self.cache[key] = value
            return value
```

---

## Summary Checklist

When managing MCP context:

- [ ] Use `@asynccontextmanager` for lifespan
- [ ] Define typed context class (dataclass)
- [ ] Initialize resources at startup
- [ ] Cleanup resources at shutdown
- [ ] Use `Context[ServerSession, AppContext]` parameter
- [ ] Access via `ctx.request_context.lifespan_context`
- [ ] Handle errors in lifespan gracefully
- [ ] Log startup/shutdown to stderr
- [ ] Implement caching when beneficial
- [ ] Use locks for concurrent access
- [ ] Persist state if needed
- [ ] Clean up temp files/resources
- [ ] Document context structure
