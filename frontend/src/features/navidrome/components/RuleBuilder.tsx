/**
 * Rule builder panel — manages a root RuleGroup with nested structure.
 * Delegates all UI and logic to GroupContainer component.
 */

import { Stack } from "@mui/material";

import type { TagMetaEntry } from "../hooks/useTagMetadata";

import { GroupContainer } from "./GroupContainer";
import type { RuleGroup } from "./ruleUtils";

interface RuleBuilderProps {
  rootGroup: RuleGroup;
  numericTags: TagMetaEntry[];
  stringTags: TagMetaEntry[];
  onGroupChange: (updated: RuleGroup) => void;
}

export function RuleBuilder({
  rootGroup,
  numericTags,
  stringTags,
  onGroupChange,
}: RuleBuilderProps) {
  return (
    <Stack spacing={1.5}>
      <GroupContainer
        group={rootGroup}
        numericTags={numericTags}
        stringTags={stringTags}
        depth={0}
        onGroupChange={onGroupChange}
      />
    </Stack>
  );
}
