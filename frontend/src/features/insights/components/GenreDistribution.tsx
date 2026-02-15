/**
 * GenreDistribution - Interactive pie chart with toggleable genres.
 *
 * Features:
 * - All genres returned from backend (no limit)
 * - Clickable chips to hide/show individual genres
 * - Pie chart updates dynamically
 */

import { Box, Chip, Stack, Typography } from "@mui/material";
import { PieChart } from "@mui/x-charts/PieChart";
import { useMemo, useState } from "react";

import type { GenreDistributionItem } from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface GenreDistributionProps {
  distribution: GenreDistributionItem[];
  parentId: string;
}

// Color palette for pie slices (will cycle if more genres than colors)
const COLORS = [
  "#2196f3", "#4caf50", "#ff9800", "#e91e63", "#9c27b0",
  "#00bcd4", "#ff5722", "#795548", "#607d8b", "#3f51b5",
  "#8bc34a", "#ffc107", "#673ab7", "#009688", "#f44336",
  "#03a9f4", "#cddc39", "#ffeb3b", "#9e9e9e", "#ff4081",
];

export function GenreDistribution({
  distribution,
  parentId,
}: GenreDistributionProps) {
  // Initialize with genres beyond top 5 hidden
  const [hiddenGenres, setHiddenGenres] = useState<Set<string>>(() => {
    return new Set(distribution.slice(5).map(d => d.genre));
  });

  // Filter and transform data for pie chart
  const { pieData, visibleCount, totalCount } = useMemo(() => {
    const visible = distribution.filter(d => !hiddenGenres.has(d.genre));
    return {
      pieData: visible.map((d, idx) => ({
        id: d.genre,
        value: d.count,
        label: d.genre,
        color: COLORS[idx % COLORS.length],
      })),
      visibleCount: visible.length,
      totalCount: distribution.length,
    };
  }, [distribution, hiddenGenres]);

  const toggleGenre = (genre: string) => {
    setHiddenGenres(prev => {
      const next = new Set(prev);
      if (next.has(genre)) {
        next.delete(genre);
      } else {
        next.add(genre);
      }
      return next;
    });
  };

  const showAll = () => setHiddenGenres(new Set());
  const hideAll = () => setHiddenGenres(new Set(distribution.map(d => d.genre)));

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
          {visibleCount} of {totalCount} genres shown
        </Typography>
      }
    >
      {/* Pie Chart */}
      {pieData.length > 0 ? (
        <Box sx={{ height: 350, mb: 2 }}>
          <PieChart
            series={[
              {
                data: pieData,
                innerRadius: 40,
                outerRadius: 120,
                paddingAngle: 1,
                cornerRadius: 4,
                highlightScope: { highlight: "item", fade: "global" },
              },
            ]}
            height={350}
            hideLegend
          />
        </Box>
      ) : (
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          All genres hidden. Click chips below to show.
        </Typography>
      )}

      {/* Toggle controls */}
      <Box sx={{ mb: 1 }}>
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <Chip
            label="Show All"
            size="small"
            variant="outlined"
            onClick={showAll}
            disabled={hiddenGenres.size === 0}
          />
          <Chip
            label="Hide All"
            size="small"
            variant="outlined"
            onClick={hideAll}
            disabled={hiddenGenres.size === distribution.length}
          />
        </Stack>
      </Box>

      {/* Genre chips */}
      <Stack direction="row" flexWrap="wrap" gap={0.5}>
        {distribution.map((d, idx) => {
          const isHidden = hiddenGenres.has(d.genre);
          const color = COLORS[idx % COLORS.length];
          return (
            <Chip
              key={d.genre}
              label={`${d.genre} (${d.count})`}
              size="small"
              onClick={() => toggleGenre(d.genre)}
              sx={{
                bgcolor: isHidden ? "transparent" : color,
                color: isHidden ? "text.secondary" : "#fff",
                border: isHidden ? 1 : 0,
                borderColor: "divider",
                textDecoration: isHidden ? "line-through" : "none",
                opacity: isHidden ? 0.6 : 1,
                "&:hover": {
                  bgcolor: isHidden ? "action.hover" : color,
                  opacity: 1,
                },
              }}
            />
          );
        })}
      </Stack>
    </AccordionSubsection>
  );
}
