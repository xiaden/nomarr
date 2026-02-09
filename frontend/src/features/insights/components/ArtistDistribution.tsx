/**
 * ArtistDistribution - Display top artists as a vertical bar chart.
 *
 * Shows top artists using MUI X Charts BarChart with "others" summary below.
 */

import { Typography } from "@mui/material";
import { BarChart } from "@mui/x-charts/BarChart";

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

  const artists = top_artists.map((d) => d.artist);
  const counts = top_artists.map((d) => d.count);

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
      <BarChart
        height={300}
        xAxis={[
          {
            scaleType: "band",
            data: artists,
            tickLabelStyle: { angle: -45, textAnchor: "end", fontSize: 11 },
          },
        ]}
        series={[{ data: counts }]}
        margin={{ left: 50, right: 20, top: 20, bottom: 80 }}
      />
      {others_count > 0 && (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ fontStyle: "italic", mt: 1 }}
        >
          + {others_count} tracks from {total_artists - top_artists.length}{" "}
          other artists
        </Typography>
      )}
    </AccordionSubsection>
  );
}
