/**
 * Per-head histogram distribution charts.
 *
 * Shows the raw embedding distribution as a bar chart with vertical lines
 * marking the p5 and p95 calibration values. Users can select which head
 * to display via a dropdown selector.
 *
 * This replaces the progressive convergence charts with a direct view of
 * the underlying data distribution, helping users assess whether their
 * library's embedding values are representative.
 */

import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Typography,
} from "@mui/material";
import { BarChart } from "@mui/x-charts/BarChart";
import { useMemo, useState } from "react";

import type { HeadHistogramResponse } from "@shared/api/calibration";

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

/** Strip model prefix: "effnet-20220825:mood_happy" → "mood_happy" */
function shortLabel(headKey: string): string {
  const colonIdx = headKey.indexOf(":");
  return colonIdx >= 0 ? headKey.slice(colonIdx + 1) : headKey;
}

/** Format a bin value for display (e.g., axis labels) */
function formatBinValue(val: number): string {
  if (Math.abs(val) >= 100) return val.toFixed(0);
  if (Math.abs(val) >= 10) return val.toFixed(1);
  return val.toFixed(2);
}
/**
 * Generate synthetic histogram bins for example patterns.
 * Creates realistic-looking distributions with controlled characteristics.
 */
function generateExampleBins(
  pattern: "healthy" | "focused" | "extreme" | "skewed" | "sparse",
  binCount = 25,
): { val: number; count: number }[] {
  const bins: { val: number; count: number }[] = [];
  const center = 50;
  const range = 100;

  switch (pattern) {
    case "healthy": {
      // Bell curve with reasonable spread
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        const distance = Math.abs(val - center);
        const count = Math.max(0, Math.floor(100 * Math.exp(-Math.pow(distance / 20, 2))));
        if (count > 0) bins.push({ val, count });
      }
      break;
    }

    case "focused": {
      // 60% of values in 30% of range (normal for genre-focused libraries)
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        const distance = Math.abs(val - center);
        let count = 0;
        if (distance < 15) {
          // Tight cluster
          count = Math.floor(80 * Math.exp(-Math.pow(distance / 8, 2)));
        } else if (distance < 35) {
          // Some spread
          count = Math.floor(20 * Math.exp(-Math.pow((distance - 15) / 10, 2)));
        }
        if (count > 0) bins.push({ val, count });
      }
      break;
    }

    case "extreme": {
      // 90%+ in tiny range (problematic)
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        const distance = Math.abs(val - center);
        const count = distance < 5 ? Math.floor(100 - distance * 5) : 0;
        if (count > 0) bins.push({ val, count });
      }
      break;
    }

    case "skewed": {
      // Smooth distribution weighted to one side
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        // Exponential decay from low end
        const count = Math.floor(80 * Math.exp(-val / 30));
        if (count > 0) bins.push({ val, count });
      }
      break;
    }

    case "sparse": {
      // Large gaps, uneven distribution
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        let count = 0;
        // Only populate select bins (creating gaps)
        if (val < 15 || (val > 40 && val < 50) || val > 85) {
          count = Math.floor(Math.random() * 40 + 10);
        }
        if (count > 0) bins.push({ val, count });
      }
      break;
    }
  }

  return bins;
}

/**
 * Example histogram patterns for user education.
 * Shows common distribution shapes and what they mean.
 */
const EXAMPLE_HISTOGRAMS: ExampleHistogramData[] = [
  {
    label: "✅ Healthy Spread",
    severity: "success",
    description:
      "Your library has good variety across this quality. Values are spread across the range with reasonable peaks. " +
      "The P5/P95 boundaries capture the full spectrum of your music, and calibration should work well for filtering and recommendations.",
    bins: generateExampleBins("healthy"),
    p5: 25,
    p95: 75,
  },
  {
    label: "ℹ️ Genre-Focused (Normal)",
    severity: "info",
    description:
      "Your music clusters in one region - this is completely normal for focused libraries! " +
      "Classical collections cluster high on 'acoustic', electronic/EDM clusters low. " +
      "Metal libraries cluster high on 'aggressive' and 'energy'. " +
      "As long as you have 5,000+ songs in the cluster, calibration will still work fine for your collection.",
    bins: generateExampleBins("focused"),
    p5: 38,
    p95: 62,
  },
  {
    label: "⚠️ Extreme Clustering (Concerning)",
    severity: "warning",
    description:
      "Almost all your values (90%+) are in a tiny range with very little variation. " +
      "If this is unexpected for the head you're viewing, it might indicate a tagging issue or data problem. " +
      "For heads like 'mood' or 'genre', you'd normally expect more spread even in focused libraries.",
    bins: generateExampleBins("extreme"),
    p5: 48,
    p95: 52,
  },
  {
    label: "ℹ️ Natural Skew (Normal)",
    severity: "info",
    description:
      "Your library leans heavily toward one end but has a smooth distribution. " +
      "This is expected for some qualities - ambient/classical libraries naturally skew low on 'danceability', " +
      "acoustic libraries skew high on 'acoustic', etc. " +
      "Nothing to worry about as long as you have 1,000+ songs.",
    bins: generateExampleBins("skewed"),
    p5: 5,
    p95: 40,
  },
  {
    label: "⚠️ Insufficient Data",
    severity: "warning",
    description:
      "Your library has large gaps or very few samples (under 1,000 songs) combined with extreme clustering. " +
      "Calibration might not be representative. Consider: " +
      "(1) scanning more music, (2) adding more variety, or " +
      "(3) understanding that tags may be less accurate for music very different from your library.",
    bins: generateExampleBins("sparse"),
    p5: 8,
    p95: 88,
  },
];

