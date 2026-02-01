import * as vscode from 'vscode';
import { ReadPlanTool, GetStepsTool, CompleteStepTool } from './tools';

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

export function activate(context: vscode.ExtensionContext) {
    // Register LM tools FIRST - before any async or logging
    // This ensures tools are available before Copilot snapshots the tool list
    const readPlanDisposable = vscode.lm.registerTool(
        'nomarr-plan_readPlan',
        new ReadPlanTool()
    );
    
    const getStepsDisposable = vscode.lm.registerTool(
        'nomarr-plan_getSteps',
        new GetStepsTool()
    );
    
    const completeStepDisposable = vscode.lm.registerTool(
        'nomarr-plan_completeStep',
        new CompleteStepTool()
    );
    
    context.subscriptions.push(
        readPlanDisposable,
        getStepsDisposable,
        completeStepDisposable
    );
    
    // Log AFTER registration is complete
    console.log('Nomarr Plan Tools extension is now active');
    console.log('Registered 3 plan tools: readPlan, getSteps, completeStep');

    // TODO: Python backend integration in Phase 5
    // - Spawn Python subprocess
    // - JSON-RPC or stdio communication
    // - Route tool invocations to MCP server
}

export function deactivate() {
    console.log('Nomarr Plan Tools extension deactivated');
    // TODO: Cleanup Python subprocess if running
}
