/**
 * InteractiveChart - Reusable chart component with type switching and value filtering.
 *
 * Features:
 * - Toggle between chart types: vertical bar, horizontal bar, line, pie
 * - Icon toggle group for chart type selection
 * - Optional value filtering: click chart items to hide them, click chips to re-add
 * - Consistent data shape: { label, value }[]
 */

import {
  AlignHorizontalLeft,
  BarChart as BarChartIcon,
  PieChart as PieChartIcon,
  ShowChart,
} from "@mui/icons-material";
import {
  Box,
  Chip,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { BarChart } from "@mui/x-charts/BarChart";
import { LineChart } from "@mui/x-charts/LineChart";
import { PieChart } from "@mui/x-charts/PieChart";
import { useMemo, useState } from "react";

// ──────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────

export interface ChartItem {
  label: string;
  value: number;
}

export type ChartType = "vertical" | "horizontal" | "line" | "pie";

export interface InteractiveChartProps {
  /** Data to display. Must be pre-sorted by caller. */
  data: ChartItem[];
  /** Initial chart type. User can toggle between types. */
  initialChartType: ChartType;
  /** When true, users can click items to filter them out. */
  filterable?: boolean;
  /** Chart height in pixels. */
  height?: number;
  /** Called when the chart type changes. */
  onChartTypeChange?: (type: ChartType) => void;
}

// ──────────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────────

const CHART_TYPES: { value: ChartType; icon: React.ReactNode; tooltip: string }[] = [
  { value: "vertical", icon: <BarChartIcon fontSize="small" />, tooltip: "Vertical bars" },
  { value: "horizontal", icon: <AlignHorizontalLeft fontSize="small" />, tooltip: "Horizontal bars" },
  { value: "line", icon: <ShowChart fontSize="small" />, tooltip: "Line chart" },
  { value: "pie", icon: <PieChartIcon fontSize="small" />, tooltip: "Pie chart" },
];

// ──────────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────────

export function InteractiveChart({
  data,
  initialChartType,
  filterable = false,
  height = 300,
  onChartTypeChange,
}: InteractiveChartProps) {
  const [chartType, setChartType] = useState<ChartType>(initialChartType);
  const [hiddenLabels, setHiddenLabels] = useState<Set<string>>(new Set());

  // Filtered data (visible items only)
  const visibleData = useMemo(
    () => data.filter((d) => !hiddenLabels.has(d.label)),
    [data, hiddenLabels],
  );

  // Sorted hidden items (for chip display)
  const hiddenItems = useMemo(
    () => data.filter((d) => hiddenLabels.has(d.label)),
    [data, hiddenLabels],
  );

  // ── Handlers ──────────────────────────────────────────────────────

  const handleChartTypeChange = (
    _event: React.MouseEvent<HTMLElement>,
    newType: ChartType | null,
  ) => {
    if (newType !== null) {
      setChartType(newType);
      onChartTypeChange?.(newType);
    }
  };

  const hideItem = (label: string) => {
    if (!filterable) return;
    setHiddenLabels((prev) => new Set(prev).add(label));
  };

  const showItem = (label: string) => {
    setHiddenLabels((prev) => {
      const next = new Set(prev);
      next.delete(label);
      return next;
    });
  };

  const showAll = () => setHiddenLabels(new Set());

  // ── Click handler for chart items ─────────────────────────────────

  const handleBarClick = (
    _event: React.MouseEvent,
    barItem: { dataIndex: number; seriesId: string | number },
  ) => {
    if (!filterable) return;
    const item = visibleData[barItem.dataIndex];
    if (item) hideItem(item.label);
  };

  // Pie click has a different signature
  const handlePieClick = (
    _event: React.MouseEvent,
    itemIdentifier: { dataIndex: number },
  ) => {
    if (!filterable) return;
    const item = visibleData[itemIdentifier.dataIndex];
    if (item) hideItem(item.label);
  };

  // ── Render helpers ────────────────────────────────────────────────

  const labels = visibleData.map((d) => d.label);
  const values = visibleData.map((d) => d.value);

  const renderChart = () => {
    if (visibleData.length === 0) {
      return (
        <Box
          sx={{
            height,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Typography color="text.secondary">
            No data to display
          </Typography>
        </Box>
      );
    }

    switch (chartType) {
      case "vertical":
        return (
          <BarChart
            height={height}
            xAxis={[
              {
                scaleType: "band" as const,
                data: labels,
                tickLabelStyle: {
                  angle: labels.length > 8 ? -45 : 0,
                  textAnchor: labels.length > 8 ? "end" : "middle",
                  fontSize: 11,
                },
              },
            ]}
            series={[{ data: values }]}
            onItemClick={handleBarClick}
            margin={{
              left: 50,
              right: 20,
              top: 20,
              bottom: labels.length > 8 ? 80 : 40,
            }}
          />
        );

      case "horizontal":
        return (
          <BarChart
            height={height}
            layout="horizontal"
            yAxis={[
              {
                scaleType: "band" as const,
                data: labels,
                tickLabelStyle: { fontSize: 11 },
              },
            ]}
            series={[{ data: values }]}
            onItemClick={handleBarClick}
            margin={{ left: 100, right: 20, top: 20, bottom: 30 }}
          />
        );

      case "line":
        return (
          <LineChart
            height={height}
            xAxis={[
              {
                scaleType: "point" as const,
                data: labels,
                tickLabelStyle: {
                  angle: labels.length > 12 ? -45 : 0,
                  textAnchor: labels.length > 12 ? "end" : "middle",
                  fontSize: 11,
                },
              },
            ]}
            series={[
              {
                data: values,
                curve: "catmullRom",
                showMark: visibleData.length <= 30,
              },
            ]}
            margin={{
              left: 50,
              right: 20,
              top: 20,
              bottom: labels.length > 12 ? 80 : 40,
            }}
          />
        );

      case "pie":
        return (
          <PieChart
            height={height}
            series={[
              {
                data: visibleData.map((d, i) => ({
                  id: i,
                  value: d.value,
                  label: d.label,
                })),
                innerRadius: 25,
                outerRadius: Math.min(height / 2 - 20, 120),
                paddingAngle: 1,
                cornerRadius: 3,
              },
            ]}
            onItemClick={handlePieClick}
            hideLegend
          />
        );
    }
  };

  // ── Main render ───────────────────────────────────────────────────

  return (
    <Box>
      {/* Chart type toggle */}
      <Box sx={{ display: "flex", justifyContent: "flex-end", mb: 1 }}>
        <ToggleButtonGroup
          value={chartType}
          exclusive
          onChange={handleChartTypeChange}
          size="small"
          sx={{ height: 28 }}
        >
          {CHART_TYPES.map((ct) => (
            <ToggleButton
              key={ct.value}
              value={ct.value}
              title={ct.tooltip}
              sx={{ px: 1 }}
            >
              {ct.icon}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
      </Box>

      {/* Chart */}
      {renderChart()}

      {/* Hidden items chips (filter mode) */}
      {filterable && hiddenItems.length > 0 && (
        <Box sx={{ mt: 1.5 }}>
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.5,
              mb: 0.5,
            }}
          >
            <Typography variant="caption" color="text.secondary">
              Hidden ({hiddenItems.length})
            </Typography>
            <Chip
              label="Show all"
              size="small"
              variant="outlined"
              onClick={showAll}
              sx={{ height: 20, fontSize: 11 }}
            />
          </Box>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
            {hiddenItems.map((item) => (
              <Chip
                key={item.label}
                label={`${item.label} (${item.value.toLocaleString()})`}
                size="small"
                onClick={() => showItem(item.label)}
                sx={{ height: 22, fontSize: 11 }}
              />
            ))}
          </Box>
        </Box>
      )}
    </Box>
  );
}
