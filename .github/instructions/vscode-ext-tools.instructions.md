---
applyTo: vscode-ext/**/src/tools/**
---

# LM Tools (Copilot-callable)

This folder contains LanguageModelTool implementations that Copilot Chat can invoke.

## Contract
- `invoke()` MUST NEVER throw. Wrap all logic in try/catch and return JSON on error.
- Return `LanguageModelToolResult` containing a single JSON string (pretty-print ok).

## Determinism
- Tools that modify files MUST be idempotent.
  - Calling the same tool twice with same inputs produces the same final file state.
  - Never duplicate annotations or reformat unrelated lines.

## Schema Alignment
- TypeScript input types MUST match `package.json` inputSchema (required vs optional).
- Reject missing required inputs with a structured error result (no partial behavior).

## Workspace Handling
- Resolve workspace root deterministically.
- If no workspace is open or multi-root is ambiguous, return `BLOCKED` with details.

---

## Reference (non-prescriptive)

Key types: `vscode.LanguageModelTool<T>`, `LanguageModelToolResult`, `LanguageModelTextPart`, `CancellationToken`

### Workspace Resolution
```typescript
const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
if (!workspaceFolder) return errorResult('No workspace folder open');
```

### Context7 Lookup
Topics: `LanguageModelTool interface`, `LanguageModelToolResult`, `languageModelTools contribution`
