# ADR-009: nom: Tag Prefix Exclusion from User Editing

**Status:** Accepted  
**Date:** 2026-04-04  
**Tags:** architecture, ml, tag-editor, invariant  
**Source Log:** rnd-manager#L1  

## Context

ML-generated tags use a `nom:` prefix convention (e.g., `nom:genre`, `nom:mood-score`). These tags are produced by the ML inference pipeline (ONNX models) and represent machine-derived classifications.\n\nAllowing users to edit `nom:` tags would:\n- Corrupt model outputs, making ML results unreliable\n- Create confusion between human-curated and machine-generated tags\n- Undermine any future model retraining that relies on `nom:` tag consistency\n\nThe system needs a clear, enforceable boundary between user-editable tags and ML-owned tags.

## Decision

Enforce `nom:` tag immutability at three layers:\n\n1. **Frontend:** Render `nom:` columns with grey background and no cell editor. Users cannot click to edit.\n2. **Service:** `LibraryTagEditMixin` raises `ValueError("Cannot modify ML-generated tags (nom: prefix)")` for any write operation targeting a `nom:` rel.\n3. **Persistence:** Debug assertion `assert not rel.startswith("nom:")` in tag write methods as a safety net.\n\nThis is a defense-in-depth strategy. The frontend prevents casual attempts, the service provides the authoritative guard, and the persistence assertion catches programming errors.

## Consequences

**Positive:**\n- ML tag integrity guaranteed at every layer\n- Clear visual distinction in UI between editable and read-only tags\n- Defense-in-depth prevents bugs from silently corrupting ML data\n\n**Negative:**\n- Users cannot correct ML misclassifications through the Tag Editor (must wait for model improvements or a future "override" mechanism)\n- Three-layer enforcement adds implementation surface\n\n**Future consideration:**\n- A "user override" mechanism could allow users to shadow `nom:` tags with user-prefixed equivalents (e.g., `user:genre` overrides `nom:genre` for display) without modifying the ML tag itself.

## References

DD-tag-editor.md
