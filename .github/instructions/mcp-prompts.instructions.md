---
name: MCP Prompts
description: Guidelines for creating reusable prompt templates
applyTo: scripts/mcp/prompts/**
---

# MCP Prompts Implementation

**Purpose:** Create reusable prompt templates that standardize common AI agent workflows and tasks.

Prompts are **interaction templates** that help AI agents perform consistent, well-defined tasks.

---

## Prompts vs Tools vs Resources

| Aspect | Prompts | Tools | Resources |
|--------|---------|-------|-----------|
| **Purpose** | Task templates | Actions | Data |
| **Returns** | Messages for LLM | Structured data | Content |
| **Use When** | Standardize workflows | Execute operations | Access information |
| **Example** | "Review code" | `lint_backend()` | `file://code.py` |

---

## Prompt Definition Pattern

### Basic Structure

```python
from mcp.server.fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent

mcp = FastMCP("nomarr")

@mcp.prompt()
def review_code(file_path: str) -> list[PromptMessage]:
    """Review code for best practices and issues.
    
    Args:
        file_path: Path to file to review
    
    Returns:
        List of messages forming the review prompt
    """
    # Get file content
    code = Path(file_path).read_text()
    
    # Build prompt messages
    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Review this Python code for:
- PEP 8 compliance
- Type hint coverage
- Error handling
- Security issues
- Performance concerns

File: {file_path}

```python
{code}
```

Provide specific, actionable feedback.
"""
            )
        )
    ]
```

---

## Prompt Components

### Messages

Prompts return a list of messages with roles:

```python
from mcp.types import PromptMessage, TextContent

@mcp.prompt()
def architecture_review(layer: str, module: str) -> list[PromptMessage]:
    """Review module against architecture guidelines."""
    
    # Get architecture rules
    instructions = Path(f".github/instructions/{layer}.instructions.md").read_text()
    
    # Get module code
    code = Path(f"nomarr/{layer}/{module}.py").read_text()
    
    return [
        # System context
        PromptMessage(
            role="system",
            content=TextContent(
                type="text",
                text=f"""You are reviewing Nomarr architecture compliance.

Architecture Guidelines:
{instructions}
"""
            )
        ),
        # User request
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Review this {layer} module for architecture violations:

```python
{code}
```

Check:
1. Dependency direction (imports from allowed layers only)
2. Naming conventions
3. Layer responsibilities
4. Code organization

Report any violations with line numbers and suggested fixes.
"""
            )
        )
    ]
```

### Message Roles

- **system**: Background context, instructions, guidelines
- **user**: The actual task request
- **assistant**: Example responses (for few-shot prompting)

---

## Nomarr Prompt Categories

### Code Review Prompts

```python
@mcp.prompt()
def review_for_security(file_path: str) -> list[PromptMessage]:
    """Security-focused code review.
    
    Args:
        file_path: Python file to review
    """
    code = Path(file_path).read_text()
    
    return [
        PromptMessage(
            role="system",
            content=TextContent(
                type="text",
                text="""You are a security expert reviewing Python code.

Focus on:
- SQL injection risks
- Path traversal vulnerabilities  
- Unsafe deserialization
- Authentication/authorization issues
- Input validation gaps
- Secrets exposure
"""
            )
        ),
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Review this file for security issues:

{file_path}

```python
{code}
```

For each issue:
1. Severity (Critical/High/Medium/Low)
2. Line number(s)
3. Description
4. Recommended fix
"""
            )
        )
    ]
```

### Architecture Validation

```python
@mcp.prompt()
def validate_layer_compliance(layer: str, file_path: str) -> list[PromptMessage]:
    """Validate module follows layer architecture rules.
    
    Args:
        layer: Layer name (services, workflows, components, etc)
        file_path: File to validate
    """
    # Load layer instructions
    instructions = Path(f".github/instructions/{layer}.instructions.md").read_text()
    code = Path(file_path).read_text()
    
    return [
        PromptMessage(
            role="system",
            content=TextContent(
                type="text",
                text=f"""Validate Nomarr {layer} layer compliance.

Architecture Rules:
{instructions}
"""
            )
        ),
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Validate this {layer} module:

{file_path}

```python
{code}
```

Check:
1. Imports (only allowed layers)
2. Naming conventions (files, classes, functions)
3. Layer responsibilities
4. Required patterns

List all violations with line numbers and fixes.
"""
            )
        )
    ]
```

### Documentation Generation

```python
@mcp.prompt()
def generate_api_docs(module_name: str) -> list[PromptMessage]:
    """Generate API documentation for a module.
    
    Args:
        module_name: Fully qualified module name
    """
    # Discover API structure
    api_info = discover_api(module_name)
    
    # Get source for key functions
    sources = {}
    for func in api_info.get("Function", [])[:5]:  # Limit to 5
        qualified_name = f"{module_name}.{func}"
        sources[func] = get_source(qualified_name)
    
    return [
        PromptMessage(
            role="system",
            content=TextContent(
                type="text",
                text="""Generate clear, concise API documentation.

Format:
# Module Name

Brief description.

## Functions

### function_name
**Purpose:** What it does
**Parameters:**
- param: description
**Returns:** description
**Example:**
```python
example_usage()
```
"""
            )
        ),
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Generate API documentation for {module_name}

API Structure:
{json.dumps(api_info, indent=2)}

Source Code:
{json.dumps(sources, indent=2)}
"""
            )
        )
    ]
```

### Test Generation

```python
@mcp.prompt()
def generate_tests(function_name: str) -> list[PromptMessage]:
    """Generate pytest tests for a function.
    
    Args:
        function_name: Fully qualified function name
    """
    source_info = get_source(function_name)
    
    return [
        PromptMessage(
            role="system",
            content=TextContent(
                type="text",
                text="""Generate comprehensive pytest tests.

Include:
- Happy path test
- Edge cases
- Error conditions
- Parametrized tests if applicable

Use pytest fixtures, clear assertions, descriptive names.
"""
            )
        ),
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Generate tests for:

{function_name}

Source:
```python
{source_info['source']}
```

File: {source_info['file']}
Lines: {source_info['line']}-{source_info['line'] + source_info['line_count']}
"""
            )
        )
    ]
```

---

## Prompt Arguments

### Dynamic vs Static

```python
# Dynamic - requires arguments
@mcp.prompt()
def review_file(file_path: str, focus: str = "general") -> list[PromptMessage]:
    """Review with configurable focus."""
    # Use arguments to customize prompt
    ...

# Static - no arguments needed
@mcp.prompt()
def explain_architecture() -> list[PromptMessage]:
    """Explain Nomarr architecture (no params)."""
    arch_docs = Path(".github/copilot-instructions.md").read_text()
    
    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Explain Nomarr's architecture:

{arch_docs}

Summarize:
1. Layer structure
2. Dependency flow
3. Key principles
4. Common patterns
"""
            )
        )
    ]
```

### Optional Parameters

```python
@mcp.prompt()
def review_code(
    file_path: str,
    focus: str = "all",
    include_examples: bool = True
) -> list[PromptMessage]:
    """Flexible review prompt with options.
    
    Args:
        file_path: File to review
        focus: Focus area (security, performance, style, all)
        include_examples: Include fix examples
    """
    code = Path(file_path).read_text()
    
    # Customize based on focus
    focus_areas = {
        "security": ["Authentication", "Input validation", "SQL injection"],
        "performance": ["Database queries", "Caching", "Algorithmic complexity"],
        "style": ["PEP 8", "Type hints", "Docstrings"],
        "all": ["Security", "Performance", "Style", "Best practices"]
    }
    
    areas = focus_areas.get(focus, focus_areas["all"])
    
    prompt_text = f"""Review {file_path} focusing on: {', '.join(areas)}

```python
{code}
```

For each issue:
- Line number
- Severity
- Description
"""
    
    if include_examples:
        prompt_text += "\n- Code fix example"
    
    return [
        PromptMessage(
            role="user",
            content=TextContent(type="text", text=prompt_text)
        )
    ]
```

---

## Combining Tools and Resources

Prompts can reference tools and resources:

```python
@mcp.prompt()
def trace_and_document(endpoint: str) -> list[PromptMessage]:
    """Trace endpoint and generate documentation.
    
    Uses trace_endpoint tool and file resources.
    """
    # This prompt instructs AI to use other capabilities
    return [
        PromptMessage(
            role="system",
            content=TextContent(
                type="text",
                text="""You have access to:
- trace_endpoint tool
- file:// resources  
- get_source tool

Use these to understand the endpoint fully.
"""
            )
        ),
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Document the {endpoint} API endpoint:

1. Use trace_endpoint("{endpoint}") to see the call flow
2. Use get_source() to read each function in the chain
3. Document:
   - Purpose
   - Request/response format
   - Business logic flow
   - Dependencies used
   - Error conditions

Generate comprehensive API documentation.
"""
            )
        )
    ]
```

---

## Prompt Discovery

Provide clear descriptions for prompt discovery:

```python
@mcp.prompt(
    description="Review Python code for security vulnerabilities and generate a detailed security report"
)
def security_review(file_path: str) -> list[PromptMessage]:
    """Security review with detailed description."""
    ...

@mcp.prompt(
    description="Generate pytest tests with fixtures, parametrization, and edge cases"
)
def generate_tests(function_name: str) -> list[PromptMessage]:
    """Test generation with description."""
    ...
```

---

## Multi-Turn Prompts

Create prompts that guide multi-step workflows:

```python
@mcp.prompt()
def refactor_workflow(file_path: str) -> list[PromptMessage]:
    """Multi-step refactoring workflow."""
    
    code = Path(file_path).read_text()
    
    return [
        PromptMessage(
            role="system",
            content=TextContent(
                type="text",
                text="""You are refactoring Python code in steps:

Step 1: Analyze current code
Step 2: Identify issues
Step 3: Propose refactoring plan
Step 4: Implement changes
Step 5: Verify improvements

After each step, wait for user confirmation before proceeding.
"""
            )
        ),
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Refactor this code:

{file_path}

```python
{code}
```

Start with Step 1: Analyze the current code structure.
"""
            )
        )
    ]
```

---

## Error Handling

```python
@mcp.prompt()
def review_code(file_path: str) -> list[PromptMessage]:
    """Review with error handling."""
    
    # Validate file exists
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}. "
            "Provide a valid path relative to workspace root."
        )
    
    # Validate file type
    if path.suffix != ".py":
        raise ValueError(
            f"Expected Python file, got {path.suffix}. "
            "This prompt only works with .py files."
        )
    
    # Validate size
    size = path.stat().st_size
    if size > 100_000:  # 100KB
        raise ValueError(
            f"File too large ({size} bytes). "
            "Use read_file with line ranges for large files."
        )
    
    code = path.read_text()
    
    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"Review:\n\n```python\n{code}\n```"
            )
        )
    ]
```

---

## Prompt Templates

Create reusable template builders:

```python
def build_review_prompt(
    title: str,
    focus_areas: list[str],
    code: str,
    file_path: str
) -> list[PromptMessage]:
    """Reusable review prompt template."""
    
    areas_text = "\n".join(f"- {area}" for area in focus_areas)
    
    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""{title}

File: {file_path}

Focus on:
{areas_text}

```python
{code}
```

Provide specific, actionable feedback with line numbers.
"""
            )
        )
    ]

# Use template in prompts
@mcp.prompt()
def security_review(file_path: str) -> list[PromptMessage]:
    """Security review using template."""
    code = Path(file_path).read_text()
    
    return build_review_prompt(
        title="Security Review",
        focus_areas=[
            "SQL injection risks",
            "Path traversal",
            "Authentication issues",
            "Input validation"
        ],
        code=code,
        file_path=file_path
    )
```

---

## Embedding Context

Include relevant context automatically:

```python
@mcp.prompt()
def review_service(service_file: str) -> list[PromptMessage]:
    """Review service with layer context."""
    
    # Load service code
    code = Path(service_file).read_text()
    
    # Load layer instructions automatically
    instructions = Path(".github/instructions/services.instructions.md").read_text()
    
    # Get related workflow/component info
    calls = trace_calls_from_file(service_file)
    
    return [
        PromptMessage(
            role="system",
            content=TextContent(
                type="text",
                text=f"""Services Layer Architecture:

{instructions}

This service calls:
{json.dumps(calls, indent=2)}
"""
            )
        ),
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"""Review this service:

{service_file}

```python
{code}
```

Verify:
1. Follows services layer patterns
2. Only calls workflows (not components directly)
3. Proper DI usage
4. DTO transformations
"""
            )
        )
    ]
```

---

## Summary Checklist

Before committing a prompt:

- [ ] Uses `@mcp.prompt()` decorator
- [ ] Returns `list[PromptMessage]`
- [ ] Clear docstring with purpose and args
- [ ] Includes `description` for discovery
- [ ] Validates all arguments
- [ ] Helpful error messages
- [ ] System context when needed
- [ ] Clear, specific instructions
- [ ] Incorporates relevant context (docs, guidelines)
- [ ] Limits code/content size
- [ ] Structured output format specified
- [ ] Examples included when helpful
- [ ] Multi-step workflows broken down clearly
