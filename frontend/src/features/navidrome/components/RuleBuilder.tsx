/**
 * Rule builder panel — manages an array of rules with a logic toggle
 * (Match ALL / Match ANY) and assembles the query string for the backend.
 */

import AddIcon from "@mui/icons-material/Add";
import {
  Button,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";

import type { TagStatEntry } from "@shared/api/navidrome";

import { RuleRow, type Rule } from "./RuleRow";
import { createRule, type LogicMode } from "./ruleUtils";

interface RuleBuilderProps {
  rules: Rule[];
  logic: LogicMode;
  numericTags: TagStatEntry[];
  stringTags: TagStatEntry[];
  onRulesChange: (rules: Rule[]) => void;
  onLogicChange: (logic: LogicMode) => void;
}

export function RuleBuilder({
  rules,
  logic,
  numericTags,
  stringTags,
  onRulesChange,
  onLogicChange,
}: RuleBuilderProps) {
  const handleAdd = () => {
    onRulesChange([...rules, createRule()]);
  };

  const handleChange = (index: number, updated: Rule) => {
    const next = [...rules];
    next[index] = updated;
    onRulesChange(next);
  };

  const handleRemove = (index: number) => {
    onRulesChange(rules.filter((_, i) => i !== index));
  };

  const handleLogicToggle = (
    _: React.MouseEvent<HTMLElement>,
    value: LogicMode | null,
  ) => {
    if (value) onLogicChange(value);
  };

  return (
    <Stack spacing={1.5}>
      {/* Logic toggle */}
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography variant="body2" color="text.secondary">
          Match
        </Typography>
        <ToggleButtonGroup
          value={logic}
          exclusive
          onChange={handleLogicToggle}
          size="small"
        >
          <ToggleButton value="all">ALL rules</ToggleButton>
          <ToggleButton value="any">ANY rule</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {/* Rule rows */}
      {rules.map((rule, i) => (
        <RuleRow
          key={rule.id}
          rule={rule}
          numericTags={numericTags}
          stringTags={stringTags}
          onChange={(updated) => handleChange(i, updated)}
          onRemove={() => handleRemove(i)}
        />
      ))}

      {/* Add rule */}
      <Button
        startIcon={<AddIcon />}
        onClick={handleAdd}
        size="small"
        sx={{ alignSelf: "flex-start" }}
      >
        Add Rule
      </Button>
    </Stack>
  );
}
