---
name: opencode-plugins
description: Use when creating or updating OpenCode plugin files in .opencode/plugins/. Covers plugin structure, hook events (tool.execute.before/after, session.*, file.*, etc.), blocking operations via throw, custom tools, environment injection, and TypeScript types.
---

# OpenCode Plugins

Plugins extend OpenCode by hooking into events and customizing behavior. They provide deterministic automation: blocking dangerous operations, injecting context, adding custom tools, and logging.

---

## Plugin Locations

| Location | Scope |
|----------|-------|
| `.opencode/plugins/*.js` or `*.ts` | Project-level |
| `~/.config/opencode/plugins/*.js` or `*.ts` | Global |

Files in these directories are automatically loaded at startup.

---

## Basic Structure

```javascript
// .opencode/plugins/example.js
export const MyPlugin = async ({ project, client, $, directory, worktree }) => {
  console.log("Plugin initialized!")
  
  return {
    // Hook implementations go here
  }
}
```

The plugin function receives:
- `project`: Current project information
- `directory`: Current working directory
- `worktree`: Git worktree path
- `client`: OpenCode SDK client for AI interactions
- `$`: Bun's shell API for executing commands

---

## TypeScript Support

```typescript
import type { Plugin } from "@opencode-ai/plugin"

export const MyPlugin: Plugin = async ({ project, client, $, directory, worktree }) => {
  return {
    // Type-safe hook implementations
  }
}
```

---

## Hook Events

### Tool Events (Primary Hook Targets)

| Event | Fires when | Common uses |
|-------|------------|-------------|
| `tool.execute.before` | Before tool runs | Block dangerous ops, validate args, inject context |
| `tool.execute.after` | After tool completes | Run formatters, log results, trigger follow-up |

### Session Events

| Event | Fires when |
|-------|------------|
| `session.created` | New session starts |
| `session.compacted` | Context compaction completes |
| `session.deleted` | Session is deleted |
| `session.diff` | Diff is generated |
| `session.error` | Session encounters error |
| `session.idle` | Session becomes idle |
| `session.status` | Status changes |
| `session.updated` | Session data changes |

### File Events

| Event | Fires when |
|-------|------------|
| `file.edited` | File is modified |
| `file.watcher.updated` | File watcher state changes |

### Other Events

- `command.executed` — After command runs
- `lsp.client.diagnostics`, `lsp.updated` — LSP events
- `message.part.updated`, `message.part.removed`, `message.updated`, `message.removed` — Message events
- `permission.asked`, `permission.replied` — Permission events
- `shell.env` — Shell environment injection
- `todo.updated` — Todo list changes
- `tui.prompt.append`, `tui.command.execute`, `tui.toast.show` — TUI events

---

## Blocking Operations

To block a tool execution, **throw an error** in `tool.execute.before`:

```javascript
export const EnvProtection = async ({ project, client, $, directory, worktree }) => {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool === "read" && output.args.filePath.includes(".env")) {
        throw new Error("Do not read .env files")
      }
    },
  }
}
```

The error message is shown to the model as feedback.

---

## Tool Execute Before

Access tool name and arguments:

```javascript
"tool.execute.before": async (input, output) => {
  // input.tool — tool name (e.g., "bash", "edit", "read")
  // output.args — tool arguments (mutable)
  
  if (input.tool === "bash") {
    // Validate or modify command
    if (output.args.command.includes("rm -rf /")) {
      throw new Error("Destructive command blocked")
    }
    // Can also modify args
    output.args.command = output.args.command.replace("dangerous", "safe")
  }
}
```

---

## Tool Execute After

Access tool results:

```javascript
"tool.execute.after": async (input, output) => {
  // input.tool — tool name
  // input.result — tool execution result
  
  if (input.tool === "edit") {
    console.log(`File edited: ${input.args.filePath}`)
    // Could trigger linting, formatting, etc.
  }
}
```

---

## Environment Injection

Inject environment variables into all shell execution:

```javascript
export const InjectEnvPlugin = async () => {
  return {
    "shell.env": async (input, output) => {
      output.env.MY_API_KEY = "secret"
      output.env.PROJECT_ROOT = input.cwd
    },
  }
}
```

---

## Custom Tools

Plugins can add custom tools:

```typescript
import { type Plugin, tool } from "@opencode-ai/plugin"

export const CustomToolsPlugin: Plugin = async (ctx) => {
  return {
    tool: {
      mytool: tool({
        description: "This is a custom tool",
        args: {
          foo: tool.schema.string(),
        },
        async execute(args, context) {
          const { directory, worktree } = context
          return `Hello ${args.foo} from ${directory} (worktree: ${worktree})`
        },
      }),
    },
  }
}
```

If a plugin tool uses the same name as a built-in tool, the plugin tool takes precedence.

---

## Compaction Hooks

Customize context included when a session is compacted:

```typescript
import type { Plugin } from "@opencode-ai/plugin"

export const CompactionPlugin: Plugin = async (ctx) => {
  return {
    "experimental.session.compacting": async (input, output) => {
      // Inject additional context
      output.context.push(`## Custom Context
- Current task status
- Important decisions made
- Files being actively worked on`)
    },
  }
}
```

Or replace the compaction prompt entirely:

```typescript
"experimental.session.compacting": async (input, output) => {
  output.prompt = `You are generating a continuation prompt...`
}
```

---

## Notifications

Send notifications on events:

```javascript
export const NotificationPlugin = async ({ project, client, $, directory, worktree }) => {
  return {
    event: async ({ event }) => {
      if (event.type === "session.idle") {
        await $`osascript -e 'display notification "Session completed!" with title "opencode"'`
      }
    },
  }
}
```

---

## Dependencies

Local plugins can use external npm packages. Add a `package.json` to your config directory:

```json
// .opencode/package.json
{
  "dependencies": {
    "shescape": "^2.1.0"
  }
}
```

OpenCode runs `bun install` at startup. Your plugins can then import them:

```javascript
import { escape } from "shescape"

export const MyPlugin = async (ctx) => {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool === "bash") {
        output.args.command = escape(output.args.command)
      }
    },
  }
}
```

---

## Logging

Use `client.app.log()` for structured logging:

```typescript
export const MyPlugin = async ({ client }) => {
  await client.app.log({
    body: {
      service: "my-plugin",
      level: "info",
      message: "Plugin initialized",
      extra: { foo: "bar" },
    },
  })
}
```

Levels: `debug`, `info`, `warn`, `error`.

---

## Load Order

Plugins load in this order:
1. Global config (`~/.config/opencode/opencode.json`)
2. Project config (`opencode.json`)
3. Global plugin directory (`~/.config/opencode/plugins/`)
4. Project plugin directory (`.opencode/plugins/`)

---

## Key Differences from Copilot Hooks

| Copilot | OpenCode |
|---------|----------|
| JSON config + shell commands | JS/TS modules |
| `.github/hooks/*.json` | `.opencode/plugins/*.js` |
| `permissionDecision: deny` | `throw new Error()` |
| `PreToolUse`, `PostToolUse` | `tool.execute.before`, `tool.execute.after` |
| JSON via stdin | Context object parameter |
| Exit code semantics | Error throwing |
| `additionalContext` in stdout | Modify `output` object |

---

## Authoring Checklist

- [ ] Plugin exports a named function
- [ ] Returns object with hook implementations
- [ ] Uses `throw new Error()` to block (not return values)
- [ ] Handles errors gracefully (don't crash on unexpected input)
- [ ] Uses `client.app.log()` for debugging
- [ ] TypeScript types imported from `@opencode-ai/plugin`
- [ ] Dependencies declared in `.opencode/package.json` if needed
