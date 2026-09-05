# Agent Skills Documentation

This directory contains documentation for the Agent Skills system used to customize agent behavior in Nomarr.

## Contents

- [specification.md](specification.md) — The Agent Skills format specification
- [nomarr-skills.md](nomarr-skills.md) — Nomarr-specific skill conventions and inventory

## Quick Reference

Skills are stored in `.opencode/skills/<skill-name>/SKILL.md`. This is the single
active project skill directory — the directory the validator scans and agents
discover skills from.

```
.opencode/skills/
├── <skill-name>/SKILL.md   # each skill is one directory with a SKILL.md
├── <skill-name>/references/  # optional supplementary files loaded on demand
└── ...
```

The live inventory is the sorted set of skill directories currently under
`.opencode/skills/`. Run the validator to list and check them:

```bash
python scripts/human-scripts/validate_skills.py
```

## How Skills Work

1. **Discovery**: The agent runtime reads `name` and `description` from frontmatter (~100 tokens)
2. **Activation**: When a task matches the description, the full `SKILL.md` body loads
3. **Resources**: Additional files in the skill directory load only when referenced

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
