/**
 * VS Code Language Model Tool implementations for plan operations.
 * 
 * These tools are registered with vscode.lm.registerTool() and become
 * available to Copilot Chat and other LLM consumers.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs/promises';
import { parsePlanMarkdown, findNextStep, getPhaseSteps } from '../plan';
import { ReadPlanResult, GetStepsResult, CompleteStepResult, StepAnnotation } from '../types';

// Default plans directory relative to workspace
const PLANS_DIR = 'docs/dev/plans';

/**
 * Get the plans directory path.
 */
function getPlansDir(): string {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        throw new Error('No workspace folder open');
    }
    return path.join(workspaceFolder.uri.fsPath, PLANS_DIR);
}

/**
 * Normalize plan name to include .md extension.
 */
function normalizePlanName(planName: string): string {
    if (planName.endsWith('.md')) {
        return planName;
    }
    return `${planName}.md`;
}

/**
 * Read plan file content.
 */
async function readPlanFile(planName: string): Promise<string> {
    const plansDir = getPlansDir();
    const filePath = path.join(plansDir, normalizePlanName(planName));
    return fs.readFile(filePath, 'utf-8');
}

/**
 * Write plan file content.
 */
async function writePlanFile(planName: string, content: string): Promise<void> {
    const plansDir = getPlansDir();
    const filePath = path.join(plansDir, normalizePlanName(planName));
    await fs.writeFile(filePath, content, 'utf-8');
}

// --- Tool Input Types ---

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

// --- Tool Implementations ---

/**
 * Read Plan Tool Implementation
 */
export class ReadPlanTool implements vscode.LanguageModelTool<ReadPlanInput> {
    
    async invoke(
        options: vscode.LanguageModelToolInvocationOptions<ReadPlanInput>,
        _token: vscode.CancellationToken
    ): Promise<vscode.LanguageModelToolResult> {
        try {
            const { plan_name } = options.input;
            const content = await readPlanFile(plan_name);
            const plan = parsePlanMarkdown(content);
            const nextStep = findNextStep(plan);
            
            const result: ReadPlanResult = {
                plan,
                nextStep
            };
            
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify(result, null, 2))
            ]);
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify({ error: message }))
            ]);
        }
    }
}

/**
 * Get Steps Tool Implementation
 */
export class GetStepsTool implements vscode.LanguageModelTool<GetStepsInput> {
    
    async invoke(
        options: vscode.LanguageModelToolInvocationOptions<GetStepsInput>,
        _token: vscode.CancellationToken
    ): Promise<vscode.LanguageModelToolResult> {
        try {
            const { plan_name, phase_name } = options.input;
            const content = await readPlanFile(plan_name);
            const plan = parsePlanMarkdown(content);
            const phase = getPhaseSteps(plan, phase_name);
            
            if (!phase) {
                return new vscode.LanguageModelToolResult([
                    new vscode.LanguageModelTextPart(JSON.stringify({ 
                        error: `Phase not found: ${phase_name || '(active phase)'}` 
                    }))
                ]);
            }
            
            const result: GetStepsResult = {
                phaseName: phase.title,
                phaseNumber: phase.number,
                steps: phase.steps,
                properties: phase.properties
            };
            
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify(result, null, 2))
            ]);
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify({ error: message }))
            ]);
        }
    }
}

/**
 * Complete Step Tool Implementation
 */
export class CompleteStepTool implements vscode.LanguageModelTool<CompleteStepInput> {
    
    async invoke(
        options: vscode.LanguageModelToolInvocationOptions<CompleteStepInput>,
        _token: vscode.CancellationToken
    ): Promise<vscode.LanguageModelToolResult> {
        try {
            const { plan_name, step_id, annotation } = options.input;
            const content = await readPlanFile(plan_name);
            const lines = content.split(/\r?\n/);
            
            // Parse to find the step
            const plan = parsePlanMarkdown(content);
            let targetStep: { lineNumber: number; text: string } | undefined;
            let currentPhaseTitle: string | undefined;
            let nextPhaseTitle: string | undefined;
            
            // Find the step by ID
            for (let i = 0; i < plan.phases.length; i++) {
                const phase = plan.phases[i];
                for (const step of phase.steps) {
                    if (step.id === step_id) {
                        targetStep = { lineNumber: step.lineNumber, text: step.text };
                        currentPhaseTitle = phase.title;
                        // Check if this is last step in phase
                        if (step === phase.steps[phase.steps.length - 1] && i + 1 < plan.phases.length) {
                            nextPhaseTitle = plan.phases[i + 1].title;
                        }
                    }
                    if (targetStep) {
                        break;
                    }
                }
                if (targetStep) {
                    break;
                }
            }
            
            if (!targetStep) {
                return new vscode.LanguageModelToolResult([
                    new vscode.LanguageModelTextPart(JSON.stringify({ 
                        error: `Step not found: ${step_id}` 
                    }))
                ]);
            }
            
            // Update the line to mark as checked (idempotent - only if unchecked)
            const lineIdx = targetStep.lineNumber - 1; // Convert to 0-based
            const line = lines[lineIdx];
            const wasAlreadyChecked = !line.includes('- [ ]');
            const updatedLine = line.replace(/- \[ \]/, '- [x]');
            lines[lineIdx] = updatedLine;
            
            // Insert annotation if provided AND step wasn't already checked
            // This ensures idempotency - calling twice won't duplicate annotations
            if (annotation && !wasAlreadyChecked) {
                const annotationLine = `  > **${annotation.marker}:** ${annotation.text}`;
                lines.splice(lineIdx + 1, 0, annotationLine);
            }
            
            // Only write back if something changed
            if (!wasAlreadyChecked) {
                const newContent = lines.join('\n');
                await writePlanFile(plan_name, newContent);
            }
            
            // Re-parse to get next step (use current content, whether modified or not)
            const currentContent = wasAlreadyChecked ? content : lines.join('\n');
            const updatedPlan = parsePlanMarkdown(currentContent);
            const nextStep = findNextStep(updatedPlan);
            
            const result: CompleteStepResult = {
                stepId: step_id,
                appliedAnnotation: wasAlreadyChecked ? undefined : annotation,
                nextStep,
                phaseTransition: nextPhaseTitle ? {
                    from: currentPhaseTitle!,
                    to: nextPhaseTitle
                } : undefined
            };
            
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify(result, null, 2))
            ]);
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify({ error: message }))
            ]);
        }
    }
}
