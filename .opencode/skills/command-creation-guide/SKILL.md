---
name: command-creation-guide
description: Guidelines for creating effective OpenCode commands. Covers command definition in opencode.json, frontmatter fields, prompt structure, and best practices. Load when creating or updating commands.
---

# Command Creation Guide for OpenCode

Commands are reusable prompts that guide OpenCode to deliver consistent, high-quality outcomes. They appear in the command palette and can be invoked with `/command-name`.

## What Are Commands?

Key characteristics:

- **Reusable**: Define once, use many times across sessions
- **Consistent**: Ensure the same quality and approach every time
- **Discoverable**: Appear in command palette with descriptions
- **Configurable**: Can specify agent, model, and tool restrictions

## Command Definition

Commands are defined in `opencode.json` under the `commands` key:

```json
{
  "commands": {
    "command-name": {
      "description": "What this command does",
      "prompt": "The actual prompt text...",
      "agent": "build",
      "model": "anthropic/claude-sonnet-4-20250514",
      "tools": ["edit", "bash"]
    }
  }
}
```

## Command Fields

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Brief description of what the command does (shown in command palette) |
| `prompt` | string | The actual prompt text that guides the agent |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `agent` | string | current | Which agent to use (e.g., `build`, `plan`, custom agent name) |
| `model` | string | current | Model override (e.g., `anthropic/claude-sonnet-4-20250514`) |
| `tools` | array | all | Restrict which tools the command can use |

## Prompt Structure

### Basic Template

```json
{
  "commands": {
    "create-plan": {
      "description": "Create a detailed implementation plan for a feature",
      "prompt": "Create a detailed implementation plan for the following feature:\n\n$ARGUMENTS\n\nInclude:\n1. Requirements analysis\n2. Technical approach\n3. Step-by-step implementation tasks\n4. Testing strategy\n5. Potential risks and mitigations\n\nSave the plan to artifacts/plans/pending/",
      "agent": "plan"
    }
  }
}
```

### Using Arguments

Commands can accept arguments via `$ARGUMENTS`:

```json
{
  "commands": {
    "fix-issue": {
      "description": "Fix a specific issue by number",
      "prompt": "Fix issue #$ARGUMENTS:\n\n1. Read the issue description\n2. Understand the problem\n3. Implement the fix\n4. Add tests\n5. Verify the fix works\n\nReference the issue in your commit message.",
      "agent": "build"
    }
  }
}
```

Invoke with: `/fix-issue 123`

## Best Practices

### Description

Write clear, actionable descriptions that explain:
- **What** the command does
- **When** to use it
- **Keywords** users might search for

**Good:**
```json
"description": "Create a detailed implementation plan for a feature with requirements, technical approach, and testing strategy"
```

**Poor:**
```json
"description": "Makes a plan"
```

### Prompt Text

Follow these guidelines:

1. **Start with a clear directive**: "Create", "Fix", "Review", "Generate"
2. **Provide context**: What information does the agent need?
3. **Define the workflow**: Step-by-step instructions
4. **Specify outputs**: Where should results be saved?
5. **Include validation**: How to verify success?

### Example: Well-Structured Command

```json
{
  "commands": {
    "review-pr": {
      "description": "Review a pull request for code quality, security, and best practices",
      "prompt": "Review pull request #$ARGUMENTS:\n\n1. Fetch the PR details\n2. Read all changed files\n3. Check for:\n   - Code quality and readability\n   - Security vulnerabilities\n   - Performance issues\n   - Test coverage\n   - Documentation updates\n4. Provide specific, actionable feedback\n5. Approve or request changes with clear reasoning\n\nFocus on constructive feedback that helps improve the code.",
      "agent": "build",
      "tools": ["bash", "read"]
    }
  }
}
```

### Tool Restrictions

Limit tools to the minimum needed for the task:

```json
{
  "commands": {
    "analyze-code": {
      "description": "Analyze code structure without making changes",
      "prompt": "Analyze the codebase structure:\n\n1. Map module dependencies\n2. Identify circular dependencies\n3. Find unused code\n4. Suggest improvements\n\nDo NOT make any changes - analysis only.",
      "agent": "plan",
      "tools": ["read", "grep", "glob"]
    }
  }
}
```

### Agent Selection

Choose the appropriate agent:

- **build**: For commands that make changes (edit files, run commands)
- **plan**: For commands that analyze or plan without making changes
- **Custom agents**: For specialized tasks (e.g., `security-auditor`, `test-generator`)

