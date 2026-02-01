"use strict";
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
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.callPythonTool = callPythonTool;
exports.lintBackend = lintBackend;
exports.lintFrontend = lintFrontend;
const vscode = __importStar(require("vscode"));
const child_process_1 = require("child_process");
const path = __importStar(require("path"));
/**
 * Get Python bridge configuration.
 */
function getConfig() {
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
async function callPythonTool(toolName, args) {
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
        const proc = (0, child_process_1.spawn)(config.pythonPath, ['-c', pythonCode], {
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
            }
            catch (parseError) {
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
async function lintBackend(targetPath, checkAll = false) {
    return callPythonTool('lint_backend', {
        path: targetPath,
        check_all: checkAll
    });
}
/**
 * Call lint_frontend Python tool.
 */
async function lintFrontend() {
    return callPythonTool('lint_frontend', {});
}
//# sourceMappingURL=bridge.js.map