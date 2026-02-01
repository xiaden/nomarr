"use strict";
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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const tools_1 = require("./tools");
/**
 * Nomarr Plan Tools Extension
 *
 * Provides VS Code Language Model Tools for plan management:
 * - readPlan: Parse and return structured plan data
 * - getSteps: Get steps for a specific phase
 * - completeStep: Mark a step as complete
 *
 * These tools integrate with Copilot Chat to enable plan-aware agentic workflows.
 */
function activate(context) {
    // Register LM tools FIRST - before any async or logging
    // This ensures tools are available before Copilot snapshots the tool list
    const readPlanDisposable = vscode.lm.registerTool('nomarr-plan_readPlan', new tools_1.ReadPlanTool());
    const getStepsDisposable = vscode.lm.registerTool('nomarr-plan_getSteps', new tools_1.GetStepsTool());
    const completeStepDisposable = vscode.lm.registerTool('nomarr-plan_completeStep', new tools_1.CompleteStepTool());
    context.subscriptions.push(readPlanDisposable, getStepsDisposable, completeStepDisposable);
    // Log AFTER registration is complete
    console.log('Nomarr Plan Tools extension is now active');
    console.log('Registered 3 plan tools: readPlan, getSteps, completeStep');
    // TODO: Python backend integration in Phase 5
    // - Spawn Python subprocess
    // - JSON-RPC or stdio communication
    // - Route tool invocations to MCP server
}
function deactivate() {
    console.log('Nomarr Plan Tools extension deactivated');
    // TODO: Cleanup Python subprocess if running
}
//# sourceMappingURL=extension.js.map