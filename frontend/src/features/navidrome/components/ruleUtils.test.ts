/**
 * Tests for ruleUtils query building functions.
 */

import { describe, it, expect } from "vitest";

import type { Rule } from "./RuleRow";
import {
  buildQueryString,
  calculateGroupDepth,
  createRuleGroup,
  flatRulesToRootGroup,
  MAX_RULE_GROUP_DEPTH,
  validateGroupDepth,
} from "./ruleUtils";

describe("buildQueryString", () => {
  it("builds query from flat rules in single group", () => {
    const rules: Rule[] = [
      { id: "1", tagKey: "mood_happy", operator: ">", value: "0.7" },
      { id: "2", tagKey: "energy", operator: ">", value: "0.6" },
    ];
    const group = flatRulesToRootGroup(rules, "all");
    const query = buildQueryString(group);
    expect(query).toBe("tag:mood_happy > 0.7 AND tag:energy > 0.6");
  });

  it("builds query with OR logic", () => {
    const rules: Rule[] = [
      { id: "1", tagKey: "calm", operator: ">", value: "0.8" },
      { id: "2", tagKey: "aggressive", operator: ">", value: "0.8" },
    ];
    const group = flatRulesToRootGroup(rules, "any");
    const query = buildQueryString(group);
    expect(query).toBe("tag:calm > 0.8 OR tag:aggressive > 0.8");
  });

  it("filters out incomplete rules", () => {
    const rules: Rule[] = [
      { id: "1", tagKey: "mood_happy", operator: ">", value: "0.7" },
      { id: "2", tagKey: "", operator: ">", value: "0.6" }, // Missing tagKey
      { id: "3", tagKey: "energy", operator: ">", value: "" }, // Missing value
    ];
    const group = flatRulesToRootGroup(rules, "all");
    const query = buildQueryString(group);
    expect(query).toBe("tag:mood_happy > 0.7");
  });

  it("builds nested query with parentheses", () => {
    // (mood_happy > 0.7 AND energy > 0.6) OR calm > 0.8
    const group1 = createRuleGroup("all");
    group1.rules = [
      { id: "1", tagKey: "mood_happy", operator: ">", value: "0.7" },
      { id: "2", tagKey: "energy", operator: ">", value: "0.6" },
    ];

    const rootGroup = createRuleGroup("any");
    rootGroup.rules = [
      { id: "3", tagKey: "calm", operator: ">", value: "0.8" },
    ];
    rootGroup.groups = [group1];

    const query = buildQueryString(rootGroup);
    expect(query).toBe("tag:calm > 0.8 OR (tag:mood_happy > 0.7 AND tag:energy > 0.6)");
  });

  it("builds complex nested query", () => {
    // (energetic AND electronic) OR (calm AND acoustic)
    const group1 = createRuleGroup("all");
    group1.rules = [
      { id: "1", tagKey: "energetic", operator: ">", value: "0.7" },
      { id: "2", tagKey: "electronic", operator: ">", value: "0.7" },
    ];

    const group2 = createRuleGroup("all");
    group2.rules = [
      { id: "3", tagKey: "calm", operator: ">", value: "0.7" },
      { id: "4", tagKey: "acoustic", operator: ">", value: "0.7" },
    ];

    const rootGroup = createRuleGroup("any");
    rootGroup.groups = [group1, group2];

    const query = buildQueryString(rootGroup);
    expect(query).toBe(
      "(tag:energetic > 0.7 AND tag:electronic > 0.7) OR (tag:calm > 0.7 AND tag:acoustic > 0.7)"
    );
  });

  it("handles deeply nested groups", () => {
    // ((A AND B) OR C) AND D
    const innerGroup = createRuleGroup("all");
    innerGroup.rules = [
      { id: "1", tagKey: "A", operator: "=", value: "1" },
      { id: "2", tagKey: "B", operator: "=", value: "1" },
    ];

    const middleGroup = createRuleGroup("any");
    middleGroup.rules = [
      { id: "3", tagKey: "C", operator: "=", value: "1" },
    ];
    middleGroup.groups = [innerGroup];

    const rootGroup = createRuleGroup("all");
    rootGroup.rules = [
      { id: "4", tagKey: "D", operator: "=", value: "1" },
    ];
    rootGroup.groups = [middleGroup];

    const query = buildQueryString(rootGroup);
    expect(query).toBe("tag:D = 1 AND (tag:C = 1 OR (tag:A = 1 AND tag:B = 1))");
  });

  it("handles empty group", () => {
    const group = createRuleGroup("all");
    const query = buildQueryString(group);
    expect(query).toBe("");
  });

  it("handles group with only nested groups (no direct rules)", () => {
    const group1 = createRuleGroup("all");
    group1.rules = [
      { id: "1", tagKey: "A", operator: "=", value: "1" },
    ];

    const group2 = createRuleGroup("all");
    group2.rules = [
      { id: "2", tagKey: "B", operator: "=", value: "1" },
    ];

    const rootGroup = createRuleGroup("any");
    rootGroup.groups = [group1, group2];

    const query = buildQueryString(rootGroup);
    expect(query).toBe("(tag:A = 1) OR (tag:B = 1)");
  });
});

