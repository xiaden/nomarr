/**
 * Per-head histogram distribution charts.
 *
 * Shows the raw embedding distribution as a bar chart with vertical lines
 * marking the p5 and p95 calibration values. Users can select which head
 * to display via a dropdown selector.
 *
 * Key design constraint: EmbeddingHistogramChart is ALWAYS mounted from page
 * load (never conditionally removed). MUI X Charts caches its bounding rect
 * on mount; if the chart only mounts after the API response, the position is
 * measured mid-page-reflow and ends up stale (offset by ~sidebar width).
 * Loading/error/empty states use an absolute overlay instead.
 */

import {
  Box,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Typography,
  type SxProps,
  type Theme,
} from "@mui/material";
import { BarChart } from "@mui/x-charts/BarChart";
import { useEffect, useMemo, useState } from "react";

import type { HeadHistogramResponse } from "@shared/api/calibration";
import { AccordionSection } from "@shared/components/ui";
import { debugLog } from "@shared/utils/debug";

import { EmbeddingHistogramChart } from "./EmbeddingHistogramChart";

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
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        const distance = Math.abs(val - center);
        const count = Math.max(0, Math.floor(100 * Math.exp(-Math.pow(distance / 20, 2))));
        if (count > 0) bins.push({ val, count });
      }
      break;
    }
    case "focused": {
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        const distance = Math.abs(val - center);
        let count = 0;
        if (distance < 15) {
          count = Math.floor(80 * Math.exp(-Math.pow(distance / 8, 2)));
        } else if (distance < 35) {
          count = Math.floor(20 * Math.exp(-Math.pow((distance - 15) / 10, 2)));
        }
        if (count > 0) bins.push({ val, count });
      }
      break;
    }
    case "extreme": {
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        const distance = Math.abs(val - center);
        const count = distance < 5 ? Math.floor(100 - distance * 5) : 0;
        if (count > 0) bins.push({ val, count });
      }
      break;
    }
    case "skewed": {
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        const count = Math.floor(80 * Math.exp(-val / 30));
        if (count > 0) bins.push({ val, count });
      }
      break;
    }
    case "sparse": {
      for (let i = 0; i < binCount; i++) {
        const val = (i / binCount) * range;
        let count = 0;
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

// ──────────────────────────────────────────────────────────────────────
// Types
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

function processHistogram(head: HeadHistogramResponse): ProcessedHistogram {
  const bins = Array.isArray(head?.histogram_bins) ? head.histogram_bins : [];
  if (bins.length === 0) {
    return { xLabels: [], counts: [], binValues: [], p5Index: null, p95Index: null };
  }

  const sortedBins = [...bins].sort((a, b) => a.val - b.val);

  // Aggregate bins that share the same formatted label.
  // The backend stores up to 10,000 fine-grained bins (0.0001 width each),
  // but toFixed(2) collapses many into the same label string ("0.00", "0.01"…).
  // Passing 10,000 items to MUI X Charts' band scale divides the container
  // width by 10,000, making hover hit-detection wildly wrong.
  const aggregated = new Map<string, { totalCount: number; representativeVal: number }>();
  for (const b of sortedBins) {
    const label = formatBinValue(b.val);
    const existing = aggregated.get(label);
    if (existing) {
      existing.totalCount += b.count;
    } else {
      aggregated.set(label, { totalCount: b.count, representativeVal: b.val });
    }
  }

  const xLabels = [...aggregated.keys()];
  const counts = [...aggregated.values()].map((v) => v.totalCount);
  const binValues = [...aggregated.values()].map((v) => v.representativeVal);

  let p5Index: number | null = null;
  let p95Index: number | null = null;
  let p5Dist = Infinity;
  let p95Dist = Infinity;

  binValues.forEach((val, i) => {
    const d5 = Math.abs(val - head.p5);
    const d95 = Math.abs(val - head.p95);
    if (d5 < p5Dist) { p5Dist = d5; p5Index = i; }
    if (d95 < p95Dist) { p95Dist = d95; p95Index = i; }
  });

  return { xLabels, counts, binValues, p5Index, p95Index };
}

// ──────────────────────────────────────────────────────────────────────
// Reference line info
// ──────────────────────────────────────────────────────────────────────

function ReferenceLineInfo({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <Box sx={{ width: 16, height: 3, bgcolor: color, borderRadius: 1 }} />
      <Typography variant="body2" color="text.secondary">
        {label}: <strong>{formatBinValue(value)}</strong>
      </Typography>
    </Box>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Example mini-chart
// ──────────────────────────────────────────────────────────────────────

function ExampleHistogram({ example }: { example: ExampleHistogramData }) {
  const xLabels = example.bins.map((b) => formatBinValue(b.val));
  const counts = example.bins.map((b) => b.count);
  const borderColor =
    example.severity === "success" ? "success.main" :
    example.severity === "warning" ? "warning.main" : "info.main";
  const barColor =
    example.severity === "success" ? "#90ee90" :
    example.severity === "warning" ? "#ffcc80" : "#90caf9";

  return (
    <Box sx={{ border: 2, borderColor, borderRadius: 1, p: 2, backgroundColor: "background.paper" }}>
      <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
        {example.label}
      </Typography>
      <Box sx={{ height: 180, mb: 2 }}>
        <BarChart
          height={180}
          xAxis={[{
            scaleType: "band",
            data: xLabels,
            tickLabelStyle: { fontSize: 8 },
            tickLabelInterval: (_value, index) => index % Math.ceil(xLabels.length / 10) === 0,
          }]}
          series={[{ data: counts, color: barColor }]}
          hideLegend
          margin={{ left: 40, right: 10, top: 10, bottom: 30 }}
        />
      </Box>
      <Box sx={{ display: "flex", gap: 2, mb: 1.5 }}>
        <Typography variant="caption" color="text.secondary">
          P5: <strong>{formatBinValue(example.p5)}</strong>
        </Typography>
        <Typography variant="caption" color="text.secondary">
          P95: <strong>{formatBinValue(example.p95)}</strong>
        </Typography>
      </Box>
      <Typography variant="body2" color="text.secondary">
        {example.description}
      </Typography>
    </Box>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Main component
// ──────────────────────────────────────────────────────────────────────

interface HistogramChartsProps {
  data: HeadHistogramResponse[] | null;
  loading: boolean;
  error: string | null;
  sx?: SxProps<Theme>;
}

export function HistogramCharts({ data, loading, error, sx }: HistogramChartsProps) {
  const TAG = "HistogramCharts";

  const headOptions = useMemo(() => {
    if (!data) return [];
    return data.map((h) => ({
      key: `${h.model_key}:${h.head_name}:${h.label}`,
      label: `${shortLabel(h.head_name)} - ${h.label}`,
    }));
  }, [data]);

  const [selectedHead, setSelectedHead] = useState<string>("");
  const effectiveSelected = selectedHead || headOptions[0]?.key || "";

  const selectedData = useMemo(() => {
    if (!data || !effectiveSelected) return null;
    return data.find((h) => `${h.model_key}:${h.head_name}:${h.label}` === effectiveSelected) ?? null;
  }, [data, effectiveSelected]);

  const processed = useMemo(
    () => (selectedData ? processHistogram(selectedData) : null),
    [selectedData],
  );

  useEffect(() => {
    debugLog(TAG, "mount/update", { loading, error, headCount: data?.length ?? 0, selectedHead: effectiveSelected });
  }, [loading, error, data, effectiveSelected]);

  const hasData = !loading && !error && data != null && data.length > 0;
  const hasChart = hasData && processed != null && processed.counts.length > 0;

  // ── Understanding section (static) ────────────────────────────────────
  const understandingSection = (
    <AccordionSection
      sectionId="calibration:histogram:understanding"
      title="Understanding Your Results"
      defaultExpanded={false}
    >
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Common patterns and what they mean for your library. Compare your histogram above to these examples:
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", md: "repeat(3, 1fr)" },
          gap: 2,
        }}
      >
        {EXAMPLE_HISTOGRAMS.map((example) => (
          <ExampleHistogram key={example.label} example={example} />
        ))}
      </Box>
    </AccordionSection>
  );

  // ── Not-ready states ──────────────────────────────────────────────────
  if (!hasChart) {
    return (
      <Box sx={sx}>
        <AccordionSection sectionId="calibration:histogram:embedding" title="Embedding Distribution">
          {loading && (
            <Box sx={{ display: "flex", alignItems: "center", gap: 2, py: 2 }}>
              <CircularProgress size={20} />
              <Typography variant="body2">Loading histogram data...</Typography>
            </Box>
          )}
          {!loading && error && (
            <Typography color="error" variant="body2" sx={{ py: 1 }}>{error}</Typography>
          )}
          {!loading && !error && (
            <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
              No histogram data available. Run calibration to see distribution.
            </Typography>
          )}
        </AccordionSection>
        {understandingSection}
      </Box>
    );
  }

  // ── Data-ready state ──────────────────────────────────────────────────
  return (
    <Box sx={sx}>
      <AccordionSection sectionId="calibration:histogram:embedding" title="Embedding Distribution">
        <Box sx={{ mb: 2 }}>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel id="head-select-label">Label</InputLabel>
            <Select
              labelId="head-select-label"
              value={effectiveSelected}
              label="Label"
              onChange={(e) => setSelectedHead(e.target.value)}
            >
              {headOptions.map((opt) => (
                <MenuItem key={opt.key} value={opt.key}>{opt.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>

        <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
          Distribution of embedding values across your library. P5/P95 markers show calibration percentiles.
        </Typography>

        {selectedData && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" fontWeight={500} color="text.primary" sx={{ mb: 1 }}>
              {shortLabel(selectedData.head_name)} - {selectedData.label}
            </Typography>
            <Box sx={{ display: "flex", gap: 3 }}>
              <ReferenceLineInfo label="P5" value={selectedData.p5} color="#2196f3" />
              <ReferenceLineInfo label="P95" value={selectedData.p95} color="#f44336" />
              <Typography variant="body2" color="text.secondary">
                Samples: <strong>{selectedData.n.toLocaleString()}</strong>
              </Typography>
            </Box>
          </Box>
        )}

        <EmbeddingHistogramChart
          key={effectiveSelected}
          xLabels={processed.xLabels}
          counts={processed.counts}
        />
      </AccordionSection>
      {understandingSection}
    </Box>
  );
}
