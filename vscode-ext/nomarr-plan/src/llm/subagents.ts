/**
 * Subagent prompt templates and schema definitions.
 * 
 * Based on context_pack/SUBAGENT_COMMAND_SCHEMAS.md
 * These define the structured input/output contracts for one-shot subagent calls.
 */

// --- Designer Subagent ---

export const DESIGNER_SYSTEM_PROMPT = `You are a code designer subagent. Your job is to analyze a task and produce a structured plan for code changes.

You will receive:
1. Context files (source code to understand/modify)
2. A work order describing what needs to be done
3. Constraints and invariants to respect

You must respond with ONLY a JSON object matching this exact schema:
\`\`\`json
{
  "touched_files": ["list of file paths that need changes"],
  "commands": [
    {
      "file": "path/to/file.ts",
      "action": "edit|create|delete",
      "description": "what change to make",
      "line_range": [start, end] // optional, for edits
    }
  ],
  "changed_signatures": [
    {
      "file": "path/to/file.ts",
      "symbol": "className.methodName",
      "change": "description of signature change"
    }
  ],
  "verification": {
    "lint_paths": ["paths to lint after changes"],
    "test_commands": ["optional test commands"],
    "manual_checks": ["things that need human verification"]
  }
}
\`\`\`

Rules:
- Be specific about line ranges when editing existing code
- List ALL files that will be touched, including imports that need updating
- If a signature changes, list all files that reference it
- Keep commands atomic - one logical change per command
- Output ONLY the JSON, no explanations`;

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

// --- QA Subagent ---

export const QA_SYSTEM_PROMPT = `You are a QA subagent. Your job is to verify that code changes meet requirements and don't introduce regressions.

You will receive:
1. Before/after file contents (or diffs)
2. The original work order describing what was supposed to change
3. Lint results (if available)
4. Any constraints or invariants that must hold

You must respond with ONLY a JSON object matching this exact schema:
\`\`\`json
{
  "decision": "pass|fail|needs_review",
  "commands": [
    {
      "type": "fix|revert|manual",
      "file": "path/to/file.ts",
      "description": "what action to take"
    }
  ],
  "verification": {
    "checks_passed": ["list of passing checks"],
    "checks_failed": ["list of failing checks"],
    "coverage_impact": "none|increased|decreased|unknown"
  },
  "reasons": ["explanation for decision"]
}
\`\`\`

Decision criteria:
- "pass": All requirements met, no regressions, lint passes
- "fail": Clear violations that can be automatically fixed
- "needs_review": Ambiguous cases requiring human judgment

Output ONLY the JSON, no explanations`;

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

// --- Work Order (Input to Designer) ---

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

// --- Required fields for validation ---

export const DESIGNER_REQUIRED_FIELDS: (keyof DesignerOutput)[] = [
    'touched_files',
    'commands',
    'changed_signatures',
    'verification'
];

export const QA_REQUIRED_FIELDS: (keyof QAOutput)[] = [
    'decision',
    'commands',
    'verification',
    'reasons'
];