// ──────────────────────────────────────────────────────────────────────
// Data transformation
// ──────────────────────────────────────────────────────────────────────

interface ProcessedHistogram {
  xLabels: string[];
  counts: number[];
  binValues: number[];
  p5Index: number | null;
  p95Index: number | null;
}

interface ExampleHistogramData {
  label: string;
  severity: "success" | "info" | "warning";
  description: string;
  bins: { val: number; count: number }[];
  p5: number;
  p95: number;
}

/**
 * Process histogram bins for display.
 * Finds the indices of bins closest to p5/p95 for marker placement.
 */
function processHistogram(head: HeadHistogramResponse): ProcessedHistogram {
  const bins = Array.isArray(head?.histogram_bins) ? head.histogram_bins : [];
  if (bins.length === 0) {
    return { xLabels: [], counts: [], binValues: [], p5Index: null, p95Index: null };
  }

  // Sort bins by value for proper display order
  const sortedBins = [...bins].sort((a, b) => a.val - b.val);

  const xLabels = sortedBins.map((b) => formatBinValue(b.val));
  const counts = sortedBins.map((b) => b.count);
  const binValues = sortedBins.map((b) => b.val);

  // Find indices closest to p5/p95
  let p5Index: number | null = null;
  let p95Index: number | null = null;
  let p5Dist = Infinity;
  let p95Dist = Infinity;

  binValues.forEach((val, i) => {
    const d5 = Math.abs(val - head.p5);
    const d95 = Math.abs(val - head.p95);
    if (d5 < p5Dist) {
      p5Dist = d5;
      p5Index = i;
    }
    if (d95 < p95Dist) {
      p95Dist = d95;
      p95Index = i;
    }
  });

  return { xLabels, counts, binValues, p5Index, p95Index };
}

// ──────────────────────────────────────────────────────────────────────
// Reference line component (p5/p95 markers)
// ──────────────────────────────────────────────────────────────────────

interface ReferenceLineProps {
  label: string;
  value: number;
  color: string;
}

function ReferenceLineInfo({ label, value, color }: ReferenceLineProps) {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <Box
        sx={{
          width: 16,
          height: 3,
          bgcolor: color,
          borderRadius: 1,
        }}
      />
      <Typography variant="body2" color="text.secondary">
        {label}: <strong>{formatBinValue(value)}</strong>
      </Typography>
    </Box>
  );
}

// ──────────────────────────────────────────────────────────────────────

// ──────────────────────────────────────────────────────────────────────
// Example Histogram Mini-Component
// ──────────────────────────────────────────────────────────────────────

interface ExampleHistogramProps {
  example: ExampleHistogramData;
}

function ExampleHistogram({ example }: ExampleHistogramProps) {
  // Process bins for display
  const xLabels = example.bins.map((b) => formatBinValue(b.val));
  const counts = example.bins.map((b) => b.count);

  // Map severity to border color
  const borderColor = example.severity === "success" 
    ? "success.main" 
    : example.severity === "warning" 
    ? "warning.main" 
    : "info.main";

  return (
    <Box
      sx={{
        border: 2,
        borderColor: borderColor,
        borderRadius: 1,
        p: 2,
        backgroundColor: "background.paper",
      }}
    >
      <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
        {example.label}
      </Typography>

      {/* Mini bar chart */}
      <Box sx={{ height: 180, mb: 2 }}>
        <BarChart
          height={180}
          xAxis={[
            {
              scaleType: "band",
              data: xLabels,
              tickLabelStyle: { fontSize: 8 },
              tickLabelInterval: (_value, index) => index % Math.ceil(xLabels.length / 10) === 0,
            },
          ]}
          series={[
            {
              data: counts,
              color: example.severity === "success" 
                ? "#90ee90" 
                : example.severity === "warning" 
                ? "#ffcc80" 
                : "#90caf9",
            },
          ]}
          hideLegend
          margin={{ left: 40, right: 10, top: 10, bottom: 30 }}
        />
      </Box>

      {/* P5/P95 indicators */}
      <Box sx={{ display: "flex", gap: 2, mb: 1.5 }}>
        <Typography variant="caption" color="text.secondary">
          P5: <strong>{formatBinValue(example.p5)}</strong>
        </Typography>
        <Typography variant="caption" color="text.secondary">
          P95: <strong>{formatBinValue(example.p95)}</strong>
        </Typography>
      </Box>

      {/* Description */}
      <Typography variant="body2" color="text.secondary">
        {example.description}
      </Typography>
    </Box>
  );
}
// Component
// ──────────────────────────────────────────────────────────────────────

