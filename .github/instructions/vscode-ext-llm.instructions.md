---
applyTo: vscode-ext/**/src/llm/**
---

# LLM One-shot + Subagents

This folder contains the LLM integration layer for VS Code extensions. It handles one-shot calls, subagent schemas, and response validation.

## One-shot Only
- One-shot calls must not rely on conversation state.
- Always accept a CancellationToken and check it at async boundaries.

## Schema-or-Die
- Response MUST contain exactly ONE ```json block.
  - 0 blocks => FAILED(SCHEMA_INVALID)
  - >1 blocks => FAILED(SCHEMA_INVALID)
- JSON must parse and include required fields (lightweight required-fields check ok).
- Never "best-effort" repair beyond extracting the single intended block.

## Outputs
- Return deterministic structured results (prefer SubagentOutcome or `{success,data,error}`).
- Do not throw.

## Prompts
- System prompts must enforce JSON-only and forbid explanations.
- Do not change prompt templates without round-trip validation.

---

## Reference (non-prescriptive)

Key types: `vscode.lm.selectChatModels()`, `LanguageModelChat`, `LanguageModelChatMessage.User()`

### Subagent Schemas
- **Designer**: WorkOrder → DesignerOutput (touched_files, commands, changed_signatures, verification)
- **QA**: diffs + lint → QAOutput (decision: pass|fail|needs_review, commands, reasons)

### Context7 Lookup
Topics: `language model sendRequest`, `LanguageModelChatMessage`, `LanguageModelChatResponse stream`
