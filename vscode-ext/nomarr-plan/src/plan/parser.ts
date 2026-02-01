/**
 * Pure functions for parsing and mutating task plan markdown files.
 * 
 * This module handles markdown mechanics only - no file I/O or async operations.
 * Port of scripts/mcp/tools/helpers/plan_md.py to TypeScript.
 * 
 * Generic markdown-to-JSON parsing:
 * - Headers create nodes keyed to their value
 * - Checkboxes become steps with id/text/done
 * - **Key:** patterns become keyed nodes (arrays if repeated)
 * - Bulleted lists become arrays
 * - Phase headers (### Phase N: Title) are collected into a phases array
 * - Raw text becomes multi-line string values
 */

import { Plan, Phase, PlanProgress, NextStepInfo } from '../types';

// --- Regex patterns (ported from Python) ---

const TITLE_PATTERN = /^#\s+(?:Task:\s*)?(.+)$/i;
const H2_PATTERN = /^##\s+(.+)$/;
const PHASE_PATTERN = /^###\s+[Pp]hase\s+(\d+)\s*[:\s]\s*(.+)$/;
const H3_PATTERN = /^###\s+(.+)$/;
const STEP_PATTERN = /^-\s*\[([ xX])\]\s+(.+)$/;
const BOLD_KEY_PATTERN = /^\*\*([a-zA-Z0-9_]+):\*\*\s*(.*)$/;
const STEP_ID_PATTERN = /^\*\*P(\d+)-S(\d+)\*\*/;

/**
 * Internal mutable plan structure during parsing.
 */
interface MutablePlan {
    title: string | null;
    sections: Record<string, string>;
    phases: MutablePhase[];
    rawLines: string[];
}

interface MutablePhase {
    number: number;
    title: string;
    steps: MutableStep[];
    properties: Record<string, string>;
    headingLine: number;
}

interface MutableStep {
    text: string;
    checked: boolean;
    lineNumber: number;
}

/**
 * Parse plan markdown into a Plan structure.
 * 
 * @param markdown Raw markdown content
 * @returns Parsed Plan with progress calculated
 */
export function parsePlanMarkdown(markdown: string): Plan {
    const lines = markdown.split(/\r?\n/);
    
    const plan: MutablePlan = {
        title: null,
        sections: {},
        phases: [],
        rawLines: lines
    };
    
    let currentSection: string | null = null;
    let currentPhase: MutablePhase | null = null;
    let contentBuffer: string[] = [];
    let targetDict: Record<string, string> = plan.sections;
    
    const flushContent = () => {
        if (contentBuffer.length === 0) {
            return;
        }
        
        const content = contentBuffer.join('\n').trim();
        if (content && currentSection && currentSection !== '__phase__') {
            plan.sections[currentSection] = content;
        }
        contentBuffer = [];
    };
    
    for (let lineNum = 0; lineNum < lines.length; lineNum++) {
        const line = lines[lineNum].trimEnd();
        
        // Title: # Task: Name
        const titleMatch = TITLE_PATTERN.exec(line);
        if (titleMatch && plan.title === null) {
            flushContent();
            plan.title = titleMatch[1].trim();
            currentSection = null;
            currentPhase = null;
            continue;
        }
        
        // Phase: ### Phase N: Title
        const phaseMatch = PHASE_PATTERN.exec(line);
        if (phaseMatch) {
            flushContent();
            const phaseNum = parseInt(phaseMatch[1], 10);
            const phaseTitle = phaseMatch[2].trim();
            currentPhase = {
                number: phaseNum,
                title: phaseTitle,
                steps: [],
                properties: {},
                headingLine: lineNum
            };
            plan.phases.push(currentPhase);
            currentSection = '__phase__';
            targetDict = currentPhase.properties;
            continue;
        }
        
        // H2: ## Section
        const h2Match = H2_PATTERN.exec(line);
        if (h2Match) {
            flushContent();
            const sectionName = h2Match[1].trim();
            currentSection = sectionName;
            currentPhase = null;
            targetDict = plan.sections;
            // Skip "Phases" header itself
            if (sectionName.toLowerCase() === 'phases') {
                currentSection = null;
            }
            continue;
        }
        
        // H3 (non-phase): ### Subsection
        const h3Match = H3_PATTERN.exec(line);
        if (h3Match && !phaseMatch) {
            flushContent();
            const sectionName = h3Match[1].trim();
            currentSection = sectionName;
            currentPhase = null;
            targetDict = plan.sections;
            continue;
        }
        
        // Step: - [x] or - [ ]
        const stepMatch = STEP_PATTERN.exec(line);
        if (stepMatch && currentPhase !== null) {
            flushContent();
            const checked = stepMatch[1].toLowerCase() === 'x';
            const text = stepMatch[2].trim();
            currentPhase.steps.push({
                text,
                checked,
                lineNumber: lineNum
            });
            continue;
        }
        
        // Bold key: **Key:** value
        const boldMatch = BOLD_KEY_PATTERN.exec(line);
        if (boldMatch) {
            flushContent();
            const key = boldMatch[1];
            const value = boldMatch[2].trim();
            if (value) {
                targetDict[key] = value;
            }
            continue;
        }
        
        // Raw text - accumulate
        if (line.trim()) {
            contentBuffer.push(line);
        }
    }
    
    flushContent();
    
    // Convert to output format with step IDs
    return convertToPlan(plan);
}

