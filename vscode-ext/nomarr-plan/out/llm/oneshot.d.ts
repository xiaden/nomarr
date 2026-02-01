/**
 * LLM integration for one-shot subagent calls.
 *
 * These functions provide a simple interface for making single-turn LLM calls
 * with context injection and schema validation. The "schema-or-die" pattern
 * means failures are explicit - either we get valid structured output or we fail.
 */
import * as vscode from 'vscode';
/**
 * Options for one-shot LLM calls.
 */
export interface OneShotOptions {
    /** System prompt describing the task and expected output format */
    systemPrompt: string;
    /** User prompt with the actual task content */
    userPrompt: string;
    /** Files to inject into context (content will be prepended to user prompt) */
    contextFiles?: {
        path: string;
        content: string;
    }[];
    /** Maximum tokens for response */
    maxTokens?: number;
    /** Cancellation token */
    token?: vscode.CancellationToken;
}
/**
 * Result from a one-shot call.
 */
export interface OneShotResult<T> {
    success: boolean;
    data?: T;
    error?: string;
    rawResponse?: string;
}
/**
 * Select a Copilot model for use.
 *
 * @returns The first available Copilot model
 * @throws Error if no model is available
 */
export declare function selectModel(): Promise<vscode.LanguageModelChat>;
/**
 * Make a one-shot LLM call with context injection.
 *
 * This is NOT streaming - it collects the full response before returning.
 * The response is expected to be valid JSON matching the schema.
 *
 * @param options Call options including prompts and context
 * @returns Parsed response or error
 */
export declare function oneShot<T>(options: OneShotOptions): Promise<OneShotResult<T>>;
/**
 * Validate that a response matches expected schema structure.
 *
 * This is a simple runtime validation - not a full JSON Schema validator.
 * Use for quick sanity checks on required fields.
 *
 * @param data The parsed data to validate
 * @param requiredFields Array of required field names
 * @returns True if all required fields exist
 */
export declare function validateSchema<T extends object>(data: T, requiredFields: (keyof T)[]): boolean;
//# sourceMappingURL=oneshot.d.ts.map