/**
 * Subagent outcome types and failure handling.
 *
 * Outcomes are deterministic:
 * - SUCCESS: Task completed, validation passed
 * - FAILED: Task attempted but validation failed (schema invalid, lint errors)
 * - BLOCKED: Cannot proceed (missing files, Python error, model unavailable)
 *
 * No retries at this layer - that's for the orchestrator to decide.
 */
/**
 * Outcome status for subagent operations.
 */
export type OutcomeStatus = 'SUCCESS' | 'FAILED' | 'BLOCKED';
/**
 * Failure category for diagnostics.
 */
export type FailureCategory = 'SCHEMA_INVALID' | 'LINT_FAILED' | 'MODEL_UNAVAILABLE' | 'PYTHON_ERROR' | 'FILE_NOT_FOUND' | 'PARSE_ERROR' | 'TIMEOUT' | 'CANCELLED' | 'UNKNOWN';
/**
 * Structured outcome from a subagent operation.
 */
export interface SubagentOutcome<T = unknown> {
    /** Result status */
    status: OutcomeStatus;
    /** Payload on success */
    data?: T;
    /** Failure details */
    failure?: {
        category: FailureCategory;
        message: string;
        details?: Record<string, unknown>;
    };
    /** Timing info */
    timing?: {
        startedAt: number;
        completedAt: number;
        durationMs: number;
    };
    /** Artifacts produced (file paths, etc.) */
    artifacts?: string[];
}
/**
 * Create a successful outcome.
 */
export declare function success<T>(data: T, artifacts?: string[]): SubagentOutcome<T>;
/**
 * Create a failed outcome (recoverable error).
 */
export declare function failed(category: FailureCategory, message: string, details?: Record<string, unknown>): SubagentOutcome<never>;
/**
 * Create a blocked outcome (cannot proceed).
 */
export declare function blocked(category: FailureCategory, message: string, details?: Record<string, unknown>): SubagentOutcome<never>;
/**
 * Add timing information to an outcome.
 */
export declare function withTiming<T>(outcome: SubagentOutcome<T>, startedAt: number): SubagentOutcome<T>;
/**
 * Wrap an async operation with outcome handling.
 *
 * Catches errors and converts them to appropriate outcomes.
 */
export declare function wrapOutcome<T>(operation: () => Promise<T>, categoryOnError?: FailureCategory): Promise<SubagentOutcome<T>>;
//# sourceMappingURL=types.d.ts.map