# ADR-002: Normalize all code-intel file reads to LF-only

**Status:** Accepted  
**Date:** 2026-04-03  
**Tags:** code-intel, eol, normalization, windows, convention  

## Context

Multiple code-intel tools used `content.split("\n")` to process file and user content without stripping `\r`. On Windows, files with CRLF line endings (`\r\n`) caused: markdown parser failures (ADR, DD, log, plan parsers produced corrupted output), content boundary mismatches (matching failed when `\r` was embedded in boundary strings), and data corruption in insert/replace tools (CRLF bytes leaked into reassembled output). The `atomic_write()` helper already normalizes to `\n` on the write side, but the read side had 10 separate entry points that did not normalize.

## Decision

All file content and user-provided content entering the code-intel tool pipeline is normalized to LF-only (`\n`) at entry points, before any `split("\n")` or line processing. The normalization pattern is: `text = text.replace("\r\n", "\n").replace("\r", "\n")`. This is applied once per entry point (parser function top, content handler entry) — not at every split call. The `eol` field in `read_file_with_metadata()` is preserved as diagnostic information (detected from raw bytes before normalization) but nothing branches on it for behavior.

## Consequences

**Positive:** Eliminates the entire class of CRLF bugs across all tools. No tool ever sees `\r`. One-line pattern at each entry point — minimal code, maximal coverage. Write side (`atomic_write`) already did this; now read side matches. **Negative:** Files with intentional `\r` (not `\r\n`) lose that byte. This is acceptable — no source code or markdown uses bare `\r`, and these tools are for text, not binary. **Convention:** Any new parser or content handler in code-intel must normalize input at its entry point before splitting on `"\n"`.

## References

Plan: TASK-code-intel-eol-normalization.md\nDesign: DD-code-intel-tool-fixes-v1.md
