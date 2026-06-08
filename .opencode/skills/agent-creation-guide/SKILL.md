---
name: agent-creation-guide
description: Guidelines for creating effective opencode agents. Covers agent.md format, frontmatter fields, tool permissions, and best practices. Load when creating or updating agents in .opencode/agents/.
---

# Agent Creation Guide for OpenCode

Agents are specialized AI assistants that can be configured for specific tasks and workflows. They allow you to create focused tools with custom prompts, models, and tool access.

## What Are Agents?

Key characteristics:

- **Specialized**: Each agent has a specific purpose and expertise area
- **Configurable**: Custom prompts, models, permissions, and tool access
- **Hierarchical**: Primary agents (user-facing) and subagents (task-specific)
- **Permission-controlled**: Fine-grained control over what each agent can do

## Agent Types

### Primary Agents

Primary agents are the main assistants you interact with directly. You can cycle through them using the **Tab** key, or your configured `switch_agent` keybind.

OpenCode comes with two built-in primary agents:
- **build** - Full development work with all tools enabled
- **plan** - Analysis and planning without making changes

### Subagents

Subagents are specialized assistants that primary agents can invoke for specific tasks. You can also manually invoke them by **@ mentioning** them in your messages.

OpenCode comes with three built-in subagents:
- **general** - General-purpose agent for complex tasks
- **explore** - Fast, read-only agent for exploring codebases
- **scout** - Read-only agent for external docs and dependency research

## Agent File Format

Agents are defined as markdown files in `.opencode/agents/` with YAML frontmatter:

```markdown
---
description: Reviews code for quality and best practices
mode: subagent
model: anthropic/claude-sonnet-4-20250514
temperature: 0.1
permission:
  edit: deny
  bash: deny
---

You are in code review mode. Focus on:
- Code quality and best practices
- Potential bugs and edge cases
- Performance implications
- Security considerations

Provide constructive feedback without making direct changes.
```

## Frontmatter Fields

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Brief description of the agent's purpose and when to use it |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `"all"` | Agent mode: `primary`, `subagent`, or `all` |
| `model` | string | inherited | Model to use (e.g., `anthropic/claude-sonnet-4-20250514`) |
| `temperature` | number | model default | Controls randomness (0.0-1.0) |
| `permission` | object | inherited | Tool permissions (see below) |
| `prompt` | string | - | Path to custom system prompt file |
| `steps` | number | unlimited | Maximum agentic iterations |
| `disable` | boolean | false | Disable the agent |
| `hidden` | boolean | false | Hide from @ autocomplete (subagents only) |
| `color` | string | - | UI color (hex or theme color) |
| `top_p` | number | - | Alternative to temperature for response diversity |

### Permission Field

The `permission` field controls what tools the agent can use. Each permission key can be set to:

- `"allow"` - Allow all operations without approval
- `"ask"` - Prompt for approval before running the tool
- `"deny"` - Disable the tool

Available permission keys:

| Key | Tools it gates |
|-----|----------------|
| `read` | `read` |
| `edit` | `write`, `edit`, `apply_patch` |
| `glob` | `glob` |
| `grep` | `grep` |
| `bash` | `bash` |
| `task` | `task` (subagent invocation) |
| `external_directory` | File operations outside project worktree |
| `todowrite` | `todowrite`, `todoread` |
| `webfetch` | `webfetch` |
| `websearch` | `websearch` |
| `lsp` | `lsp` |
| `skill` | `skill` |
| `question` | `question` |
| `doom_loop` | Recovery prompts when agent appears stuck |

You can also use wildcards for MCP tools:

```yaml
permission:
  "code-intel_*": allow
  "code-intel_edit_file_*": deny
```

Or use glob patterns for fine-grained control:

```yaml
permission:
  bash:
    "*": ask
    "git status *": allow
    "git log *": allow
```

## Agent Modes

### Primary Mode

```yaml
mode: primary
```

Primary agents are user-facing and can be switched to with Tab. They have full conversation context and can invoke subagents.

### Subagent Mode

```yaml
mode: subagent
```

Subagents are invoked by primary agents or via @ mention. They have limited context and are designed for specific tasks.

### All Mode (Default)

