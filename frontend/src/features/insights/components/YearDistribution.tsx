/**
 * YearDistribution - Display year distribution as a smooth line chart.
 *
 * Shows release years as a chronological line chart using MUI X Charts.
 * Filters out year "1" (garbage data). Uses catmullRom curve for smooth interpolation.
 */

import { Typography } from "@mui/material";
import { LineChart } from "@mui/x-charts/LineChart";

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
  // Filter out year "1" (garbage data) and sort chronologically
  const sorted = distribution
    .filter((d) => String(d.year) !== "1")
    .sort((a, b) => Number(a.year) - Number(b.year));

  if (sorted.length === 0) {
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

  const years = sorted.map((d) => String(d.year));
  const counts = sorted.map((d) => d.count);

  return (
    <AccordionSubsection
      subsectionId="years"
      parentId={parentId}
      title="Years"
      secondary={
        <Typography variant="body2" color="text.secondary">
          {sorted.length} years
        </Typography>
      }
    >
      <LineChart
        height={250}
        xAxis={[{ scaleType: "point", data: years }]}
        series={[{ data: counts, curve: "catmullRom", showMark: false }]}
        margin={{ left: 50, right: 20, top: 20, bottom: 30 }}
      />
    </AccordionSubsection>
  );
}
