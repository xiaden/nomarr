import { type Plugin, tool } from "@opencode-ai/plugin"
import path from "path"

type ToolArgs = Record<string, unknown>
type ToolContext = {
  directory?: string
  [key: string]: unknown
}

function workspaceRoot(context: ToolContext): string {
  if (typeof context.directory === "string" && context.directory.length > 0) {
    return context.directory
  }
  return process.cwd()
}

function optionalString(description: string) {
  return tool.schema.string().optional().describe(description)
}

function requiredString(description: string) {
  return tool.schema.string().describe(description)
}

function requiredNumber(description: string) {
  return tool.schema.number().describe(description)
}

function optionalNumber(description: string) {
  return tool.schema.number().optional().describe(description)
}

function optionalBoolean(description: string) {
  return tool.schema.boolean().optional().describe(description)
}

function optionalStringArray(description: string) {
  return tool.schema.array(tool.schema.string()).optional().describe(description)
}

// ── Runner ───────────────────────────────────────────────────────────────────

async function runPythonTool(
  moduleName: string,
  args: ToolArgs,
  context: ToolContext,
  toolsDir: string,
) {
  const input = JSON.stringify({
    ...args,
    workspace_root: workspaceRoot(context),
  })

  const pythonExecutable = path.join(
    workspaceRoot(context),
    process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python",
  )

  const proc = Bun.spawn({
    cmd: [pythonExecutable, "-m", moduleName],
    cwd: toolsDir,
    stdin: "pipe",
    stdout: "pipe",
    stderr: "pipe",
  })

  proc.stdin.write(input)
  proc.stdin.end()

  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ])

  const trimmedStdout = stdout.trim()
  const trimmedStderr = stderr.trim()

  if (exitCode !== 0) {
    throw new Error(
      `[${moduleName}] exited with code ${exitCode}: ${trimmedStderr || trimmedStdout || "no output"}`,
    )
  }

  if (!trimmedStdout) {
    throw new Error(`[${moduleName}] returned no stdout`)
  }

  let result: unknown
  try {
    result = JSON.parse(trimmedStdout)
  } catch (error) {
    throw new Error(
      `[${moduleName}] invalid JSON: ${error instanceof Error ? error.message : String(error)}`,
    )
  }

  if (result && typeof result === "object" && "error" in result) {
    const err = result as { error: string; message?: string }
    // Some tools return partial results alongside an error — still return the raw output
  }

  // If the Python tool already returns { output, title, metadata }, use it directly
  if (result && typeof result === "object" && "output" in result) {
    const r = result as { output: unknown; title?: string; metadata?: Record<string, unknown> }
    return {
      output: typeof r.output === "string" ? r.output : JSON.stringify(r.output),
      title: r.title ?? "",
      metadata: r.metadata ?? {},
    }
  }

  // Fallback: raw JSON (should not be reached for properly configured tools)
  return {
    output: typeof result === "string" ? result : JSON.stringify(result, null, 2),
    title: moduleName.split(".").pop() ?? moduleName,
    metadata: {},
  }
}

// ── Plugin ───────────────────────────────────────────────────────────────────

