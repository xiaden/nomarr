/**
 * TypeScript interfaces for Nomarr Plan structures.
 *
 * These mirror the Python dataclasses in scripts/mcp/tools/helpers/plan_md.py
 * to ensure consistent data exchange between TypeScript and Python backends.
 */
/**
 * A step within a phase of a plan.
 */
export interface Step {
    /** Step ID in P<n>-S<m> format (e.g., "P1-S3") */
    id: string;
    /** The full step text (after the checkbox) */
    text: string;
    /** Whether the step is checked/completed */
    checked: boolean;
    /** 1-based line number in the markdown file */
    lineNumber: number;
}
/**
 * A phase within a plan, containing multiple steps.
 */
export interface Phase {
    /** Phase number (1-based) */
    number: number;
    /** Phase title (e.g., "Discovery and Analysis") */
    title: string;
    /** Steps within this phase */
    steps: Step[];
    /** Phase-level properties/markers (e.g., { "Warning": "..." }) */
    properties: Record<string, string>;
}
/**
 * Annotation to add under a completed step.
 */
export interface StepAnnotation {
    /** Alphanumeric marker word (e.g., "Notes", "Warning", "Blocked") */
    marker: string;
    /** Annotation text content */
    text: string;
}
/**
 * Summary of plan progress.
 */
export interface PlanProgress {
    /** Total number of steps */
    totalSteps: number;
    /** Number of completed steps */
    completedSteps: number;
    /** Completion percentage (0-100) */
    percentage: number;
}
/**
 * Next step information returned from operations.
 */
export interface NextStepInfo {
    /** Step ID (e.g., "P2-S1") */
    id: string;
    /** Step text */
    text: string;
    /** Phase-level markers if transitioning to a new phase */
    phaseMarkers?: Record<string, string>;
}
/**
 * Phase transition information.
 */
export interface PhaseTransition {
    /** Phase we're leaving */
    from: string;
    /** Phase we're entering */
    to: string;
}
/**
 * Full plan structure.
 */
export interface Plan {
    /** Plan title (from first H1) */
    title: string;
    /** Pre-phase content sections */
    sections: Record<string, string>;
    /** All phases in the plan */
    phases: Phase[];
    /** Progress summary */
    progress: PlanProgress;
}
/**
 * Result from read_plan operation.
 */
export interface ReadPlanResult {
    plan: Plan;
    nextStep?: NextStepInfo;
}
/**
 * Result from get_steps operation.
 */
export interface GetStepsResult {
    phaseName: string;
    phaseNumber: number;
    steps: Step[];
    properties: Record<string, string>;
}
/**
 * Result from complete_step operation.
 */
export interface CompleteStepResult {
    stepId: string;
    appliedAnnotation?: StepAnnotation;
    nextStep?: NextStepInfo;
    phaseTransition?: PhaseTransition;
}
//# sourceMappingURL=plan.d.ts.map