### Model Selection

Override the model for specific needs:

```json
{
  "commands": {
    "quick-summary": {
      "description": "Generate a quick summary of recent changes",
      "prompt": "Summarize the recent git commits:\n\n1. Get the last 10 commits\n2. Group by theme\n3. Provide a concise summary\n\nKeep it brief and actionable.",
      "model": "anthropic/claude-haiku-4-20250514"
    }
  }
}
```

## Common Patterns

### Code Generation Command

```json
{
  "commands": {
    "generate-component": {
      "description": "Generate a new React component with tests and styles",
      "prompt": "Generate a new React component:\n\nComponent name: $ARGUMENTS\n\nCreate:\n1. Component file with TypeScript\n2. Test file with comprehensive tests\n3. Style file (CSS modules)\n4. Export from index.ts\n\nFollow the project's component structure and naming conventions.",
      "agent": "build"
    }
  }
}
```

### Debugging Command

```json
{
  "commands": {
    "debug-error": {
      "description": "Debug an error message and suggest fixes",
      "prompt": "Debug this error:\n\n$ARGUMENTS\n\n1. Analyze the error message\n2. Find where it occurs in the codebase\n3. Identify the root cause\n4. Suggest 2-3 possible fixes\n5. Recommend the best approach\n\nProvide clear, actionable steps to resolve the issue.",
      "agent": "build"
    }
  }
}
```

### Documentation Command

```json
{
  "commands": {
    "write-docs": {
      "description": "Generate documentation for a module or function",
      "prompt": "Generate documentation for: $ARGUMENTS\n\nInclude:\n1. Purpose and overview\n2. Parameters and return values\n3. Usage examples\n4. Edge cases and limitations\n5. Related functions/modules\n\nWrite in clear, concise language suitable for developers.",
      "agent": "build"
    }
  }
}
```

## Validation Checklist

Before committing a command:

- [ ] `description` clearly states purpose and use cases
- [ ] `prompt` provides clear, step-by-step instructions
- [ ] `agent` is appropriate for the task
- [ ] `tools` are restricted to minimum needed (if applicable)
- [ ] `model` is overridden only when necessary
- [ ] Arguments are used correctly (if applicable)
- [ ] Command has been tested with representative inputs
- [ ] Output location/format is specified
- [ ] Validation steps are included

## Maintenance

**Keep commands up-to-date:**

- Review when workflows change
- Update when tools are added/removed
- Adjust based on usage patterns
- Test with actual tasks

**Version control:**

- Commit command definitions to git
- Share with team via repository
- Document changes in commit messages
- Use PR reviews to validate new commands

## Advanced Patterns

### Multi-Step Workflow

```json
{
  "commands": {
    "refactor-module": {
      "description": "Refactor a module following best practices",
      "prompt": "Refactor module: $ARGUMENTS\n\nPhase 1: Analysis\n1. Read the module and all dependencies\n2. Identify code smells and issues\n3. Document current behavior\n\nPhase 2: Planning\n1. Create a refactoring plan\n2. Identify breaking changes\n3. Plan test updates\n\nPhase 3: Implementation\n1. Apply refactoring changes\n2. Update tests\n3. Update documentation\n\nPhase 4: Validation\n1. Run all tests\n2. Check for regressions\n3. Verify behavior unchanged\n\nSave plan to artifacts/plans/pending/ before starting implementation.",
      "agent": "build"
    }
  }
}
```

### Conditional Logic

```json
{
  "commands": {
    "deploy": {
      "description": "Deploy to specified environment",
      "prompt": "Deploy to environment: $ARGUMENTS\n\n1. Validate environment name (dev/staging/prod)\n2. Run pre-deployment checks:\n   - All tests pass\n   - No uncommitted changes\n   - Dependencies up to date\n3. Build the application\n4. Deploy to $ARGUMENTS\n5. Run smoke tests\n6. Report deployment status\n\nIf environment is 'prod', require explicit confirmation before proceeding.",
      "agent": "build"
    }
  }
}
```

## Troubleshooting

### Command Not Appearing

- Check JSON syntax in opencode.json
- Verify command is under `commands` key
- Restart OpenCode after adding commands

### Command Fails

- Check agent has required tool permissions
- Verify prompt syntax is correct
- Test with simple arguments first
- Check agent logs for errors

### Command Too Slow

- Consider using a faster model
- Reduce scope of the command
- Break into multiple smaller commands
- Use `plan` agent for analysis-only tasks
