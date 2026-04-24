# ADR-029: Adopt GitFlow-lite branching strategy

**Status:** Accepted  
**Date:** 2026-04-24  
**Tags:** git, branching, workflow, process  
**Source Log:** agent#L24  

## Context

Prior to this decision, all development work happened directly on a single `develop` branch with no enforced structure. This led to messy commit history (fixup commits, debug commits, and incomplete work all interleaved), no clear stability tiers, and no gate before changes reached `main`. The branch itself carried 71 commits of mixed-quality work before this pattern was recognised as a problem.

## Decision

Adopt a three-tier GitFlow-lite branching strategy:

**Tiers:**
- `feat/*`, `fix/*`, `chore/*` branches — short-lived, spawned from `develop`. Work happens here. Commits can be messy, broken, or iterative. Merged into `develop` via PR with squash merge.
- `develop` — integration branch. Receives PRs from feature branches. Should be working at every commit but not necessarily fully tested. Protected: no direct push, PR required. Merged into `main` via PR.
- `main` — stable, versioned releases only. One PR per version bump. Fully tested and known working. Protected: no direct push, PR required.

**Merge strategy:**
- Feature → develop: squash merge (one clean commit per feature in develop history)
- Develop → main: merge commit (preserves which features composed the version)

**Branch naming:** `feat/`, `fix/`, `chore/` prefixes with a short kebab-case description.

**Branch protection:** Both `develop` and `main` are protected on GitHub with PR-only merge enforcement.

## Consequences

**Positive:**
- `develop` and `main` histories become meaningful and readable
- Incomplete or experimental work is isolated to feature branches
- PRs provide a natural review gate and a squash point for messy commit trails
- Clear stability contract per tier: feature=messy, develop=working, main=stable

**Negative:**
- Slightly more ceremony per change (branch, push, open PR)
- Solo developer bears full PR overhead with no reviewer benefit until team grows

**Neutral:**
- Existing work in progress must live on feature branches; `develop` starts clean from `main`
- The first migration PR (`feat/develop-branch-migration`) establishes the pattern
