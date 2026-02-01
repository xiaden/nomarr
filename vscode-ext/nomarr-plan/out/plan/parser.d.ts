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
import { Plan, Phase, NextStepInfo } from '../types';
/**
 * Parse plan markdown into a Plan structure.
 *
 * @param markdown Raw markdown content
 * @returns Parsed Plan with progress calculated
 */
export declare function parsePlanMarkdown(markdown: string): Plan;
/**
 * Find the next incomplete step in a plan.
 */
export declare function findNextStep(plan: Plan): NextStepInfo | undefined;
/**
 * Get steps for a specific phase by name or number.
 * If phaseName is not provided, returns the active phase (first with incomplete steps).
 */
export declare function getPhaseSteps(plan: Plan, phaseName?: string): Phase | undefined;
//# sourceMappingURL=parser.d.ts.map