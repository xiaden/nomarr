/**
 * Python MCP Server Bridge
 *
 * Spawns and communicates with the Python MCP server for tools that
 * require Python-side logic (lint_backend, lint_frontend, etc.)
 *
 * Strategy: Simple subprocess with JSON-over-stdio.
 * Each tool call spawns a fresh Python process with the tool name and args.
 * This avoids MCP protocol complexity while still leveraging Python tools.
 */
/**
 * Result from a Python tool call.
 */
export interface PythonToolResult<T = unknown> {
    success: boolean;
    data?: T;
    error?: string;
    stderr?: string;
}
/**
 * Call a Python tool via subprocess.
 *
 * This uses a simple wrapper script that:
 * 1. Imports the tool function
 * 2. Calls it with JSON args
 * 3. Prints JSON result to stdout
 *
 * @param toolName Name of the tool (e.g., 'lint_backend')
 * @param args Arguments to pass to the tool
 * @returns Tool result
 */
export declare function callPythonTool<T>(toolName: string, args: Record<string, unknown>): Promise<PythonToolResult<T>>;
/**
 * Call lint_backend Python tool.
 */
export declare function lintBackend(targetPath?: string, checkAll?: boolean): Promise<PythonToolResult<LintBackendResult>>;
/**
 * Call lint_frontend Python tool.
 */
export declare function lintFrontend(): Promise<PythonToolResult<LintFrontendResult>>;
export interface LintBackendResult {
    ruff: {
        errors: number;
        warnings: number;
        issues: Array<{
            file: string;
            line: number;
            column: number;
            code: string;
            message: string;
        }>;
    };
    mypy: {
        errors: number;
        issues: Array<{
            file: string;
            line: number;
            message: string;
        }>;
    };
    summary: {
        total_errors: number;
        total_warnings: number;
        passed: boolean;
    };
}
export interface LintFrontendResult {
    eslint: {
        errors: number;
        warnings: number;
        issues: unknown[];
    };
    typescript: {
        errors: number;
        issues: unknown[];
    };
    summary: {
        passed: boolean;
    };
}
//# sourceMappingURL=bridge.d.ts.map