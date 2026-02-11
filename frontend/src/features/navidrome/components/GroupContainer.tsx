/**
 * Container for a single rule group with logic toggle and nested structure.
 *
 * Displays:
 * - Border/visual container for the group
 * - AND/OR logic toggle for this group
 * - Rules within the group
 * - Nested child groups (recursively rendered)
 * - "Add Rule" button
 */

import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  IconButton,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import { useState } from "react";

import type { TagMetaEntry } from "../hooks/useTagMetadata";

import { RuleRow, type Rule } from "./RuleRow";
import {
  createRule,
  createRuleGroup,
  type LogicMode,
  type RuleGroup,
} from "./ruleUtils";

interface GroupContainerProps {
  group: RuleGroup;
  numericTags: TagMetaEntry[];
  stringTags: TagMetaEntry[];
  depth?: number; // Nesting depth (0 = root)
  onGroupChange: (updated: RuleGroup) => void;
  onRemove?: () => void; // Undefined for root group
}

export function GroupContainer({
  group,
  numericTags,
  stringTags,
  depth = 0,
  onGroupChange,
  onRemove,
}: GroupContainerProps) {
  const isRoot = depth === 0;
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false);

  // Check if group has content
  const hasContent = group.rules.length > 0 || group.groups.length > 0;

  // Rule management
  const handleAddRule = () => {
    const updated = {
      ...group,
      rules: [...group.rules, createRule()],
    };
    onGroupChange(updated);
  };

  const handleRuleChange = (index: number, updatedRule: Rule) => {
    const updated = {
      ...group,
      rules: group.rules.map((r, i) => (i === index ? updatedRule : r)),
    };
    onGroupChange(updated);
  };

  const handleRuleRemove = (index: number) => {
    const updated = {
      ...group,
      rules: group.rules.filter((_, i) => i !== index),
    };
    onGroupChange(updated);
  };

  // Logic toggle
  const handleLogicToggle = (
    _: React.MouseEvent<HTMLElement>,
    value: LogicMode | null
  ) => {
    if (value) {
      const updated = { ...group, logic: value };
      onGroupChange(updated);
    }
  };

  // Nested group management (will be used in P3-S2)
  const handleNestedGroupChange = (index: number, updatedGroup: RuleGroup) => {
    const updated = {
      ...group,
      groups: group.groups.map((g, i) => (i === index ? updatedGroup : g)),
    };
    onGroupChange(updated);
  };

  const handleNestedGroupRemove = (index: number) => {
    const updated = {
      ...group,
      groups: group.groups.filter((_, i) => i !== index),
    };
    onGroupChange(updated);
  };

  const handleAddGroup = () => {
    const newGroup = createRuleGroup(group.logic); // Inherit parent logic
    const updated = {
      ...group,
      groups: [...group.groups, newGroup],
    };
    onGroupChange(updated);
  };


  // Group removal with confirmation
  const handleRemoveClick = () => {
    if (hasContent) {
      setConfirmRemoveOpen(true);
    } else if (onRemove) {
      onRemove();
    }
  };

  const handleConfirmRemove = () => {
    setConfirmRemoveOpen(false);
    if (onRemove) {
      onRemove();
    }
  };

  const handleCancelRemove = () => {
    setConfirmRemoveOpen(false);
  };
  const containerSx = isRoot
    ? {}
    : {
        border: 1,
        borderColor: "divider",
        borderRadius: 1,
        p: 2,
        ml: 2, // Indent nested groups
      };

  return (
    <>
      <Box sx={containerSx}>
        <Stack spacing={1.5}>
          {/* Header: Logic toggle + Remove button */}
          <Stack direction="row" spacing={2} alignItems="center">
            <Typography variant="body2" color="text.secondary">
              {isRoot ? "Match" : "Group match"}
            </Typography>
            <ToggleButtonGroup
              value={group.logic}
              exclusive
              onChange={handleLogicToggle}
              size="small"
            >
              <ToggleButton value="all">ALL</ToggleButton>
              <ToggleButton value="any">ANY</ToggleButton>
            </ToggleButtonGroup>

            {!isRoot && onRemove && (
              <Tooltip title="Remove group">
                <IconButton
                  size="small"
                  onClick={handleRemoveClick}
                  color="error"
                  sx={{ ml: "auto" }}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </Stack>

          {/* Rules in this group */}
          {group.rules.map((rule, i) => (
            <RuleRow
              key={rule.id}
              rule={rule}
              numericTags={numericTags}
              stringTags={stringTags}
              onChange={(updated) => handleRuleChange(i, updated)}
              onRemove={() => handleRuleRemove(i)}
            />
          ))}

          {/* Nested groups (recursive) */}
          {group.groups.map((nestedGroup, i) => (
            <GroupContainer
              key={nestedGroup.id}
              group={nestedGroup}
              numericTags={numericTags}
              stringTags={stringTags}
              depth={depth + 1}
              onGroupChange={(updated) => handleNestedGroupChange(i, updated)}
              onRemove={() => handleNestedGroupRemove(i)}
            />
          ))}

          {/* Action buttons */}
          <Stack direction="row" spacing={1}>
            <Button
              startIcon={<AddIcon />}
              onClick={handleAddRule}
              variant="outlined"
              size="small"
            >
              Add Rule
            </Button>
            <Button
              startIcon={<AddIcon />}
              onClick={handleAddGroup}
              variant="outlined"
              size="small"
            >
              Add Group
            </Button>
          </Stack>
        </Stack>
      </Box>

      {/* Confirmation dialog for group removal */}
      <Dialog open={confirmRemoveOpen} onClose={handleCancelRemove}>
        <DialogTitle>Remove Group?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This group contains {group.rules.length} rule(s) and{" "}
            {group.groups.length} nested group(s). Are you sure you want to
            remove it?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelRemove}>Cancel</Button>
          <Button onClick={handleConfirmRemove} color="error" autoFocus>
            Remove
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
