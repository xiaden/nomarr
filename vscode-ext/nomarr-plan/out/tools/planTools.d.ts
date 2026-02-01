/**
 * VS Code Language Model Tool implementations for plan operations.
 *
 * These tools are registered with vscode.lm.registerTool() and become
 * available to Copilot Chat and other LLM consumers.
 */
import * as vscode from 'vscode';
import { StepAnnotation } from '../types';
interface ReadPlanInput {
    plan_name: string;
}
interface GetStepsInput {
    plan_name: string;
    phase_name?: string;
}
interface CompleteStepInput {
    plan_name: string;
    step_id: string;
    annotation?: StepAnnotation;
}
/**
 * Read Plan Tool Implementation
 */
export declare class ReadPlanTool implements vscode.LanguageModelTool<ReadPlanInput> {
    invoke(options: vscode.LanguageModelToolInvocationOptions<ReadPlanInput>, _token: vscode.CancellationToken): Promise<vscode.LanguageModelToolResult>;
}
/**
 * Get Steps Tool Implementation
 */
export declare class GetStepsTool implements vscode.LanguageModelTool<GetStepsInput> {
    invoke(options: vscode.LanguageModelToolInvocationOptions<GetStepsInput>, _token: vscode.CancellationToken): Promise<vscode.LanguageModelToolResult>;
}
/**
 * Complete Step Tool Implementation
 */
export declare class CompleteStepTool implements vscode.LanguageModelTool<CompleteStepInput> {
    invoke(options: vscode.LanguageModelToolInvocationOptions<CompleteStepInput>, _token: vscode.CancellationToken): Promise<vscode.LanguageModelToolResult>;
}
export {};
//# sourceMappingURL=planTools.d.ts.map