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
export type FailureCategory = 
    | 'SCHEMA_INVALID'      // LLM output didn't match expected schema
    | 'LINT_FAILED'         // Code changes broke lint
    | 'MODEL_UNAVAILABLE'   // No LLM model available
    | 'PYTHON_ERROR'        // Python subprocess failed
    | 'FILE_NOT_FOUND'      // Required file doesn't exist
    | 'PARSE_ERROR'         // Couldn't parse plan/file
    | 'TIMEOUT'             // Operation timed out
    | 'CANCELLED'           // User/token cancelled
    | 'UNKNOWN';            // Unexpected error

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
export function success<T>(data: T, artifacts?: string[]): SubagentOutcome<T> {
    return {
        status: 'SUCCESS',
        data,
        artifacts
    };
}

/**
 * Create a failed outcome (recoverable error).
 */
export function failed(
    category: FailureCategory,
    message: string,
    details?: Record<string, unknown>
): SubagentOutcome<never> {
    return {
        status: 'FAILED',
        failure: { category, message, details }
    };
}

/**
 * Create a blocked outcome (cannot proceed).
 */
export function blocked(
    category: FailureCategory,
    message: string,
    details?: Record<string, unknown>
): SubagentOutcome<never> {
    return {
        status: 'BLOCKED',
        failure: { category, message, details }
    };
}

/**
 * Add timing information to an outcome.
 */
export function withTiming<T>(
    outcome: SubagentOutcome<T>,
    startedAt: number
): SubagentOutcome<T> {
    const completedAt = Date.now();
    return {
        ...outcome,
        timing: {
            startedAt,
            completedAt,
            durationMs: completedAt - startedAt
        }
    };
}

/**
 * Wrap an async operation with outcome handling.
 * 
 * Catches errors and converts them to appropriate outcomes.
 */
export async function wrapOutcome<T>(
    operation: () => Promise<T>,
    categoryOnError: FailureCategory = 'UNKNOWN'
): Promise<SubagentOutcome<T>> {
    const startedAt = Date.now();
    
    try {
        const data = await operation();
        return withTiming(success(data), startedAt);
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        
        // Determine category from error type
        let category = categoryOnError;
        if (message.includes('ENOENT') || message.includes('not found')) {
            category = 'FILE_NOT_FOUND';
        } else if (message.includes('timeout')) {
            category = 'TIMEOUT';
        } else if (message.includes('cancelled') || message.includes('canceled')) {
            category = 'CANCELLED';
        }
        
        return withTiming(blocked(category, message), startedAt);
    }
}
