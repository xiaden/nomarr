---
name: subsystem-orientation
description: Create a subsystem orientation skill after deep research on a stable, non-churning part of the codebase when no skill exists for it. Use when you have just read many files, traced call chains, or explored architecture to understand how a subsystem works — and that knowledge should be captured to prevent the same context burn on every future session touching that area. Triggers include: had to explore 5+ files to understand one concept, traced IPC/process/worker/pipeline topology manually, or answered "how does X actually work" from scratch.
---

# Subsystem Orientation Skill Creator

You have just done expensive research on a stable subsystem. Capture the mental model now — once — rather than rediscovering it every session.

## Check Before Creating

**Before creating a new skill, check if one already exists** for this subsystem. Skills live in `.github/skills/` and `code-intel/skills/`. If a skill exists:
- **Extend it** with what you just learned — do not create a duplicate
- Update the `## Coverage` section (see below)
- If you learned something that contradicts the skill, fix the skill and note the change

A partial skill that labels its gaps is always preferable to no skill. A partial skill with *unlabeled* gaps causes confident wrong reasoning — worse than no skill.

## What Belongs in a Subsystem Orientation Skill

A subsystem skill answers: **"What does a competent engineer need to know before touching this area?"**

**Include:**
- The intended mental model — why this architecture, not just what it does
- Process/thread/IPC topology (who owns what, how parts communicate)
- Key invariants an agent must not violate
- Which files are canonical owners of each concern
- How the subsystem connects to the rest of the system (entry/exit points)
- Citations to the ADRs/DDs that motivated the design

**Do not include:**
- Implementation details that change with normal refactors (method signatures, variable names)
- Information already obvious from reading one file
- Anything the model already knows (Python stdlib, FastAPI patterns, etc.)
- Episodic history ("we tried X and it failed") — that belongs in logs/ADRs

## The Test

If an agent reads all the files in the subsystem but still doesn't know *why* it's structured this way or *what would break* if they changed it naively — the gap belongs in a skill.

## Structure

Place Nomarr subsystem skills in `.github/skills/{subsystem-name}/SKILL.md`.
Place generic/tooling skills in `code-intel/skills/{skill-name}/SKILL.md`.

```
.github/skills/my-subsystem/
├── SKILL.md                  ← required: frontmatter + summary + key files table
└── references/
    └── architecture.md       ← optional: full topology, schema, invariants if large
```

Keep `SKILL.md` scannable — if the mental model needs more than ~60 lines, move the detail to `references/architecture.md` and link it (see `nomarr-tags` skill as reference implementation).

## Frontmatter Discipline

The `description` field is the trigger selector. It must:
- Name the subsystem explicitly (agents match on nouns)
- List the *tasks* that should load it, not just the domain
- Be specific enough that it doesn't load for every session

**Good:**
```yaml
description: Use when working with the discovery worker system — process isolation,
  ML job dispatch, IPC pipe protocol, worker lifecycle, or BaseWorker subclassing.
  Also covers how the service connects to workers and handles worker crashes.
```

**Bad:**
```yaml
description: Use when working with workers or ML.
```

## Required Sections in the Skill Body

1. **One-paragraph mental model** — the "explain it to a new hire in 60 seconds" summary
2. **Coverage** — formal declaration of what this skill documents and what it does not (see format below)
3. **Key Files table** — area → canonical file, no descriptions, just the map
4. **Critical Invariants** — the things an agent must never break, stated as constraints
5. **Common Task Patterns** (optional) — if there are 2-3 stereotyped tasks that are easy to get wrong

## Coverage Section Format

Every subsystem skill **must** include a `## Coverage` section immediately after the mental model. This is the staleness and incompleteness signal for future agents.

```markdown
## Coverage

**Documented:** worker IPC protocol, pipe lifecycle, BaseWorker subclassing, service ↔ worker connection setup

**Not yet documented:** worker crash recovery, GPU memory limits, multi-worker scheduling policy

**Last extended:** 2026-06-03
```

Rules:
- `Documented` lists the specific concerns this skill covers — not the subsystem name, the *concerns*
- `Not yet documented` lists known gaps — areas that exist in the subsystem but weren't researched yet
- `Last extended` is the ISO date the skill was last written or extended
- When extending a skill, move items from `Not yet documented` to `Documented` as appropriate, and add new gaps discovered
- If `Not yet documented` is empty, write `none known` — do not omit the field

## Source Citations

Every skill must cite its authoritative sources. Include at the bottom:

```
## Sources
- ADR-NNN: Title
- DD: slug (artifacts/designs/...)
```

If no ADR/DD exists for the design decision, that's a gap worth noting — the skill can serve as informal documentation until a proper ADR is written.

## Staleness Contract

A skill is a *view* over ADRs/DDs. When the underlying design changes:
- The ADR supersession and the skill update must be in the same commit
- If the skill becomes stale, it causes confident wrong reasoning — worse than no skill
- Add a `## Sources` section so future maintainers know which ADRs to check

## Reference Implementation

`nomarr-tags` (`d:\Github\nomarr\.github\skills\nomarr-tags\SKILL.md`) is the canonical example. Note: concise SKILL.md body, detailed content in `references/`, explicit key files table, invariants called out.
