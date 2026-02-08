/**
 * ArtistDistribution - Display top artists.
 *
 * Shows top artists list and "others" count.
 */

import { Box, List, ListItem, ListItemText, Typography } from "@mui/material";

import type { ArtistDistribution as ArtistDistributionType } from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface ArtistDistributionProps {
  distribution: ArtistDistributionType;
  parentId: string;
}

export function ArtistDistribution({
  distribution,
  parentId,
}: ArtistDistributionProps) {
  const { top_artists, others_count, total_artists } = distribution;

  if (top_artists.length === 0) {
    return (
      <AccordionSubsection
        subsectionId="artists"
        parentId={parentId}
        title="Artists"
      >
        <Typography color="text.secondary">
          No artist data available
        </Typography>
      </AccordionSubsection>
    );
  }

  return (
    <AccordionSubsection
      subsectionId="artists"
      parentId={parentId}
      title="Artists"
      secondary={
        <Typography variant="body2" color="text.secondary">
          {total_artists} artists
        </Typography>
      }
    >
      <List dense disablePadding>
        {top_artists.map((item, index) => (
          <ListItem key={item.artist} disableGutters sx={{ py: 0.25 }}>
            <ListItemText
              primary={
                <Box sx={{ display: "flex", alignItems: "center" }}>
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ width: 24, textAlign: "right", mr: 1 }}
                  >
                    {index + 1}.
                  </Typography>
                  <Typography variant="body2">{item.artist}</Typography>
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ ml: "auto" }}
                  >
                    {item.count} tracks
                  </Typography>
                </Box>
              }
            />
          </ListItem>
        ))}
        {others_count > 0 && (
          <ListItem disableGutters sx={{ py: 0.25 }}>
            <ListItemText
              primary={
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ fontStyle: "italic" }}
                >
                  + {others_count} tracks from{" "}
                  {total_artists - top_artists.length} other artists
                </Typography>
              }
            />
          </ListItem>
        )}
      </List>
    </AccordionSubsection>
  );
}
