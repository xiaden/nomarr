/**
 * MoodCoverage - Display mood value distribution per tier as pie charts.
 *
 * Shows three pie charts (one per tier) showing proportions of mood values.
 * Each pie includes the tier's coverage stats as a subtitle.
 */

import { Box, Typography } from "@mui/material";
import { PieChart } from "@mui/x-charts/PieChart";

import type {
  MoodBalanceItem,
  MoodCoverage as MoodCoverageType,
} from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface MoodCoverageProps {
  coverage: MoodCoverageType;
  balance: Record<string, MoodBalanceItem[]>;
  parentId: string;
}

const TIER_LABELS: Record<string, string> = {
  strict: "Strict",
  regular: "Regular",
  loose: "Loose",
};

const TIER_ORDER = ["strict", "regular", "loose"];

export function MoodCoverage({
  coverage,
  balance,
  parentId,
}: MoodCoverageProps) {
  const tiers = TIER_ORDER.filter(
    (t) => t in coverage.tiers || t in balance,
  );

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
      <Box
        sx={{
          display: "flex",
          gap: 2,
          flexWrap: "wrap",
          justifyContent: "center",
        }}
      >
        {tiers.map((tier) => {
          const tierData = coverage.tiers[tier];
          const moods = balance[tier] || [];
          const pieData = moods.map((m, i) => ({
            id: i,
            value: m.count,
            label: m.mood,
          }));

          return (
            <Box key={tier} sx={{ textAlign: "center", minWidth: 200 }}>
              <Typography variant="subtitle2">
                {TIER_LABELS[tier] || tier}
              </Typography>
              {tierData && (
                <Typography variant="caption" color="text.secondary">
                  {tierData.tagged.toLocaleString()} tagged (
                  {tierData.percentage.toFixed(1)}%)
                </Typography>
              )}
              {pieData.length > 0 ? (
                <PieChart
                  series={[
                    {
                      data: pieData,
                      innerRadius: 25,
                      outerRadius: 80,
                      paddingAngle: 1,
                      cornerRadius: 3,
                    },
                  ]}
                  height={200}
                  width={250}
                  hideLegend
                />
              ) : (
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ mt: 2 }}
                >
                  No data
                </Typography>
              )}
            </Box>
          );
        })}
      </Box>
    </AccordionSubsection>
  );
}