/**
 * P2-S1: Test RuleGroup depth validation - prevent adding groups beyond max depth.
 */
describe("RuleGroup depth validation", () => {
  it("single group has depth 1", () => {
    const group = createRuleGroup("all");
    expect(calculateGroupDepth(group)).toBe(1);
  });

  it("one nested group has depth 2", () => {
    const inner = createRuleGroup("any");
    const outer = createRuleGroup("all");
    outer.groups.push(inner);
    expect(calculateGroupDepth(outer)).toBe(2);
  });

  it("three levels of nesting has depth 3", () => {
    const level3 = createRuleGroup("all");
    const level2 = createRuleGroup("any");
    level2.groups.push(level3);
    const level1 = createRuleGroup("all");
    level1.groups.push(level2);
    expect(calculateGroupDepth(level1)).toBe(3);
  });

  it("validateGroupDepth returns null for valid depth", () => {
    const group = createRuleGroup("all");
    expect(validateGroupDepth(group)).toBeNull();
  });

  it("validateGroupDepth returns error for depth > MAX_RULE_GROUP_DEPTH", () => {
    // Build a chain deeper than MAX_RULE_GROUP_DEPTH
    let current = createRuleGroup("all");
    for (let i = 0; i < MAX_RULE_GROUP_DEPTH; i++) {
      const wrapper = createRuleGroup("any");
      wrapper.groups.push(current);
      current = wrapper;
    }
    // current now has depth = MAX_RULE_GROUP_DEPTH + 1
    expect(calculateGroupDepth(current)).toBe(MAX_RULE_GROUP_DEPTH + 1);
    expect(validateGroupDepth(current)).not.toBeNull();
    expect(validateGroupDepth(current)).toContain("too deep");
  });

  it("validateGroupDepth accepts depth exactly at MAX_RULE_GROUP_DEPTH", () => {
    let current = createRuleGroup("all");
    for (let i = 0; i < MAX_RULE_GROUP_DEPTH - 1; i++) {
      const wrapper = createRuleGroup("any");
      wrapper.groups.push(current);
      current = wrapper;
    }
    expect(calculateGroupDepth(current)).toBe(MAX_RULE_GROUP_DEPTH);
    expect(validateGroupDepth(current)).toBeNull();
  });

  it("sibling groups use max depth", () => {
    const deep = createRuleGroup();
    const child = createRuleGroup();
    child.groups.push(deep);

    const shallow = createRuleGroup();

    const root = createRuleGroup();
    root.groups.push(child, shallow);
    expect(calculateGroupDepth(root)).toBe(3);
  });
});

/**
 * P2-S2: Test group removal - ensure state updates correctly.
 */
describe("Group state management", () => {
  it("removing a nested group reduces depth", () => {
    const inner = createRuleGroup();
    const outer = createRuleGroup();
    outer.groups.push(inner);
    expect(calculateGroupDepth(outer)).toBe(2);

    outer.groups = [];
    expect(calculateGroupDepth(outer)).toBe(1);
  });

  it("groups can contain both rules and nested groups", () => {
    const rule: Rule = { id: "1", tagKey: "mood", operator: ">", value: "0.5" };
    const nested = createRuleGroup();
    const root = createRuleGroup();
    root.rules.push(rule);
    root.groups.push(nested);

    expect(root.rules).toHaveLength(1);
    expect(root.groups).toHaveLength(1);
  });
});

/**
 * P2-S4: Test nested state updates - ensure immutability preserved.
 */
describe("Immutability of nested state updates", () => {
  it("flatRulesToRootGroup creates new group without mutating input", () => {
    const rules: Rule[] = [
      { id: "1", tagKey: "mood", operator: ">", value: "0.5" },
    ];
    const originalLength = rules.length;
    const group = flatRulesToRootGroup(rules, "all");

    expect(rules.length).toBe(originalLength);
    expect(group.rules).toHaveLength(1);
    expect(group.rules[0]).toBe(rules[0]);
  });

  it("adding nested group does not mutate sibling groups", () => {
    const sibling = createRuleGroup("all");
    sibling.rules.push({ id: "1", tagKey: "a", operator: ">", value: "0.5" });

    const parent = createRuleGroup("any");
    parent.groups.push(sibling);

    const newSibling = createRuleGroup("all");
    parent.groups.push(newSibling);

    expect(sibling.groups).toHaveLength(0);
    expect(sibling.rules).toHaveLength(1);
  });

  it("createRuleGroup returns independent instances", () => {
    const group1 = createRuleGroup("all");
    const group2 = createRuleGroup("any");

    expect(group1.id).not.toBe(group2.id);
    expect(group1.logic).toBe("all");
    expect(group2.logic).toBe("any");

    group1.rules.push({ id: "r1", tagKey: "test", operator: ">", value: "1" });
    expect(group2.rules).toHaveLength(0);
  });
});