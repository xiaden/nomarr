/**
 * Per-head convergence charts.
 *
 * Two line charts in an accordion:
 * 1. P5 & P95 values per head across progressive calibration iterations
 * 2. P5 & P95 deltas per head showing convergence
 *
 * Each head is its own series. X-axis is sample count (n), showing how
 * percentiles stabilize as more data is included (50% → 100%).
 *
 * Series are individually toggleable via colored chips. Click a chip to
 * hide/show that series. Y-axis auto-scales to visible series only.
 */

import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  CircularProgress,
  Typography,
} from "@mui/material";
import { LineChart } from "@mui/x-charts/LineChart";
import { useMemo, useState } from "react";

import type { CalibrationHistoryData } from "../hooks/useCalibrationHistory";

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

/** Strip model prefix: "effnet-20220825:mood_happy" → "mood_happy" */
function shortLabel(headKey: string): string {
  const colonIdx = headKey.indexOf(":");
  return colonIdx >= 0 ? headKey.slice(colonIdx + 1) : headKey;
}

const COLORS = [
  "#2196f3", "#f44336", "#4caf50", "#ff9800", "#9c27b0",
  "#00bcd4", "#e91e63", "#8bc34a", "#ff5722", "#3f51b5",
  "#009688", "#ffc107", "#673ab7", "#795548", "#607d8b",
];

interface LineSeries {
  data: (number | null)[];
  label: string;
  color: string;
  curve: "catmullRom";
  showMark: boolean;
}

// ──────────────────────────────────────────────────────────────────────
// Data transformation
// ──────────────────────────────────────────────────────────────────────

/**
 * Extract only the latest progressive run from a chronological snapshot array.
 * A new run starts when `n` drops (progressive goes 50%→100%, then restarts at 50%).
 * If `n` never drops, there's only one run — return all snapshots.
 */
function extractLatestRun(snapshots: CalibrationHistoryData[string]): CalibrationHistoryData[string] {
  if (snapshots.length <= 1) return snapshots;

  // Find the last index where n drops compared to previous (= start of latest run)
  let lastRunStart = 0;
  for (let i = 1; i < snapshots.length; i++) {
    if (snapshots[i].n < snapshots[i - 1].n) {
      lastRunStart = i;
    }
  }
  return snapshots.slice(lastRunStart);
}

function buildConvergenceSeries(historyData: CalibrationHistoryData) {
  const headKeys = Object.keys(historyData).sort();

  // Snapshots come DESC from API — reverse to chronological, then extract latest run
  const chronoData: Record<string, typeof historyData[string]> = {};
  for (const key of headKeys) {
    const chrono = [...historyData[key]].reverse();
    chronoData[key] = extractLatestRun(chrono);
  }

  // Find max iterations across all heads
  let maxIter = 0;
  for (const key of headKeys) {
    maxIter = Math.max(maxIter, chronoData[key].length);
  }

  if (maxIter === 0) {
    return { p5Series: [], p95Series: [], p5DeltaSeries: [], p95DeltaSeries: [], xLabels: [] };
  }

  // Build x-axis labels from sample counts of the first head with full data
  // Use "n" (sample count) as x-axis — shows convergence vs data volume
  const referenceHead = headKeys.find((k) => chronoData[k].length === maxIter) ?? headKeys[0];
  const xLabels = chronoData[referenceHead].map((snap) =>
    snap.n >= 1000 ? `${(snap.n / 1000).toFixed(1)}k` : String(snap.n),
  );

  const showMarks = maxIter <= 20;

  const p5Series: LineSeries[] = [];
  const p95Series: LineSeries[] = [];
  const p5DeltaSeries: LineSeries[] = [];
  const p95DeltaSeries: LineSeries[] = [];

  headKeys.forEach((key, headIdx) => {
    const snapshots = chronoData[key];
    const label = shortLabel(key);
    const color = COLORS[headIdx % COLORS.length];

    const p5Data: (number | null)[] = Array(maxIter).fill(null);
    const p95Data: (number | null)[] = Array(maxIter).fill(null);
    const p5DeltaData: (number | null)[] = Array(maxIter).fill(null);
    const p95DeltaData: (number | null)[] = Array(maxIter).fill(null);

    snapshots.forEach((snap, i) => {
      p5Data[i] = snap.p5;
      p95Data[i] = snap.p95;
      p5DeltaData[i] = snap.p5_delta;
      p95DeltaData[i] = snap.p95_delta;
    });

    p5Series.push({ data: p5Data, label: `${label} P5`, color, curve: "catmullRom", showMark: showMarks });
    p95Series.push({ data: p95Data, label: `${label} P95`, color, curve: "catmullRom", showMark: showMarks });
    p5DeltaSeries.push({ data: p5DeltaData, label: `${label} ΔP5`, color, curve: "catmullRom", showMark: showMarks });
    p95DeltaSeries.push({ data: p95DeltaData, label: `${label} ΔP95`, color, curve: "catmullRom", showMark: showMarks });
  });

  return { p5Series, p95Series, p5DeltaSeries, p95DeltaSeries, xLabels };
}

// ──────────────────────────────────────────────────────────────────────
// Series toggle chips
// ──────────────────────────────────────────────────────────────────────

interface SeriesTogglesProps {
  allSeries: LineSeries[];
  hiddenLabels: Set<string>;
  onToggle: (label: string) => void;
  onShowAll: () => void;
}

