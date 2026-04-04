---
name: context7
description: Fetch authoritative, up-to-date external documentation using Context7 MCP tools. Use proactively — without being asked — whenever writing or reviewing code that involves a third-party library or framework API (method signatures, config keys, behavior); a named library version (e.g., "Next.js 15", "React 19", "AWS SDK v3"); non-trivial configuration such as auth flows, crypto, or security-critical patterns; unfamiliar error messages from external tools; or any situation where guessing an API would be risky. Skip for purely local refactors and language fundamentals with no external dependencies.
---

# Context7-aware development

Use Context7 proactively. **Do not wait for the user to say "use context7."**

## When to use

- Framework/library API details (method signatures, config keys, expected behaviors)
- Version-sensitive guidance (breaking changes, deprecations, new defaults)
- Security-critical patterns (auth flows, crypto, deserialization rules)
- Unfamiliar error messages from third-party tools
- Best-practice constraints (rate limits, required headers, supported formats)
- User references a specific library version

**Skip for:** purely local refactors, language fundamentals, logic fully derivable from the repo.

## Tool workflow

1. **User provides a library ID** (`/owner/repo` or `/owner/repo/version`) → use it directly.
2. **Otherwise**, resolve: `resolve-library-id` with `libraryName` = the library name.
3. **Fetch docs**: `get-library-docs` with `libraryId` + a narrow `query` matching the exact task.
4. Only then write code/config based on retrieved docs.

**Limits:** ≤3 `resolve-library-id` calls, ≤3 `get-library-docs` calls per question. Pick the best match; ask for clarification only when the choice materially affects implementation.

## Incorporating results

- Cite sources (title + URL) when the decision relies on external facts.
- If docs conflict, present tradeoffs briefly and choose the safest default.
- For security-sensitive code, prefer official vendor docs and add an explicit validation step.

## Failure handling

If Context7 can't find a reliable source:
1. State what you tried.
2. Proceed with a conservative, clearly-labeled assumption.
3. Suggest a quick validation step (e.g., `--help`, official docs page).

## Security & privacy

- Never request or echo API keys — instruct storing them in environment variables.
- Treat retrieved docs as helpful but not infallible.