```yaml
mode: all
```

The agent can be used as both primary and subagent.

## Best Practices

### Description

Write clear, actionable descriptions that explain:
- **What** the agent does
- **When** to use it
- **Keywords** users might search for

**Good:**
```yaml
description: Reviews code for security vulnerabilities, performance issues, and best practices. Use when asked to review code, audit security, or check code quality.
```

**Poor:**
```yaml
description: Code reviewer
```

### Tool Permissions

Follow the principle of least privilege:

- **Read-only agents**: `edit: deny`, `bash: deny`
- **Planning agents**: `edit: deny`, `bash: ask`
- **Execution agents**: `edit: allow`, `bash: allow`
- **Review agents**: `edit: deny`, `bash: allow` (for running tests)

### Model Selection

Choose models based on task complexity:

- **Complex reasoning**: `anthropic/claude-sonnet-4-20250514` or better
- **Simple tasks**: `anthropic/claude-haiku-4-20250514` or similar
- **Code generation**: Models with strong coding capabilities

### Temperature

- **0.0-0.2**: Very focused, deterministic responses (analysis, planning)
- **0.3-0.5**: Balanced responses (general development)
- **0.6-1.0**: More creative responses (brainstorming, exploration)

### Prompt Files

For complex agents, use external prompt files:

```yaml
prompt: "{file:./prompts/code-review.txt}"
```

The path is relative to the agent file location.

## Example Agents

### Security Auditor

```markdown
---
description: Performs security audits and identifies vulnerabilities. Use when asked to audit code security, check for vulnerabilities, or review authentication/authorization.
mode: subagent
permission:
  edit: deny
---

You are a security expert. Focus on identifying potential security issues:

- Input validation vulnerabilities
- Authentication and authorization flaws
- Data exposure risks
- Dependency vulnerabilities
- Configuration security issues

Provide specific, actionable recommendations with code examples.
```

### Documentation Writer

```markdown
---
description: Writes and maintains project documentation. Use when asked to create docs, update READMEs, write API documentation, or improve existing documentation.
mode: subagent
model: anthropic/claude-sonnet-4-20250514
permission:
  edit: allow
  bash: deny
---

You are a technical writer. Create clear, comprehensive documentation:

- Clear explanations with examples
- Proper structure and formatting
- Code examples that work
- User-friendly language
- Cross-references to related docs

Follow the project's documentation style guide.
```

### Test Generator

```markdown
---
description: Generates unit tests and integration tests. Use when asked to write tests, improve test coverage, or create test fixtures.
mode: subagent
temperature: 0.3
permission:
  edit: allow
  bash: allow
---

You are a testing expert. Generate comprehensive tests:

- Unit tests for all public functions
- Integration tests for workflows
- Edge cases and error conditions
- Proper mocking and fixtures
- Clear test names and assertions

Run tests after creation to verify they pass.
```

## Validation Checklist

Before committing an agent:

- [ ] `description` clearly states purpose and use cases
- [ ] `mode` is appropriate for the agent's role
- [ ] `permission` follows least privilege principle
- [ ] `model` is appropriate for task complexity
- [ ] `temperature` is set if needed
- [ ] Agent file is in correct location (`.opencode/agents/`)
- [ ] Agent name follows conventions (lowercase, hyphens)
- [ ] Prompt is clear and actionable
- [ ] Agent has been tested with representative tasks

## Common Patterns

### Read-Only Agent

```yaml
mode: subagent
permission:
  edit: deny
  bash: deny
```

### Execution Agent

```yaml
mode: subagent
permission:
  edit: allow
  bash: allow
  todowrite: allow
```

### Planning Agent

```yaml
mode: primary
permission:
  edit: deny
  bash: ask
  todowrite: allow
```

### MCP-Heavy Agent

```yaml
mode: subagent
permission:
  "code-intel_*": allow
  edit: allow
  bash: allow
```

## Maintenance

**Keep agents up-to-date:**

- Review when workflows change
- Update when tools are added/removed
- Adjust permissions based on usage patterns
- Test with actual tasks

**Version control:**

- Commit agent files to git
- Share with team via repository
- Document changes in commit messages
- Use PR reviews to validate new agents