function SeriesToggles({ allSeries, hiddenLabels, onToggle, onShowAll }: SeriesTogglesProps) {
  const hiddenCount = allSeries.filter((s) => hiddenLabels.has(s.label)).length;

  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mb: 1 }}>
      {allSeries.map((series) => {
        const hidden = hiddenLabels.has(series.label);
        return (
          <Chip
            key={series.label}
            label={series.label}
            size="small"
            variant={hidden ? "outlined" : "filled"}
            onClick={() => onToggle(series.label)}
            sx={{
              height: 22,
              fontSize: 11,
              bgcolor: hidden ? "transparent" : series.color,
              color: hidden ? "text.secondary" : "#fff",
              borderColor: hidden ? series.color : undefined,
              opacity: hidden ? 0.5 : 1,
              "&:hover": {
                bgcolor: hidden ? `${series.color}22` : series.color,
                opacity: 1,
              },
            }}
          />
        );
      })}
      {hiddenCount > 0 && (
        <Chip
          label="Show all"
          size="small"
          variant="outlined"
          onClick={onShowAll}
          sx={{ height: 22, fontSize: 11 }}
        />
      )}
    </Box>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────────

interface ConvergenceChartsProps {
  data: CalibrationHistoryData | null;
  loading: boolean;
  error: string | null;
}

export function ConvergenceCharts({ data, loading, error }: ConvergenceChartsProps) {
  const { p5Series, p95Series, p5DeltaSeries, p95DeltaSeries, xLabels } = useMemo(
    () =>
      data
        ? buildConvergenceSeries(data)
        : { p5Series: [], p95Series: [], p5DeltaSeries: [], p95DeltaSeries: [], xLabels: [] },
    [data],
  );

  // Per-chart hidden series state
  const [hiddenValues, setHiddenValues] = useState<Set<string>>(new Set());
  const [hiddenDeltas, setHiddenDeltas] = useState<Set<string>>(new Set());

  const toggleValue = (label: string) => {
    setHiddenValues((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const toggleDelta = (label: string) => {
    setHiddenDeltas((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const showAllValues = () => setHiddenValues(new Set());
  const showAllDeltas = () => setHiddenDeltas(new Set());

  const hasSeries = p5Series.length > 0;

  // Filter series based on hidden state
  const allValueSeries = useMemo(() => [...p5Series, ...p95Series], [p5Series, p95Series]);
  const allDeltaSeries = useMemo(() => [...p5DeltaSeries, ...p95DeltaSeries], [p5DeltaSeries, p95DeltaSeries]);

  const visibleValueSeries = useMemo(
    () => allValueSeries.filter((s) => !hiddenValues.has(s.label)),
    [allValueSeries, hiddenValues],
  );
  const visibleDeltaSeries = useMemo(
    () => allDeltaSeries.filter((s) => !hiddenDeltas.has(s.label)),
    [allDeltaSeries, hiddenDeltas],
  );

  if (loading) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, py: 2 }}>
        <CircularProgress size={20} />
        <Typography variant="body2">Loading convergence history...</Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Typography color="error" variant="body2">
        {error}
      </Typography>
    );
  }

  if (!hasSeries) {
    return (
      <Typography variant="body2" color="text.secondary">
        No convergence history available. Run calibration to see progressive convergence.
      </Typography>
    );
  }

  return (
    <Box>
      {/* P5 / P95 values across progressive iterations */}
      <Accordion defaultExpanded>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle1" fontWeight={500}>
            P5 & P95 Per Head (Progressive Convergence)
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
            X-axis: sample count. Watch percentiles stabilize as more data is included.
          </Typography>
          <SeriesToggles
            allSeries={allValueSeries}
            hiddenLabels={hiddenValues}
            onToggle={toggleValue}
            onShowAll={showAllValues}
          />
          {visibleValueSeries.length > 0 ? (
            <LineChart
              height={350}
              xAxis={[{
                scaleType: "point",
                data: xLabels,
                label: "Samples",
                tickLabelStyle: { fontSize: 11 },
              }]}
              series={visibleValueSeries}
              hideLegend
              margin={{ left: 60, right: 20, top: 20, bottom: 50 }}
            />
          ) : (
            <Box sx={{ height: 350, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Typography color="text.secondary">All series hidden</Typography>
            </Box>
          )}
        </AccordionDetails>
      </Accordion>

      {/* Deltas — should converge toward 0 */}
      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle1" fontWeight={500}>
            P5 & P95 Deltas Per Head
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
            Delta between iterations. Values approaching 0 indicate convergence.
          </Typography>
          <SeriesToggles
            allSeries={allDeltaSeries}
            hiddenLabels={hiddenDeltas}
            onToggle={toggleDelta}
            onShowAll={showAllDeltas}
          />
          {visibleDeltaSeries.length > 0 ? (
            <LineChart
              height={350}
              xAxis={[{
                scaleType: "point",
                data: xLabels,
                label: "Samples",
                tickLabelStyle: { fontSize: 11 },
              }]}
              series={visibleDeltaSeries}
              hideLegend
              margin={{ left: 60, right: 20, top: 20, bottom: 50 }}
            />
          ) : (
            <Box sx={{ height: 350, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Typography color="text.secondary">All series hidden</Typography>
            </Box>
          )}
        </AccordionDetails>
      </Accordion>
    </Box>
  );
}
