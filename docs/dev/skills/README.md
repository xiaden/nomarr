# Agent Skills Documentation

This directory contains documentation for the Agent Skills system used to customize GitHub Copilot behavior in Nomarr.

## Contents

- [specification.md](specification.md) - The Agent Skills format specification
- [nomarr-skills.md](nomarr-skills.md) - Nomarr-specific skill conventions

## Quick Reference

Skills are stored in `.github/skills/<skill-name>/SKILL.md`.

```
.github/skills/
├── layer-helpers/
│   └── SKILL.md
├── layer-components/
│   └── SKILL.md
├── layer-workflows/
│   └── SKILL.md
└── ...
```

## How Skills Work

1. **Discovery**: Copilot reads `name` and `description` from frontmatter (~100 tokens)
2. **Activation**: When request matches description, full `SKILL.md` body loads
3. **Resources**: Additional files in skill directory load only when referenced

## Creating a New Skill

```markdown
---
name: my-skill
description: Use when [trigger conditions]. Provides [capabilities].
---

# Skill Title

Instructions, examples, and guidelines...
```

See [specification.md](specification.md) for complete format requirements.
