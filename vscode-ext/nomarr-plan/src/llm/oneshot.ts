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
    contextFiles?: { path: string; content: string }[];
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
export async function selectModel(): Promise<vscode.LanguageModelChat> {
    const models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
    
    if (models.length === 0) {
        throw new Error('No Copilot language model available. Ensure GitHub Copilot is installed and signed in.');
    }
    
    // Prefer Claude if available, otherwise take first available
    const claudeModel = models.find(m => m.family.toLowerCase().includes('claude'));
    return claudeModel || models[0];
}

/**
 * Make a one-shot LLM call with context injection.
 * 
 * This is NOT streaming - it collects the full response before returning.
 * The response is expected to be valid JSON matching the schema.
 * 
 * @param options Call options including prompts and context
 * @returns Parsed response or error
 */
export async function oneShot<T>(options: OneShotOptions): Promise<OneShotResult<T>> {
    try {
        const model = await selectModel();
        
        // Build user message with injected context
        let userContent = '';
        
        if (options.contextFiles && options.contextFiles.length > 0) {
            userContent += '## Context Files\n\n';
            for (const file of options.contextFiles) {
                userContent += `### ${file.path}\n\`\`\`\n${file.content}\n\`\`\`\n\n`;
            }
            userContent += '---\n\n';
        }
        
        userContent += options.userPrompt;
        
        // Build messages
        const messages: vscode.LanguageModelChatMessage[] = [
            vscode.LanguageModelChatMessage.User(options.systemPrompt),
            vscode.LanguageModelChatMessage.User(userContent)
        ];
        
        // Make request
        const requestOptions: vscode.LanguageModelChatRequestOptions = {
            justification: 'Nomarr Plan Tools - One-shot subagent call'
        };
        
        const response = await model.sendRequest(
            messages,
            requestOptions,
            options.token || new vscode.CancellationTokenSource().token
        );
        
        // Collect full response (non-streaming)
        let responseText = '';
        for await (const chunk of response.text) {
            responseText += chunk;
        }
        
        // Extract JSON from response - enforce exactly one code block
        const jsonBlocks = responseText.match(/```(?:json)?\s*([\s\S]*?)\s*```/g);
        
        let jsonText: string;
        if (jsonBlocks && jsonBlocks.length === 1) {
            // Exactly one block - extract content
            const match = responseText.match(/```(?:json)?\s*([\s\S]*?)\s*```/);
            jsonText = match ? match[1].trim() : '';
        } else if (jsonBlocks && jsonBlocks.length > 1) {
            // Multiple blocks - ambiguous, fail
            return {
                success: false,
                error: `Ambiguous response: found ${jsonBlocks.length} JSON blocks, expected exactly 1`,
                rawResponse: responseText
            };
        } else {
            // No code blocks - try parsing raw response as JSON
            jsonText = responseText.trim();
            // But only if it looks like JSON
            if (!jsonText.startsWith('{') && !jsonText.startsWith('[')) {
                return {
                    success: false,
                    error: 'No JSON code block found in response',
                    rawResponse: responseText
                };
            }
        }
        
        // Parse as JSON
        try {
            const data = JSON.parse(jsonText) as T;
            return { success: true, data, rawResponse: responseText };
        } catch (parseError) {
            return {
                success: false,
                error: `Failed to parse response as JSON: ${parseError instanceof Error ? parseError.message : String(parseError)}`,
                rawResponse: responseText
            };
        }
        
    } catch (error) {
        return {
            success: false,
            error: error instanceof Error ? error.message : String(error)
        };
    }
}

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
export function validateSchema<T extends object>(data: T, requiredFields: (keyof T)[]): boolean {
    for (const field of requiredFields) {
        if (!(field in data) || data[field] === undefined) {
            return false;
        }
    }
    return true;
}
