# Agent Skills Specification

Reference: https://agentskills.io/specification

Agent Skills are folders of instructions, scripts, and resources that agents can discover and use to perform tasks more accurately and efficiently.

---

## Directory Structure

A skill is a directory containing at minimum a `SKILL.md` file:

```
skill-name/
├── SKILL.md          # Required
├── scripts/          # Optional: executable code
├── references/       # Optional: additional documentation
└── assets/           # Optional: templates, data files
```

---

## SKILL.md Format

The `SKILL.md` file must contain YAML frontmatter followed by Markdown content.

### Frontmatter (Required)

```yaml
---
name: skill-name
description: A description of what this skill does and when to use it.
---
```

With optional fields:

```yaml
---
name: pdf-processing
description: Extract text and tables from PDF files, fill forms, merge documents.
license: Apache-2.0
compatibility: Requires git, docker
metadata:
  author: example-org
  version: "1.0"
allowed-tools: Bash(git:*) Read
---
```

### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Max 64 characters. Lowercase letters, numbers, and hyphens only. Must not start or end with a hyphen. **Must match parent directory name.** |
| `description` | Yes | Max 1024 characters. Non-empty. Describes what the skill does and when to use it. |
| `license` | No | License name or reference to a bundled license file. |
| `compatibility` | No | Max 500 characters. Environment requirements (system packages, network access, etc.). |
| `metadata` | No | Arbitrary key-value mapping for additional metadata. |
| `allowed-tools` | No | Space-delimited list of pre-approved tools. (Experimental) |

### Name Field Rules

- Must be 1-64 characters
- May only contain lowercase alphanumeric characters and hyphens (`a-z`, `0-9`, `-`)
- Must not start or end with `-`
- Must not contain consecutive hyphens (`--`)
- **Must match the parent directory name**

Valid:
```yaml
name: pdf-processing
name: data-analysis
name: code-review
```

Invalid:
```yaml
name: PDF-Processing  # uppercase not allowed
name: -pdf            # cannot start with hyphen
name: pdf--processing # consecutive hyphens not allowed
```

### Description Field Guidelines

- Must be 1-1024 characters
- Should describe both what the skill does AND when to use it
- Should include specific keywords that help agents identify relevant tasks

Good:
```yaml
description: Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.
```

Poor:
```yaml
description: Helps with PDFs.
```

---

## Body Content

The Markdown body after the frontmatter contains the skill instructions. Write clear, specific instructions that describe:

- What the skill helps accomplish
- When to use the skill
- Step-by-step procedures to follow
- Examples of inputs and outputs
- Common edge cases

**Recommended sections:**
- Step-by-step instructions
- Examples of inputs and outputs
- Common edge cases
- References to included scripts or resources

---

## Optional Directories

### scripts/

Contains executable code that agents can run. Scripts should:
- Be self-contained or clearly document dependencies
- Include helpful error messages
- Handle edge cases gracefully

### references/

Contains additional documentation that agents can read when needed:
- `REFERENCE.md` - Detailed technical reference
- Domain-specific files (`api.md`, `patterns.md`, etc.)

Keep individual reference files focused. Agents load these on demand.

### assets/

Contains static resources:
- Templates (document templates, configuration templates)
- Data files (lookup tables, schemas)

---

## Progressive Disclosure

Skills should be structured for efficient context usage:

1. **Metadata (~100 tokens)**: `name` and `description` loaded at startup for all skills
2. **Instructions (< 5000 tokens recommended)**: Full `SKILL.md` body loaded when activated
3. **Resources (as needed)**: Files in `scripts/`, `references/`, `assets/` loaded only when required

**Keep your main `SKILL.md` under 500 lines.** Move detailed reference material to separate files.

---

## File References

When referencing other files in your skill, use relative paths from the skill root:

```markdown
See [the reference guide](references/REFERENCE.md) for details.

Run the extraction script:
scripts/extract.py
```

Keep file references one level deep from `SKILL.md`. Avoid deeply nested reference chains.

---

## Portability

Agent Skills is an open standard that works across multiple agents:

- GitHub Copilot in VS Code
- GitHub Copilot CLI
- GitHub Copilot coding agent
- Claude Code
- Cursor
- And others

Skills created in one environment work across all skills-compatible agents.

---

## Validation

Use the skills-ref library to validate skills:

```bash
skills-ref validate ./my-skill
```

This checks that `SKILL.md` frontmatter is valid and follows all naming conventions.

---

## References

- Specification: https://agentskills.io/specification
- VS Code docs: https://code.visualstudio.com/docs/copilot/customization/agent-skills
- Example skills: https://github.com/anthropics/skills
- Community skills: https://github.com/github/awesome-copilot
