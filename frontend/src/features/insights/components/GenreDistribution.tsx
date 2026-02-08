/**
 * GenreDistribution - Display top genres.
 *
 * Shows genre breakdown with counts.
 */

import { Box, Chip, Typography } from "@mui/material";

import type { GenreDistributionItem } from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface GenreDistributionProps {
  distribution: GenreDistributionItem[];
  parentId: string;
}

export function GenreDistribution({
  distribution,
  parentId,
}: GenreDistributionProps) {
  if (distribution.length === 0) {
    return (
      <AccordionSubsection
        subsectionId="genres"
        parentId={parentId}
        title="Genres"
      >
        <Typography color="text.secondary">No genre data available</Typography>
      </AccordionSubsection>
    );
  }

  return (
    <AccordionSubsection
      subsectionId="genres"
      parentId={parentId}
      title="Genres"
      secondary={
        <Typography variant="body2" color="text.secondary">
          {distribution.length} genres
        </Typography>
      }
    >
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
        {distribution.map((item) => (
          <Chip
            key={item.genre}
            label={`${item.genre} (${item.count})`}
            size="small"
            variant="outlined"
          />
        ))}
      </Box>
    </AccordionSubsection>
  );
}
