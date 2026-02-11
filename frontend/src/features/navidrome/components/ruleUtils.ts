/**
 * Utilities for the playlist rule builder.
 */

import type { Rule } from "./RuleRow";

export type LogicMode = "all" | "any";

/**
 * Nested rule group for complex boolean logic.
 *
 * Supports hierarchical structures like: (A AND B) OR (C AND D)
 * Backend enforces MAX_RULE_GROUP_DEPTH = 5.
 */
export interface RuleGroup {
  id: string;
  logic: LogicMode;
  rules: Rule[];
  groups: RuleGroup[]; // Recursive nesting
}

let nextId = 1;

/** Create a blank rule with a unique id. */
export function createRule(): Rule {
  return { id: String(nextId++), tagKey: "", operator: "=", value: "" };
}

/** Create a blank rule group with a unique id. */
export function createRuleGroup(logic: LogicMode = "all"): RuleGroup {
  return {
    id: String(nextId++),
    logic,
    rules: [],
    groups: [],
  };
}

/**
 * Convert flat rules array to single root group.
 *
 * For backward compatibility - wraps existing flat rule list
 * in a single group with no nesting.
 *
 * @param rules - Flat array of rules
 * @param logic - Logic mode for the group ("all" or "any")
 * @returns Root RuleGroup with rules and no nested groups
 */
export function flatRulesToRootGroup(rules: Rule[], logic: LogicMode): RuleGroup {
  return {
    id: String(nextId++),
    logic,
    rules,
    groups: [], // No nesting for flat queries
  };
}

/** Maximum allowed nesting depth (must match backend MAX_RULE_GROUP_DEPTH). */
export const MAX_RULE_GROUP_DEPTH = 5;

/**
 * Calculate the maximum nesting depth of a rule group tree.
 *
 * @param group - RuleGroup to measure
 * @returns Depth (1 for leaf group, 1 + max child depth otherwise)
 */
export function calculateGroupDepth(group: RuleGroup): number {
  if (group.groups.length === 0) {
    return 1;
  }
  return 1 + Math.max(...group.groups.map(calculateGroupDepth));
}

/**
 * Validate that group depth does not exceed backend limit.
 *
 * @param group - RuleGroup to validate
 * @returns Error message if depth exceeds limit, null if valid
 */
export function validateGroupDepth(group: RuleGroup): string | null {
  const depth = calculateGroupDepth(group);
  if (depth > MAX_RULE_GROUP_DEPTH) {
    return `Group nesting too deep (${depth} levels). Maximum allowed: ${MAX_RULE_GROUP_DEPTH}`;
  }
  return null;
}

/**
 * Assemble the backend query string from structured rule groups.
 *
 * Format: `tag:KEY OPERATOR VALUE [AND|OR] tag:KEY OPERATOR VALUE`
 * Supports nested groups with parentheses: `(A AND B) OR (C AND D)`
 *
 * @param group - Root RuleGroup (may contain nested groups)
 * @returns Query string with proper nesting and operators
 */
export function buildQueryString(group: RuleGroup): string {
  const parts: string[] = [];

  // Add rules from this group
  const ruleParts = group.rules
    .filter((r) => r.tagKey && r.value !== "")
    .map((r) => `tag:${r.tagKey} ${r.operator} ${r.value}`);
  parts.push(...ruleParts);

  // Recursively add nested groups with parentheses
  for (const nestedGroup of group.groups) {
    const nestedQuery = buildQueryString(nestedGroup);
    if (nestedQuery) {
      // Wrap nested groups in parentheses
      parts.push(`(${nestedQuery})`);
    }
  }

  // Join with appropriate operator
  const operator = group.logic === "all" ? " AND " : " OR ";
  return parts.join(operator);
}

/**
 * Assemble query string from flat rules (backward compatibility).
 *
 * @deprecated Use buildQueryString(RuleGroup) instead
 * @param rules - Flat array of rules
 * @param logic - Logic mode
 * @returns Query string
 */
export function buildQueryStringFlat(rules: Rule[], logic: LogicMode): string {
  const group = flatRulesToRootGroup(rules, logic);
  return buildQueryString(group);
}
