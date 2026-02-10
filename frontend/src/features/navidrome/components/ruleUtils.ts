/**
 * Utilities for the playlist rule builder.
 */

import type { Rule } from "./RuleRow";

export type LogicMode = "all" | "any";

let nextId = 1;

/** Create a blank rule with a unique id. */
export function createRule(): Rule {
  return { id: String(nextId++), tagKey: "", operator: "=", value: "" };
}

/**
 * Assemble the backend query string from structured rules.
 *
 * Format: `tag:KEY OPERATOR VALUE [AND|OR] tag:KEY OPERATOR VALUE`
 * The backend only accepts uniform logic — all AND or all OR.
 */
export function buildQueryString(rules: Rule[], logic: LogicMode): string {
  const parts = rules
    .filter((r) => r.tagKey && r.value !== "")
    .map((r) => `tag:${r.tagKey} ${r.operator} ${r.value}`);

  const joiner = logic === "all" ? " AND " : " OR ";
  return parts.join(joiner);
}
