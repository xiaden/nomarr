# Task: Break The Parser

## Problem Statement

Attempting to find cases that parse but produce wrong output.

## Phases

### Phase 1: Marker Edge Cases

- [ ] Step with **Notes:** embedded in text
- [ ] Check the **Warning:** file for details
- [ ] **Bold:** at start of step text

**Notes:**
**Warning:** Marker with nothing before it but another marker

### Phase 2: Indentation Chaos

- [ ] Step with tabs
	- tabbed bullet under step
	**Notes:** tabbed marker
- [ ] Normal step
    - 4-space bullet
      - 6-space bullet (nested?)

### Phase 3: Checkbox Variations

- [X] Uppercase X
- [x] Lowercase x
- [ ] Empty checkbox
- []No space in checkbox
- [ ]No space after checkbox
-[ ] No space before checkbox

### Phase 4: Colons Everywhere

- [ ] Remember: this has a colon
**Notes:** Important: don't forget: multiple colons: here

### Phase 5: Numbered Lists

1. First thing
2. Second thing
- [ ] Actual step after numbered list

### Phase 6: Bare Bullets at Step Level

- Bare bullet that should fail
- Another bare bullet
- [ ] Valid step for comparison

### Phase 7: Extra Spaces in Checkbox

- [x ] Extra space after x
- [  ] Two spaces inside

### Phase 8: Wrong Bullet Markers

* [ ] Asterisk checkbox
+ [ ] Plus checkbox
* [x] Completed asterisk
- [ ] Valid step for comparison

## Completion Criteria

- Find something broken
