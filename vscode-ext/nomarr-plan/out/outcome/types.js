"use strict";
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
Object.defineProperty(exports, "__esModule", { value: true });
exports.success = success;
exports.failed = failed;
exports.blocked = blocked;
exports.withTiming = withTiming;
exports.wrapOutcome = wrapOutcome;
/**
 * Create a successful outcome.
 */
function success(data, artifacts) {
    return {
        status: 'SUCCESS',
        data,
        artifacts
    };
}
/**
 * Create a failed outcome (recoverable error).
 */
function failed(category, message, details) {
    return {
        status: 'FAILED',
        failure: { category, message, details }
    };
}
/**
 * Create a blocked outcome (cannot proceed).
 */
function blocked(category, message, details) {
    return {
        status: 'BLOCKED',
        failure: { category, message, details }
    };
}
/**
 * Add timing information to an outcome.
 */
function withTiming(outcome, startedAt) {
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
async function wrapOutcome(operation, categoryOnError = 'UNKNOWN') {
    const startedAt = Date.now();
    try {
        const data = await operation();
        return withTiming(success(data), startedAt);
    }
    catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        // Determine category from error type
        let category = categoryOnError;
        if (message.includes('ENOENT') || message.includes('not found')) {
            category = 'FILE_NOT_FOUND';
        }
        else if (message.includes('timeout')) {
            category = 'TIMEOUT';
        }
        else if (message.includes('cancelled') || message.includes('canceled')) {
            category = 'CANCELLED';
        }
        return withTiming(blocked(category, message), startedAt);
    }
}
//# sourceMappingURL=types.js.map