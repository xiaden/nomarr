/**
 * YearDistribution - Display year distribution as a simple bar chart.
 *
 * Shows release years histogram.
 */

import { Box, Typography } from "@mui/material";

import type { YearDistributionItem } from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface YearDistributionProps {
  distribution: YearDistributionItem[];
  parentId: string;
}

export function YearDistribution({
  distribution,
  parentId,
}: YearDistributionProps) {
  if (distribution.length === 0) {
    return (
      <AccordionSubsection
        subsectionId="years"
        parentId={parentId}
        title="Years"
      >
        <Typography color="text.secondary">No year data available</Typography>
      </AccordionSubsection>
    );
  }

  const maxCount = Math.max(...distribution.map((d) => d.count));

  return (
    <AccordionSubsection
      subsectionId="years"
      parentId={parentId}
      title="Years"
      secondary={
        <Typography variant="body2" color="text.secondary">
          {distribution.length} years
        </Typography>
      }
    >
      <Box sx={{ maxHeight: 200, overflow: "auto" }}>
        {distribution.map((item) => (
          <Box
            key={item.year}
            sx={{
              display: "flex",
              alignItems: "center",
              mb: 0.5,
            }}
          >
            <Typography
              variant="body2"
              sx={{ width: 60, flexShrink: 0, textAlign: "right", mr: 1 }}
            >
              {item.year}
            </Typography>
            <Box
              sx={{
                height: 16,
                width: `${(item.count / maxCount) * 100}%`,
                minWidth: 2,
                bgcolor: "primary.main",
                borderRadius: 0.5,
              }}
            />
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ ml: 1, flexShrink: 0 }}
            >
              {item.count}
            </Typography>
          </Box>
        ))}
      </Box>
    </AccordionSubsection>
  );
}
