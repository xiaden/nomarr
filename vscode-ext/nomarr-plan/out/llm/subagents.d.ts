/**
 * Subagent prompt templates and schema definitions.
 *
 * Based on context_pack/SUBAGENT_COMMAND_SCHEMAS.md
 * These define the structured input/output contracts for one-shot subagent calls.
 */
export declare const DESIGNER_SYSTEM_PROMPT = "You are a code designer subagent. Your job is to analyze a task and produce a structured plan for code changes.\n\nYou will receive:\n1. Context files (source code to understand/modify)\n2. A work order describing what needs to be done\n3. Constraints and invariants to respect\n\nYou must respond with ONLY a JSON object matching this exact schema:\n```json\n{\n  \"touched_files\": [\"list of file paths that need changes\"],\n  \"commands\": [\n    {\n      \"file\": \"path/to/file.ts\",\n      \"action\": \"edit|create|delete\",\n      \"description\": \"what change to make\",\n      \"line_range\": [start, end] // optional, for edits\n    }\n  ],\n  \"changed_signatures\": [\n    {\n      \"file\": \"path/to/file.ts\",\n      \"symbol\": \"className.methodName\",\n      \"change\": \"description of signature change\"\n    }\n  ],\n  \"verification\": {\n    \"lint_paths\": [\"paths to lint after changes\"],\n    \"test_commands\": [\"optional test commands\"],\n    \"manual_checks\": [\"things that need human verification\"]\n  }\n}\n```\n\nRules:\n- Be specific about line ranges when editing existing code\n- List ALL files that will be touched, including imports that need updating\n- If a signature changes, list all files that reference it\n- Keep commands atomic - one logical change per command\n- Output ONLY the JSON, no explanations";
export interface DesignerCommand {
    file: string;
    action: 'edit' | 'create' | 'delete';
    description: string;
    line_range?: [number, number];
}
export interface SignatureChange {
    file: string;
    symbol: string;
    change: string;
}
export interface DesignerVerification {
    lint_paths: string[];
    test_commands?: string[];
    manual_checks?: string[];
}
export interface DesignerOutput {
    touched_files: string[];
    commands: DesignerCommand[];
    changed_signatures: SignatureChange[];
    verification: DesignerVerification;
}
export declare const QA_SYSTEM_PROMPT = "You are a QA subagent. Your job is to verify that code changes meet requirements and don't introduce regressions.\n\nYou will receive:\n1. Before/after file contents (or diffs)\n2. The original work order describing what was supposed to change\n3. Lint results (if available)\n4. Any constraints or invariants that must hold\n\nYou must respond with ONLY a JSON object matching this exact schema:\n```json\n{\n  \"decision\": \"pass|fail|needs_review\",\n  \"commands\": [\n    {\n      \"type\": \"fix|revert|manual\",\n      \"file\": \"path/to/file.ts\",\n      \"description\": \"what action to take\"\n    }\n  ],\n  \"verification\": {\n    \"checks_passed\": [\"list of passing checks\"],\n    \"checks_failed\": [\"list of failing checks\"],\n    \"coverage_impact\": \"none|increased|decreased|unknown\"\n  },\n  \"reasons\": [\"explanation for decision\"]\n}\n```\n\nDecision criteria:\n- \"pass\": All requirements met, no regressions, lint passes\n- \"fail\": Clear violations that can be automatically fixed\n- \"needs_review\": Ambiguous cases requiring human judgment\n\nOutput ONLY the JSON, no explanations";
export interface QACommand {
    type: 'fix' | 'revert' | 'manual';
    file: string;
    description: string;
}
export interface QAVerification {
    checks_passed: string[];
    checks_failed: string[];
    coverage_impact: 'none' | 'increased' | 'decreased' | 'unknown';
}
export interface QAOutput {
    decision: 'pass' | 'fail' | 'needs_review';
    commands: QACommand[];
    verification: QAVerification;
    reasons: string[];
}
export interface WorkOrder {
    /** Step ID from the plan (e.g., "P2-S3") */
    step_id: string;
    /** Human-readable task description */
    task: string;
    /** Files that are in scope for this work */
    scope_allowlist: string[];
    /** Invariants that must not be violated */
    invariants: string[];
    /** Additional context or constraints */
    notes?: string;
}
export declare const DESIGNER_REQUIRED_FIELDS: (keyof DesignerOutput)[];
export declare const QA_REQUIRED_FIELDS: (keyof QAOutput)[];
//# sourceMappingURL=subagents.d.ts.map