/**
 * Convert internal mutable plan to output Plan format.
 */
function convertToPlan(mplan: MutablePlan): Plan {
    const phases: Phase[] = mplan.phases.map(mp => ({
        number: mp.number,
        title: mp.title,
        steps: mp.steps.map((ms, idx) => ({
            id: extractStepId(ms.text, mp.number, idx + 1),
            text: ms.text,
            checked: ms.checked,
            lineNumber: ms.lineNumber + 1 // Convert to 1-based
        })),
        properties: mp.properties
    }));
    
    // Calculate progress
    let totalSteps = 0;
    let completedSteps = 0;
    for (const phase of phases) {
        for (const step of phase.steps) {
            totalSteps++;
            if (step.checked) {
                completedSteps++;
            }
        }
    }
    
    const progress: PlanProgress = {
        totalSteps,
        completedSteps,
        percentage: totalSteps > 0 ? Math.round((completedSteps / totalSteps) * 100) : 0
    };
    
    return {
        title: mplan.title || 'Untitled Plan',
        sections: mplan.sections,
        phases,
        progress
    };
}

/**
 * Extract step ID from step text, or generate one.
 */
function extractStepId(text: string, phaseNum: number, stepNum: number): string {
    const match = STEP_ID_PATTERN.exec(text);
    if (match) {
        return `P${match[1]}-S${match[2]}`;
    }
    return `P${phaseNum}-S${stepNum}`;
}

/**
 * Find the next incomplete step in a plan.
 */
export function findNextStep(plan: Plan): NextStepInfo | undefined {
    for (const phase of plan.phases) {
        for (const step of phase.steps) {
            if (!step.checked) {
                return {
                    id: step.id,
                    text: step.text,
                    phaseMarkers: Object.keys(phase.properties).length > 0 
                        ? phase.properties 
                        : undefined
                };
            }
        }
    }
    return undefined;
}

/**
 * Get steps for a specific phase by name or number.
 * If phaseName is not provided, returns the active phase (first with incomplete steps).
 */
export function getPhaseSteps(plan: Plan, phaseName?: string): Phase | undefined {
    if (phaseName) {
        // Match by title (partial match)
        const lower = phaseName.toLowerCase();
        return plan.phases.find(p => 
            p.title.toLowerCase().includes(lower) ||
            p.number.toString() === phaseName
        );
    }
    
    // Find active phase (first with incomplete steps)
    for (const phase of plan.phases) {
        if (phase.steps.some(s => !s.checked)) {
            return phase;
        }
    }
    
    // All complete - return last phase
    return plan.phases[plan.phases.length - 1];
}
