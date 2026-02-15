/**
 * Manual tag selector accordion for advanced tag selection.
 * Only active when the corresponding axis preset is "manual".
 */

import CloseIcon from "@mui/icons-material/Close";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Stack,
  Typography,
} from "@mui/material";
import type { JSX } from "react";
import { useEffect, useState } from "react";

import type { TagSpec } from "../../../../shared/api/analytics";
import { getUniqueTagKeys, getUniqueTagValues } from "../../../../shared/api/files";
import { ComboBox } from "../../../../shared/components/ComboBox";

import { PRESET_METADATA } from "./types";

interface ManualTagSelectorProps {
  /** Tags currently on X axis */
  xTags: TagSpec[];
  /** Tags currently on Y axis */
  yTags: TagSpec[];
  /** Whether X axis is in manual mode */
  xIsManual: boolean;
  /** Whether Y axis is in manual mode */
  yIsManual: boolean;
  /** Add tag to X axis */
  onAddToX: (tag: TagSpec) => void;
  /** Add tag to Y axis */
  onAddToY: (tag: TagSpec) => void;
  /** Remove tag from X axis */
  onRemoveFromX: (index: number) => void;
  /** Remove tag from Y axis */
  onRemoveFromY: (index: number) => void;
}

export function ManualTagSelector({
  xTags,
  yTags,
  xIsManual,
  yIsManual,
  onAddToX,
  onAddToY,
  onRemoveFromX,
  onRemoveFromY,
}: ManualTagSelectorProps): JSX.Element {
  const [tagKeys, setTagKeys] = useState<string[]>([]);
  const [tagValues, setTagValues] = useState<string[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [selectedValue, setSelectedValue] = useState("");

  // Load tag keys on mount
  useEffect(() => {
    const loadTagKeys = async () => {
      try {
        const response = await getUniqueTagKeys(true);
        setTagKeys(response.tag_keys);
      } catch (err) {
        console.error("[ManualTagSelector] Failed to load tag keys:", err);
      }
    };
    void loadTagKeys();
  }, []);

  // Load tag values when key changes
  useEffect(() => {
    if (!selectedKey) {
      setTagValues([]);
      setSelectedValue("");
      return;
    }

    const loadTagValues = async () => {
      try {
        const response = await getUniqueTagValues(selectedKey, true);
        // Parse multi-value tags
        const parsedValues = new Set<string>();
        for (const value of response.tag_keys) {
          if (value.startsWith("[") && value.endsWith("]")) {
            try {
              const parsed = JSON.parse(value) as unknown;
              if (Array.isArray(parsed)) {
                for (const v of parsed) {
                  parsedValues.add(String(v));
                }
              } else {
                parsedValues.add(value);
              }
            } catch {
              parsedValues.add(value);
            }
          } else {
            parsedValues.add(value);
          }
        }
        setTagValues(Array.from(parsedValues).sort());
      } catch (err) {
        console.error("[ManualTagSelector] Failed to load tag values:", err);
        setTagValues([]);
      }
    };
    void loadTagValues();
  }, [selectedKey]);

  const isTagInEitherAxis = (key: string, value: string): boolean => {
    return (
      xTags.some((t) => t.key === key && t.value === value) ||
      yTags.some((t) => t.key === key && t.value === value)
    );
  };

  const maxValues = PRESET_METADATA.manual.maxValues;
  const canAddToX = xIsManual && selectedKey && selectedValue &&
    xTags.length < maxValues && !isTagInEitherAxis(selectedKey, selectedValue);
  const canAddToY = yIsManual && selectedKey && selectedValue &&
    yTags.length < maxValues && !isTagInEitherAxis(selectedKey, selectedValue);

  const handleAddToX = () => {
    if (canAddToX) {
      onAddToX({ key: selectedKey, value: selectedValue });
    }
  };

  const handleAddToY = () => {
    if (canAddToY) {
      onAddToY({ key: selectedKey, value: selectedValue });
    }
  };

  // Don't show if neither axis is in manual mode
  if (!xIsManual && !yIsManual) {
    return <></>;
  }

  return (
    <Accordion
      sx={{
        bgcolor: "background.paper",
        "&:before": { display: "none" },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>
          Advanced (Manual Tag Selection)
        </Typography>
      </AccordionSummary>

      <AccordionDetails>
        <Stack spacing={2}>
          {/* Tag Selection */}
          <Box sx={{ display: "flex", gap: 1.5, alignItems: "flex-end" }}>
            <Box sx={{ flex: 1 }}>
              <Typography variant="body2" sx={{ mb: 0.5, fontWeight: 500 }}>
                Tag Key
              </Typography>
              <ComboBox
                value={selectedKey}
                onChange={setSelectedKey}
                options={tagKeys}
                placeholder="Select tag key..."
              />
            </Box>
            <Box sx={{ flex: 1 }}>
              <Typography variant="body2" sx={{ mb: 0.5, fontWeight: 500 }}>
                Tag Value
              </Typography>
              <ComboBox
                value={selectedValue}
                onChange={setSelectedValue}
                options={tagValues}
                placeholder="Select tag value..."
                disabled={!selectedKey}
              />
            </Box>
            <Button
              onClick={handleAddToX}
              disabled={!canAddToX}
              variant="contained"
              size="small"
            >
              Add to X
            </Button>
            <Button
              onClick={handleAddToY}
              disabled={!canAddToY}
              variant="contained"
              color="secondary"
              size="small"
            >
              Add to Y
            </Button>
          </Box>

          {/* Manual X Axis Tags */}
          {xIsManual && (
            <Box>
              <Typography variant="body2" sx={{ mb: 0.5, fontWeight: 500 }}>
                X Axis Manual Tags ({xTags.length}/{maxValues})
              </Typography>
              <Box
                sx={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 1,
                  p: 1.5,
                  bgcolor: "background.default",
                  border: 1,
                  borderColor: "divider",
                  borderRadius: 1,
                  minHeight: 48,
                }}
              >
                {xTags.length === 0 && (
                  <Typography variant="body2" color="text.secondary">
                    No tags added
                  </Typography>
                )}
                {xTags.map((tag, index) => (
                  <Chip
                    key={index}
                    label={`${tag.key}: ${tag.value}`}
                    onDelete={() => onRemoveFromX(index)}
                    deleteIcon={<CloseIcon />}
                    size="small"
                  />
                ))}
              </Box>
            </Box>
          )}

          {/* Manual Y Axis Tags */}
          {yIsManual && (
            <Box>
              <Typography variant="body2" sx={{ mb: 0.5, fontWeight: 500 }}>
                Y Axis Manual Tags ({yTags.length}/{maxValues})
              </Typography>
              <Box
                sx={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 1,
                  p: 1.5,
                  bgcolor: "background.default",
                  border: 1,
                  borderColor: "divider",
                  borderRadius: 1,
                  minHeight: 48,
                }}
              >
                {yTags.length === 0 && (
                  <Typography variant="body2" color="text.secondary">
                    No tags added
                  </Typography>
                )}
                {yTags.map((tag, index) => (
                  <Chip
                    key={index}
                    label={`${tag.key}: ${tag.value}`}
                    onDelete={() => onRemoveFromY(index)}
                    deleteIcon={<CloseIcon />}
                    size="small"
                  />
                ))}
              </Box>
            </Box>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
