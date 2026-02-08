/**
 * DominantVibes - Display dominant mood vibes.
 *
 * Shows top 5 moods across all tiers.
 */

import { Box, Typography } from "@mui/material";

import type { DominantVibeItem } from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface DominantVibesProps {
  vibes: DominantVibeItem[];
  parentId: string;
}

export function DominantVibes({ vibes, parentId }: DominantVibesProps) {
  if (vibes.length === 0) {
    return (
      <AccordionSubsection
        subsectionId="vibes"
        parentId={parentId}
        title="Dominant Vibes"
      >
        <Typography color="text.secondary">No mood data available</Typography>
      </AccordionSubsection>
    );
  }

  return (
    <AccordionSubsection
      subsectionId="vibes"
      parentId={parentId}
      title="Dominant Vibes"
    >
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
        {vibes.map((vibe, index) => (
          <Box
            key={vibe.mood}
            sx={{
              textAlign: "center",
              flex: "1 1 100px",
              p: 1,
              borderRadius: 1,
              bgcolor: index === 0 ? "primary.main" : "action.hover",
              color: index === 0 ? "primary.contrastText" : "text.primary",
            }}
          >
            <Typography variant="h6">{vibe.percentage.toFixed(0)}%</Typography>
            <Typography
              variant="body2"
              sx={{ textTransform: "capitalize" }}
            >
              {vibe.mood}
            </Typography>
          </Box>
        ))}
      </Box>
    </AccordionSubsection>
  );
}
