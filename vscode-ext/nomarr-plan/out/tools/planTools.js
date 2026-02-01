"use strict";
/**
 * VS Code Language Model Tool implementations for plan operations.
 *
 * These tools are registered with vscode.lm.registerTool() and become
 * available to Copilot Chat and other LLM consumers.
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
exports.CompleteStepTool = exports.GetStepsTool = exports.ReadPlanTool = void 0;
const vscode = __importStar(require("vscode"));
const path = __importStar(require("path"));
const fs = __importStar(require("fs/promises"));
const plan_1 = require("../plan");
// Default plans directory relative to workspace
const PLANS_DIR = 'docs/dev/plans';
/**
 * Get the plans directory path.
 */
function getPlansDir() {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        throw new Error('No workspace folder open');
    }
    return path.join(workspaceFolder.uri.fsPath, PLANS_DIR);
}
/**
 * Normalize plan name to include .md extension.
 */
function normalizePlanName(planName) {
    if (planName.endsWith('.md')) {
        return planName;
    }
    return `${planName}.md`;
}
/**
 * Read plan file content.
 */
async function readPlanFile(planName) {
    const plansDir = getPlansDir();
    const filePath = path.join(plansDir, normalizePlanName(planName));
    return fs.readFile(filePath, 'utf-8');
}
/**
 * Write plan file content.
 */
async function writePlanFile(planName, content) {
    const plansDir = getPlansDir();
    const filePath = path.join(plansDir, normalizePlanName(planName));
    await fs.writeFile(filePath, content, 'utf-8');
}
// --- Tool Implementations ---
/**
 * Read Plan Tool Implementation
 */
class ReadPlanTool {
    async invoke(options, _token) {
        try {
            const { plan_name } = options.input;
            const content = await readPlanFile(plan_name);
            const plan = (0, plan_1.parsePlanMarkdown)(content);
            const nextStep = (0, plan_1.findNextStep)(plan);
            const result = {
                plan,
                nextStep
            };
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify(result, null, 2))
            ]);
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify({ error: message }))
            ]);
        }
    }
}
exports.ReadPlanTool = ReadPlanTool;
/**
 * Get Steps Tool Implementation
 */
class GetStepsTool {
    async invoke(options, _token) {
        try {
            const { plan_name, phase_name } = options.input;
            const content = await readPlanFile(plan_name);
            const plan = (0, plan_1.parsePlanMarkdown)(content);
            const phase = (0, plan_1.getPhaseSteps)(plan, phase_name);
            if (!phase) {
                return new vscode.LanguageModelToolResult([
                    new vscode.LanguageModelTextPart(JSON.stringify({
                        error: `Phase not found: ${phase_name || '(active phase)'}`
                    }))
                ]);
            }
            const result = {
                phaseName: phase.title,
                phaseNumber: phase.number,
                steps: phase.steps,
                properties: phase.properties
            };
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify(result, null, 2))
            ]);
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify({ error: message }))
            ]);
        }
    }
}
exports.GetStepsTool = GetStepsTool;
/**
 * Complete Step Tool Implementation
 */
class CompleteStepTool {
    async invoke(options, _token) {
        try {
            const { plan_name, step_id, annotation } = options.input;
            const content = await readPlanFile(plan_name);
            const lines = content.split(/\r?\n/);
            // Parse to find the step
            const plan = (0, plan_1.parsePlanMarkdown)(content);
            let targetStep;
            let currentPhaseTitle;
            let nextPhaseTitle;
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
            const updatedPlan = (0, plan_1.parsePlanMarkdown)(currentContent);
            const nextStep = (0, plan_1.findNextStep)(updatedPlan);
            const result = {
                stepId: step_id,
                appliedAnnotation: wasAlreadyChecked ? undefined : annotation,
                nextStep,
                phaseTransition: nextPhaseTitle ? {
                    from: currentPhaseTitle,
                    to: nextPhaseTitle
                } : undefined
            };
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify(result, null, 2))
            ]);
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            return new vscode.LanguageModelToolResult([
                new vscode.LanguageModelTextPart(JSON.stringify({ error: message }))
            ]);
        }
    }
}
exports.CompleteStepTool = CompleteStepTool;
//# sourceMappingURL=planTools.js.map