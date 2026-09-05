# Skills Archive

## Purpose

This directory holds **superseded** project skills removed from the active skill
directory. It is **NON-DISCOVERABLE historical material** — neither OpenCode nor
any skill loader, validator, or migration tool scans or loads skills from here.

## Active skills

Only `.opencode/skills/<skill-name>/SKILL.md` is active and discoverable. That
directory is the single source of truth for project skills; its sorted contents
are the live inventory (see `scripts/human-scripts/validate_skills.py`).

Archived skills are retained here solely for reference/audit history. They are
**not** loaded, validated, or referenced as loadable skills anywhere.

## Archive policy

- Move/removal date: **2026-09-04** (branch `feat/develop-branch-migration`).
- Any future skill archived here **must** be excluded from active validation
  (`validate_skills.py` / `check_migration.py` scan `.opencode/skills`, so a
  move here already excludes it) and from any loader configuration.
- Do not leave an active duplicate beside an archived skill.

## Archived skills

The following superseded active skills were moved here in hard-cut fashion (full
directory contents preserved):

| Archived skill | Superseded by | Archived SKILL.md |
| -------------- | ------------- | ----------------- |
| `subsystem-orientation` | Global skill `capture-subsystem` (`~/.config/opencode/skills/capture-subsystem/`) | `subsystem-orientation/SKILL.md` |
| `scan-lifecycle` | Canonical active project skill `library-scan-lifecycle` (`.opencode/skills/library-scan-lifecycle/SKILL.md`) | `scan-lifecycle/SKILL.md` |
| `code-discovery` | AFT indexed discovery/callgraph toolset (`aft_search` / `aft_outline` / `aft_zoom` / `aft_callgraph` / `aft_inspect`); supporting scripts remain live under `scripts/human-scripts/` | `code-discovery/SKILL.md` |

## Retained/archived split

As of **2026-09-04**: **37 retained active skills, 3 archived** (40 audited
skills minus the 3 archived candidates). Each archived directory contains its
`SKILL.md` (and any `references/` files it had) moved verbatim via plain `mv`.
