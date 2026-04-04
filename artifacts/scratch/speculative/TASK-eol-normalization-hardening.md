# Task: EOL Normalization Hardening for mcp_code_intel

## Problem Statement

The mcp_code_intel file edit tools perform EOL detection and normalization to handle cross-platform line ending differences (\r\n, \n, \r). Current implementation has four critical risks that can cause non-deterministic behavior and matching failures:

1. **No "majority EOL" algorithm exists** - Current `detect_eol` uses "first found" logic (checks \r\n, then \n, then \r). This creates ambiguity in mixed-EOL files and doesn't meet the documented intent of "majority detection."

2. **Coordinate space inconsistency** - Not all tools operate in the same normalized representation. If match decisions happen pre-normalization but replacements happen post-normalization (or vice versa), range calculations become incorrect.

3. **Unspecified no-EOL file behavior** - Files without line endings (single-line files) have undefined normalization behavior. When input text contains EOLs but target file doesn't, current behavior may unintentionally introduce line endings.

4. **Line count validation depends on normalization order** - If `expected_line_count` or `expected_content` validation happens before normalization, but the tool operates on normalized content, counts diverge and cause spurious failures.

These issues create "It matched but replaced the wrong span" or "No match even though it should" bugs under load, particularly with mixed-EOL files or when called from different contexts.

## Phases

### Phase 1: Implement Deterministic Majority EOL Detection

- [ ] Replace `detect_eol` in file_helpers.py with count-based majority algorithm
- [ ] Implement tie-breaker rule (prefer \r\n > \n > \r for stability)
- [ ] Add explicit handling for zero-newline files (return \n as default)
- [ ] Document algorithm contract in function docstring
- [ ] Create unit tests for majority detection edge cases

### Phase 2: Audit Tool Coordinate Space Usage

- [ ] Document each edit tool's normalization phase and coordinate space
- [ ] Verify read_raw_lines and read_raw_line_range preserve exact bytes
- [ ] Audit all tools using normalize_eol to confirm pre-match normalization
- [ ] Identify any tools performing late normalization (after matching)
- [ ] Create coordinate space invariant documentation

### Phase 3: Implement No-EOL File Safeguards

- [ ] Add no_eol detection flag to read_file_with_metadata return value
- [ ] Update normalize_eol to accept optional preserve_no_eol parameter
- [ ] Add warnings when tools introduce EOLs into newline-free files
- [ ] Document no-EOL behavior policy in file_helpers.py
- [ ] Add test cases for single-line file operations

### Phase 4: Fix Line Count Validation Ordering

- [ ] Audit all uses of expected_content and expected_line_count
- [ ] Ensure validation happens AFTER normalization in all tools
- [ ] Update edit_file_replace_line_range.py validation logic
- [ ] Document validation ordering requirement in tool docstrings
- [ ] Add test for mixed-EOL file with expected_content verification

### Phase 5: Comprehensive Testing and Validation

- [ ] Create test suite with mixed-EOL files (close-to-even distribution)
- [ ] Add tie-case tests (equal counts of \r\n and \n)
- [ ] Test no-newline files with various input patterns
- [ ] Test input boundaries containing \n while file is \r\n
- [ ] Verify all file edit tools pass new test suite
- [ ] Run lint_project_backend on code-intel/src/mcp_code_intel
- [ ] Update .github/instructions/code-intel.instructions.md with EOL contract

## Completion Criteria

- All edit tools use single canonical `detect_eol` with documented majority algorithm
- Zero edit tools perform coordinate calculations or matching in different normalization states
- No-EOL file behavior is explicitly documented and tested
- All validation (expected_content, expected_line_count) happens in normalized space
- Test suite covers all four identified risk scenarios
- lint_project_backend passes with zero errors
- EOL normalization contract is documented in layer instructions

## References

- Current implementation: [file_helpers.py](code-intel/src/mcp_code_intel/helpers/file_helpers.py)
- Current line reading: [file_lines.py](code-intel/src/mcp_code_intel/helpers/file_lines.py)
- Affected tools: edit_file_replace_string.py, edit_file_move_text.py, edit_file_replace_line_range.py
- User-identified risks: See creation context for detailed risk analysis