interface HistogramChartsProps {
  data: HeadHistogramResponse[] | null;
  loading: boolean;
  error: string | null;
}

export function HistogramCharts({ data, loading, error }: HistogramChartsProps) {
  // Track selected head (default to first)
  const headOptions = useMemo(() => {
    if (!data) return [];
    return data.map((h) => ({
      key: `${h.model_key}:${h.head_name}`,
      label: shortLabel(h.head_name),
      fullLabel: `${h.model_key}:${h.head_name}`,
    }));
  }, [data]);

  const [selectedHead, setSelectedHead] = useState<string>("");

  // Auto-select first head when data loads
  const effectiveSelected = selectedHead || headOptions[0]?.key || "";

  const selectedData = useMemo(() => {
    if (!data || !effectiveSelected) return null;
    return data.find((h) => `${h.model_key}:${h.head_name}` === effectiveSelected) ?? null;
  }, [data, effectiveSelected]);

  const processed = useMemo(
    () => (selectedData ? processHistogram(selectedData) : null),
    [selectedData],
  );

  if (loading) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, py: 2 }}>
        <CircularProgress size={20} />
        <Typography variant="body2">Loading histogram data...</Typography>
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

  if (!data || data.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No histogram data available. Run calibration to see distribution.
      </Typography>
    );
  }

  return (
    <Box>
      <Accordion defaultExpanded>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle1" fontWeight={500}>
            Embedding Distribution
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          {/* Head selector */}
          <Box sx={{ mb: 2 }}>
            <FormControl size="small" sx={{ minWidth: 200 }}>
              <InputLabel id="head-select-label">Head</InputLabel>
              <Select
                labelId="head-select-label"
                value={effectiveSelected}
                label="Head"
                onChange={(e) => setSelectedHead(e.target.value)}
              >
                {headOptions.map((opt) => (
                  <MenuItem key={opt.key} value={opt.key}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>

          {/* Description */}
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
            Distribution of embedding values across your library. P5/P95 markers show calibration
            percentiles.
          </Typography>

          {/* P5/P95 legend */}
          {selectedData && (
            <Box sx={{ display: "flex", gap: 3, mb: 2 }}>
              <ReferenceLineInfo label="P5" value={selectedData.p5} color="#2196f3" />
              <ReferenceLineInfo label="P95" value={selectedData.p95} color="#f44336" />
              <Typography variant="body2" color="text.secondary">
                Samples: <strong>{selectedData.n.toLocaleString()}</strong>
              </Typography>
            </Box>
          )}

          {/* Bar chart */}
          {processed && processed.counts.length > 0 ? (
            <BarChart
              height={350}
              xAxis={[
                {
                  scaleType: "band",
                  data: processed.xLabels,
                  label: "Embedding Value",
                  tickLabelStyle: { fontSize: 9 },
                  // Only show every Nth label to avoid crowding
                  tickLabelInterval: (_value, index) =>
                    index % Math.ceil(processed.xLabels.length / 20) === 0,
                },
              ]}
              series={[
                {
                  data: processed.counts,
                  label: "Count",
                  color: "#90caf9",
                },
              ]}
              hideLegend
              margin={{ left: 60, right: 20, top: 20, bottom: 60 }}
            />
          ) : (
            <Box sx={{ height: 350, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Typography color="text.secondary">No histogram data for selected head</Typography>
            </Box>
          )}
        </AccordionDetails>
      </Accordion>

      {/* Example patterns for user education */}
      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle1" fontWeight={500}>
            Understanding Your Results
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Common patterns and what they mean for your library. Compare your histogram above to these examples:
          </Typography>

          {/* Examples grid */}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "1fr",
                sm: "repeat(2, 1fr)",
                md: "repeat(3, 1fr)",
              },
              gap: 2,
            }}
          >
            {EXAMPLE_HISTOGRAMS.map((example) => (
              <ExampleHistogram key={example.label} example={example} />
            ))}
          </Box>
        </AccordionDetails>
      </Accordion>
    </Box>
  );
}
