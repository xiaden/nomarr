# Task: Edge Case Testing

## Problem Statement

This plan tests edge cases that are schema-valid but potentially weird parser behavior.

## Random Section Before Phases

Some projects might have arbitrary sections before phases. This should become a top-level key.

## Phases

### Phase 1: Indented Bullets as Annotations

- [ ] This is a proper step
  - This is an indented bullet under the step (annotation)
  - Another indented bullet
- [ ] Another proper step

Some raw text after steps but before annotations.

**Notes:** Phase-level annotation after raw text.
**bullets:**
    - Phase-level bullet via marker
    - Another phase-level bullet

### Phase 2: Previously Empty

- [ ] Added a step so this phase is valid

### Phase 3: Mixed Content

Random text at the start of a phase.

- [ ] Step after raw text
- [ ] Step with **bold** and `code` in text
- [ ] Step with: colons in text

More random text between steps.

- [ ] Final step

**CustomMarker:** Testing arbitrary annotation markers work.
**Another:** Multiple annotations on same phase.

### Phase 4: Minimal Phase

- [ ] Only one step, no annotations

## Section After Phases

Content after all phases should also become a top-level key.

With multiple paragraphs.

And bullet points:
- Item one
- Item two

## Completion Criteria

- This plan parses without error
- Edge cases are handled gracefully
