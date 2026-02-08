/**
 * MoodCoverage - Display mood tag coverage per tier.
 *
 * Shows what percentage of tracks have mood tags at each tier.
 */

import { Box, LinearProgress, Typography } from "@mui/material";

import type { MoodCoverage as MoodCoverageType } from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface MoodCoverageProps {
  coverage: MoodCoverageType;
  parentId: string;
}

const TIER_LABELS: Record<string, string> = {
  strict: "Strict (Primary)",
  relaxed: "Relaxed (Secondary)",
  genre: "Genre-Implied",
};

export function MoodCoverage({ coverage, parentId }: MoodCoverageProps) {
  const tierEntries = Object.entries(coverage.tiers);

  return (
    <AccordionSubsection
      subsectionId="coverage"
      parentId={parentId}
      title="Mood Coverage"
      secondary={
        <Typography variant="body2" color="text.secondary">
          {coverage.total_files.toLocaleString()} tracks
        </Typography>
      }
    >
      <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {tierEntries.map(([tier, data]) => (
          <Box key={tier}>
            <Box
              sx={{
                display: "flex",
                justifyContent: "space-between",
                mb: 0.5,
              }}
            >
              <Typography variant="body2">
                {TIER_LABELS[tier] || tier}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {data.tagged.toLocaleString()} ({data.percentage.toFixed(1)}%)
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={data.percentage}
              sx={{ height: 8, borderRadius: 1 }}
            />
          </Box>
        ))}
      </Box>
    </AccordionSubsection>
  );
}
