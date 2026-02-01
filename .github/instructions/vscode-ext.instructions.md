---
applyTo: vscode-ext/**
---

# VS Code Extension Rules (Nomarr)

You are working in a VS Code extension running in the Extension Host.

## Non-negotiables
- Do NOT guess VS Code API behavior. If unsure, use Context7 docs.
- Keep changes scoped to `vscode-ext/**` unless explicitly directed.
- Prefer deterministic behavior over "helpful" heuristics.

## LM Tool Requirements
- LM tools MUST be registered synchronously in `activate()` (before any async work or logging).
- Activation MUST include `onLanguageModelTool:<toolName>` for each tool.
- Tool name strings MUST exactly match `package.json` contributes.languageModelTools[].name.

## Error Discipline
- Never throw from LM tool `invoke()`; always return structured JSON.
- `BLOCKED` / `FAILED` are discovered outcomes; do not encode anticipated blocks.

## Output Expectation
- Changes must compile and lint: `npm run compile && npm run lint`.

---

## Reference (non-prescriptive)

### Context7 Lookup
```
mcp_context7_get-library-docs("/websites/code_visualstudio_api", "<topic>", 10000)
```
Topics: `language model tools`, `chat participant`, `activation events`, `language model chat`

### Model Selection
```typescript
// Always handle empty model list
const models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
if (models.length === 0) {
    return { error: 'No model available' };
}
const model = models[0];
```

### Chat Messages
```typescript
// User and Assistant message creation
const messages = [
    vscode.LanguageModelChatMessage.User(systemPrompt),
    vscode.LanguageModelChatMessage.User(userContent)
];
```

### Response Streaming
```typescript
// Collect full response (non-streaming)
let text = '';
for await (const chunk of response.text) {
    text += chunk;
}

// Or stream parts
for await (const chunk of response.stream) {
    if (chunk instanceof vscode.LanguageModelTextPart) {
        // Handle text
    } else if (chunk instanceof vscode.LanguageModelToolCallPart) {
        // Handle tool call
    }
}
```

## Debugging Checklist

1. ☐ Activation events include `onLanguageModelTool:tool-name`
2. ☐ Tool registered synchronously in activate()
3. ☐ No throws escape from invoke()
4. ☐ inputSchema matches TypeScript interface
5. ☐ Extension enabled in Extension Development Host (F5)
