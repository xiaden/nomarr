/**
 * MoodCombos - Display top co-occurring mood pairs.
 */

import { Box, Chip, Typography } from "@mui/material";

import type { MoodPairItem } from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface MoodCombosProps {
  pairs: MoodPairItem[];
  parentId: string;
}

export function MoodCombos({ pairs, parentId }: MoodCombosProps) {
  if (pairs.length === 0) {
    return (
      <AccordionSubsection
        subsectionId="combos"
        parentId={parentId}
        title="Mood Combos"
      >
        <Typography color="text.secondary">
          No mood combinations found
        </Typography>
      </AccordionSubsection>
    );
  }

  return (
    <AccordionSubsection
      subsectionId="combos"
      parentId={parentId}
      title="Mood Combos"
      defaultExpanded={false}
      secondary={
        <Typography variant="body2" color="text.secondary">
          Top pairs
        </Typography>
      }
    >
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
        {pairs.map((pair, index) => (
          <Chip
            key={`${pair.mood1}-${pair.mood2}`}
            label={
              <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                <Typography
                  variant="body2"
                  component="span"
                  sx={{ textTransform: "capitalize" }}
                >
                  {pair.mood1}
                </Typography>
                <Typography variant="body2" component="span" color="text.secondary">
                  +
                </Typography>
                <Typography
                  variant="body2"
                  component="span"
                  sx={{ textTransform: "capitalize" }}
                >
                  {pair.mood2}
                </Typography>
                <Typography
                  variant="body2"
                  component="span"
                  color="text.secondary"
                  sx={{ ml: 0.5 }}
                >
                  ({pair.count})
                </Typography>
              </Box>
            }
            variant={index < 3 ? "filled" : "outlined"}
            color={index < 3 ? "primary" : "default"}
            size="small"
          />
        ))}
      </Box>
    </AccordionSubsection>
  );
}
