---
name: Instruction Files
description: Guidelines for creating and maintaining .instructions.md files for GitHub Copilot customization
applyTo: .github/instructions/**/*.instructions.md
---

# Instruction Files for GitHub Copilot

**Purpose:** Define context-specific guidance for GitHub Copilot to ensure consistent, architecture-aware code generation and assistance.

Instructions files customize how Copilot behaves when working with specific files, patterns, or tasks in your workspace.

---

## File Structure

All instruction files must:
- Use `.instructions.md` extension
- Be stored in `.github/instructions/` (workspace-level)
- Follow Markdown format with optional YAML frontmatter

### YAML Frontmatter (Header)

Optional but recommended. Defines metadata and automatic application rules:

```yaml
---
name: Display Name
description: Brief explanation of what these instructions cover
applyTo: glob/pattern/**/*.ext
---
```

**Fields:**
- `name`: Human-readable name displayed in VS Code UI (defaults to filename if omitted)
- `description`: Short summary of the instructions' purpose
- `applyTo`: Glob pattern for automatic application (e.g., `**/*.py`, `nomarr/services/**`)
  - If omitted, instructions are only applied when manually attached
  - Use `**` to apply globally across all files
  - Multiple patterns: `**/*.ts,**/*.tsx`

### Body (Markdown Content)

The instructions themselves. Should contain:
- Clear, specific guidelines Copilot should follow
- Architecture rules or constraints
- Naming conventions
- Code patterns to use or avoid
- References to other files or tools

**Syntax for referencing agent tools:**
```markdown
#tool:githubRepo
#tool:search/codebase
```

---

## Best Practices

### Keep Instructions Focused

- **One topic per file** - Don't mix unrelated concerns
- **Short and specific** - Each statement should be a single, clear directive
- **Self-contained** - Assume Copilot has no prior context

### Use Multiple Files for Specificity

Instead of one massive instructions file:
- Create layer-specific files (services, workflows, components)
- Create language-specific files (Python, TypeScript, etc.)
- Create task-specific files (testing, documentation, etc.)

### Leverage Glob Patterns

Use `applyTo` to automatically apply instructions when editing relevant files:

```yaml
# Python-specific
applyTo: "**/*.py"

# Layer-specific  
applyTo: "nomarr/services/**"

# Documentation
applyTo: "docs/**/*.md"

# Multiple patterns
applyTo: "**/*.ts,**/*.tsx"
```

### Reference, Don't Duplicate

Use Markdown links to reference other instruction files:

```markdown
Apply the [general coding guidelines](./general-coding.instructions.md).

For database access, see [persistence layer guidelines](./persistence.instructions.md).
```

This avoids duplication and ensures consistency.

### Structure for Readability

Use headings, lists, and code blocks:

```markdown
## Naming Conventions
- Use `PascalCase` for class names
- Use `snake_case` for function names
- Suffix services with `Service`

## Error Handling
- Never use bare `except:`
- Always log exceptions with context
- Use custom exception types from `nomarr/helpers/exceptions.py`

## Example
\`\`\`python
class DataProcessorService:
    def process(self, data: DataModel) -> Result:
        try:
            return self._transform(data)
        except ValidationError as e:
            logger.error("Validation failed", extra={"data": data})
            raise
\`\`\`
```

---

## Testing Instructions Files

Use VS Code's built-in testing:

1. Open Chat view
2. Click gear icon → **Configure Chat** → **Chat Instructions**
3. Verify your instructions file appears
4. Attach it manually to test: **Add Context** → **Instructions** → select your file
5. Ask Copilot to generate code matching your patterns

---

## Common Patterns

### Layer-Specific (Architecture Enforcement)

```yaml
---
name: Services Layer
description: DI wiring, orchestration, worker processes
applyTo: nomarr/services/**
---

# Services Layer Rules

Services are:
- Dependency coordinators (wire config, DB, backends)
- Thin orchestrators (call workflows, aggregate results)
- DTO providers (shape data for interfaces)

**No complex business logic.** That belongs in workflows.

## Allowed Imports
- `nomarr.workflows.*`
- `nomarr.helpers.*`
- Standard library

## Forbidden Imports
- Never import from `nomarr.interfaces`
- Never import from `nomarr.components`
```

### Language-Specific (Coding Standards)

```yaml
---
name: Python Standards
description: Project-wide Python coding guidelines
applyTo: "**/*.py"
---

# Python Coding Standards

- Follow PEP 8 style guide
- Use type hints for all function signatures
- Prefer `pathlib.Path` over `os.path`
- Use `ruff` for linting and formatting
- Write docstrings for all public functions/classes
```

### Documentation Style

```yaml
---
name: Documentation Guidelines
description: Writing standards for Markdown documentation
applyTo: "docs/**/*.md"
---

# Documentation Style Guide

## Voice and Tense
- Use present tense ("is", "does") not past tense
- Use active voice where subject performs action
- Write in second person ("you") to address readers
- Avoid hypotheticals ("could", "would")

## Formatting
- Use ATX-style headings (`#`, `##`, `###`)
- Use fenced code blocks with language identifiers
- Include concrete examples
- Link to related resources
```

---

## Nomarr-Specific Patterns

### Reference Copilot Instructions

Always cross-reference the main Copilot instructions:

```markdown
Follow the general architecture rules in [copilot-instructions.md](../.github/copilot-instructions.md).
```

### Reference Layer Skills

When instructions apply to a specific architectural layer:

```markdown
See the comprehensive layer documentation: [layer-services/SKILL.md](../skills/layer-services/SKILL.md)

**YOU MUST** run the validation script after changes:
\`\`\`bash
python .github/skills/layer-services/scripts/check_naming.py
\`\`\`
```

### Enforce Dependency Direction

```markdown
## Dependency Flow

```
interfaces → services → workflows → components → (persistence / helpers)
```

**This file must only import:**
- Lower layers (workflows, helpers)
- Standard library
- Third-party packages

**Never import:**
- Higher layers (services, interfaces)
```

---

## When NOT to Use Instruction Files

Avoid instruction files for:
- One-off tasks or temporary project-specific notes
- Complex procedural knowledge better suited for documentation
- Highly dynamic rules that change frequently
- Information already covered by linters, type checkers, or CI

Instead:
- Use linters/formatters for style enforcement
- Use documentation for architecture explanations
- Use code comments for implementation-specific notes
- Use CI/CD checks for validation rules

---

## Maintenance

**Keep instructions up-to-date:**
- Review when architectural patterns change
- Update when naming conventions evolve
- Remove obsolete or contradictory rules
- Test with actual Copilot interactions

**Version control:**
- Commit instruction files to git
- Share workspace instructions with team
- Document changes in commit messages
- Use PR reviews to validate new/changed instructions

---

## Summary Checklist

Before committing an instruction file:

- [ ] Uses `.instructions.md` extension
- [ ] Has clear, specific YAML frontmatter (if needed)
- [ ] Uses appropriate `applyTo` glob pattern
- [ ] Contains focused, actionable directives
- [ ] Uses Markdown headings, lists, and code blocks
- [ ] References other files instead of duplicating
- [ ] Tested with Copilot Chat
- [ ] Follows Nomarr's architectural principles
- [ ] Cross-references relevant skills/documentation