export const NomarrToolsPlugin: Plugin = async ({ directory }) => {
  const toolsDir = path.join(directory, ".opencode", "tools")

  return {
    tool: {
      // ── Code Navigation ──────────────────────────────────────────────────

      read_module_api: tool({
        description:
          "Discover the entire API of any Python module. Uses pure static AST parsing (no code execution). " +
          "Returns structured JSON with classes, functions, constants, methods, fields, and docstrings.",
        args: {
          module_name: requiredString(
            "Fully qualified module name (e.g., 'nomarr.components.ml.genre')",
          ),
          include_docstrings: optionalBoolean("Include full docstrings in output (default: true)"),
          include_inherited: optionalBoolean(
            "Include methods from base classes/mixins (default: true)",
          ),
        },
        async execute(args: ToolArgs, context: ToolContext) {
          return runPythonTool("common.tools.read_module_api", args, context, toolsDir)
        },
      }),

      read_module_source: tool({
        description:
          "Get source code of a Python function, method, or class by import path. " +
          "Uses static AST parsing (no code execution). Returns symbol with context lines " +
          "plus exact symbol boundaries for precise replacements.",
        args: {
          qualified_name: optionalString(
            "Dotted Python import path, e.g. 'nomarr.persistence.db.Database.close'. " +
              "Mutually exclusive with file_path+symbol.",
          ),
          file_path: optionalString(
            "Workspace-relative or absolute file path, e.g. 'nomarr/persistence/db.py'. " +
              "Must be paired with 'symbol'.",
          ),
          symbol: optionalString(
            "Dotted symbol name within the file, e.g. 'Database.close'. " +
              "Only valid alongside file_path.",
          ),
          large_context: optionalBoolean(
            "If true, include 10 lines context (default: 2 lines)",
          ),
        },
        async execute(args: ToolArgs, context: ToolContext) {
          return runPythonTool("common.tools.read_module_source", args, context, toolsDir)
        },
      }),

      read_file_symbol_at_line: tool({
        description:
          "Get full function/method/class containing a line for contextual understanding. " +
          "Use when you have a line number from an error, search result, or stack trace.",
        args: {
          file_path: requiredString("Absolute or relative path to Python file"),
          line_number: requiredNumber("Line number (1-indexed) from error message or trace"),
        },
        async execute(args: ToolArgs, context: ToolContext) {
          return runPythonTool("common.tools.read_file_symbol_at_line", args, context, toolsDir)
        },
      }),

      // ── Linting ───────────────────────────────────────────────────────────

      lint_project_backend: tool({
        description:
          "Run backend linting tools on specified path. " +
          "Runs ruff (check + fix + format), mypy, import-linter, and pytest. " +
          "By default, only lints git-modified and untracked files.",
        args: {
          path: optionalString(
            "Relative path to lint (e.g., 'nomarr/services'). Default: nomarr/",
          ),
          check_all: optionalBoolean(
            "If true, lint ALL files in path. If false (default), only modified/untracked files.",
          ),
        },
        async execute(args: ToolArgs, context: ToolContext) {
          return runPythonTool("common.tools.lint_project_backend", args, context, toolsDir)
        },
      }),

      lint_project_frontend: tool({
        description:
          "Run frontend linting tools (ESLint, TypeScript type checking, and Vitest). " +
          "Returns structured JSON with errors or clean status.",
        args: {},
        async execute(args: ToolArgs, context: ToolContext) {
          return runPythonTool("common.tools.lint_project_frontend", args, context, toolsDir)
        },
      }),

      // ── Introspection ─────────────────────────────────────────────────────

      py_introspect: tool({
        description:
          "Run whitelist-only Python introspection checks in an isolated subprocess. " +
          "Safe: no arbitrary code execution, hard timeout, no network, no filesystem writes. " +
          "Supports: mro, issubclass, signature, doc, getsource_contains, ast_raises.",
        args: {
          imports: optionalStringArray(
            "Extra dotted imports to execute before checks (e.g. ['nomarr.services'])",
          ),
          checks: tool.schema
            .array(tool.schema.object({}))
            .describe(
              "List of check specs. Each has a 'check' key " +
                "(mro|issubclass|signature|doc|getsource_contains|ast_raises) plus check-specific fields.",
            ),
          timeout_ms: optionalNumber("Hard timeout in milliseconds (500-30000, default: 3000)"),
          max_source_chars: optionalNumber(
            "Max characters for source-text results (100-50000, default: 2000)",
          ),
        },
        async execute(args: ToolArgs, context: ToolContext) {
          return runPythonTool("common.tools.py_introspect", args, context, toolsDir)
        },
      }),
    },
  }
}
