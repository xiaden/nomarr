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

import * as vscode from 'vscode';
import { spawn } from 'child_process';
import * as path from 'path';

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
 * Configuration for the Python bridge.
 */
interface PythonBridgeConfig {
    /** Path to Python executable (defaults to 'python' or '.venv/Scripts/python') */
    pythonPath: string;
    /** Path to the workspace root */
    workspaceRoot: string;
    /** Environment variables to pass */
    env: NodeJS.ProcessEnv;
}

/**
 * Get Python bridge configuration.
 */
function getConfig(): PythonBridgeConfig {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        throw new Error('No workspace folder open');
    }
    
    const workspaceRoot = workspaceFolder.uri.fsPath;
    
    // Check for venv
    const venvPython = path.join(workspaceRoot, '.venv', 'Scripts', 'python.exe');
    const pythonPath = venvPython; // Assume venv exists in Nomarr
    
    return {
        pythonPath,
        workspaceRoot,
        env: {
            ...process.env,
            PYTHONPATH: workspaceRoot
        }
    };
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
export async function callPythonTool<T>(
    toolName: string,
    args: Record<string, unknown>
): Promise<PythonToolResult<T>> {
    const config = getConfig();
    
    // Python one-liner to call the tool
    const pythonCode = `
import json
import sys
sys.path.insert(0, '${config.workspaceRoot.replace(/\\/g, '\\\\')}')

try:
    from scripts.mcp.tools.${toolName} import ${toolName}
    result = ${toolName}(**${JSON.stringify(args)})
    print(json.dumps({"success": True, "data": result}))
except Exception as e:
    print(json.dumps({"success": False, "error": str(e)}))
`.trim();
    
    return new Promise((resolve) => {
        const proc = spawn(config.pythonPath, ['-c', pythonCode], {
            cwd: config.workspaceRoot,
            env: config.env
        });
        
        let stdout = '';
        let stderr = '';
        
        proc.stdout.on('data', (data) => {
            stdout += data.toString();
        });
        
        proc.stderr.on('data', (data) => {
            stderr += data.toString();
        });
        
        proc.on('close', (code) => {
            if (code !== 0 && !stdout) {
                resolve({
                    success: false,
                    error: `Python process exited with code ${code}`,
                    stderr
                });
                return;
            }
            
            try {
                // Find the last JSON line (ignore any debug output)
                const lines = stdout.trim().split('\n');
                const jsonLine = lines.filter(l => l.startsWith('{')).pop();
                
                if (!jsonLine) {
                    resolve({
                        success: false,
                        error: 'No JSON output from Python',
                        stderr
                    });
                    return;
                }
                
                const result = JSON.parse(jsonLine);
                resolve({
                    ...result,
                    stderr: stderr || undefined
                });
            } catch (parseError) {
                resolve({
                    success: false,
                    error: `Failed to parse Python output: ${parseError}`,
                    stderr
                });
            }
        });
        
        proc.on('error', (err) => {
            resolve({
                success: false,
                error: `Failed to spawn Python: ${err.message}`
            });
        });
    });
}

/**
 * Call lint_backend Python tool.
 */
export async function lintBackend(
    targetPath?: string,
    checkAll: boolean = false
): Promise<PythonToolResult<LintBackendResult>> {
    return callPythonTool<LintBackendResult>('lint_backend', {
        path: targetPath,
        check_all: checkAll
    });
}

/**
 * Call lint_frontend Python tool.
 */
export async function lintFrontend(): Promise<PythonToolResult<LintFrontendResult>> {
    return callPythonTool<LintFrontendResult>('lint_frontend', {});
}

// --- Result types from Python tools ---

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
