/**
 * MoodCoverage - Display mood value distribution per tier as pie charts.
 *
 * Each tier has filter pills so users can toggle specific mood values on/off
 * to dig into the less-prominent slices.
 */

import { Box, Chip, Typography } from "@mui/material";
import { PieChart } from "@mui/x-charts/PieChart";
import { useState } from "react";

import { AccordionSubsection } from "@shared/components/ui";

import type {
  MoodBalanceItem,
  MoodCoverage as MoodCoverageType,
} from "../../../shared/api/analytics";


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

// 20-colour accessible palette for pie slices
const PIE_COLORS = [
  "#4C9BE8", "#E86C4C", "#4CE87A", "#E8D44C", "#9B4CE8",
  "#4CE8D4", "#E84C9B", "#A8E84C", "#E8A84C", "#4CA8E8",
  "#E8E84C", "#4CE8A8", "#E84CA8", "#4C4CE8", "#E8C44C",
  "#C44CE8", "#4CE8C4", "#C4E84C", "#E84C4C", "#4CCCE8",
];

/** Single tier pie + filter pills */
function TierChart({
  tier,
  tierData,
  moods,
}: {
  tier: string;
  tierData: { tagged: number; percentage: number } | undefined;
  moods: MoodBalanceItem[];
}) {
  // hiddenMoods: set of mood strings removed from the pie
  const [hiddenMoods, setHiddenMoods] = useState<Set<string>>(new Set());

  const toggleMood = (mood: string) => {
    setHiddenMoods((prev) => {
      const next = new Set(prev);
      if (next.has(mood)) next.delete(mood);
      else next.add(mood);
      return next;
    });
  };

  const allHidden = hiddenMoods.size === moods.length;

  const toggleAll = () => {
    if (allHidden) setHiddenMoods(new Set());
    else setHiddenMoods(new Set(moods.map((m) => m.mood)));
  };

  const visibleMoods = moods.filter((m) => !hiddenMoods.has(m.mood));

  const pieData = visibleMoods.map((m, i) => ({
    id: i,
    value: m.count,
    label: m.mood,
    color: PIE_COLORS[moods.indexOf(m) % PIE_COLORS.length],
  }));

  return (
    <Box sx={{ textAlign: "center", minWidth: 220, maxWidth: 320, flex: "1 1 220px" }}>
      <Typography variant="subtitle2">{TIER_LABELS[tier] ?? tier}</Typography>
      {tierData && (
        <Typography variant="caption" color="text.secondary">
          {tierData.tagged.toLocaleString()} tagged ({tierData.percentage.toFixed(1)}%)
        </Typography>
      )}

      {moods.length > 0 ? (
        <>
          {/* Pie chart */}
          {pieData.length > 0 ? (
            <PieChart
              series={[{
                data: pieData,
                innerRadius: 25,
                outerRadius: 80,
                paddingAngle: 1,
                cornerRadius: 3,
              }]}
              height={200}
              width={260}
              hideLegend
            />
          ) : (
            <Box sx={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Typography variant="body2" color="text.secondary">
                All moods hidden
              </Typography>
            </Box>
          )}

          {/* Filter pills */}
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, justifyContent: "center", mt: 1 }}>
            {moods.map((m) => {
              const hidden = hiddenMoods.has(m.mood);
              const colorIdx = moods.indexOf(m) % PIE_COLORS.length;
              return (
                <Chip
                  key={m.mood}
                  label={m.mood}
                  size="small"
                  onClick={() => toggleMood(m.mood)}
                  variant={hidden ? "outlined" : "filled"}
                  sx={{
                    fontSize: "0.68rem",
                    height: 20,
                    backgroundColor: hidden ? "transparent" : `${PIE_COLORS[colorIdx]}33`,
                    borderColor: PIE_COLORS[colorIdx],
                    color: hidden ? "text.disabled" : "text.primary",
                    cursor: "pointer",
                    "&:hover": { opacity: 0.8 },
                  }}
                />
              );
            })}
            {moods.length > 1 && (
              <Chip
                label={allHidden ? "Show all" : "Hide all"}
                size="small"
                onClick={toggleAll}
                variant="outlined"
                sx={{ fontSize: "0.68rem", height: 20, cursor: "pointer" }}
              />
            )}
          </Box>
        </>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          No data
        </Typography>
      )}
    </Box>
  );
}

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
          gap: 3,
          flexWrap: "wrap",
          justifyContent: "center",
        }}
      >
        {tiers.map((tier) => (
          <TierChart
            key={tier}
            tier={tier}
            tierData={coverage.tiers[tier]}
            moods={balance[tier] ?? []}
          />
        ))}
      </Box>
    </AccordionSubsection>
  );
}
