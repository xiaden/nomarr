/**
 * Main Tag Co-Occurrence Grid component.
 * Preset-first UI with automatic axis population and manual override option.
 */

import { Alert, Box, CircularProgress, Stack } from "@mui/material";
import type { JSX } from "react";
import { useCallback, useEffect, useState } from "react";

import { Panel, SectionHeader } from "@shared/components/ui";

import { getTagCoOccurrence } from "../../../../shared/api/analytics";

import { ColorLegend } from "./ColorLegend";
import { HeatmapCell } from "./HeatmapCell";
import { ManualTagSelector } from "./ManualTagSelector";
import { PresetSelector } from "./PresetSelector";
import type { MatrixData, TagCoOccurrenceGridProps } from "./types";
import { useAxisState } from "./useAxisState";

export function TagCoOccurrenceGrid({
  libraryId,
}: TagCoOccurrenceGridProps): JSX.Element {
  const {
    state,
    selectPreset,
    swapAxes,
    addManualTag,
    removeTag,
    isLoading,
    canBuildMatrix,
  } = useAxisState();

  const [matrix, setMatrix] = useState<MatrixData | null>(null);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [matrixError, setMatrixError] = useState<string | null>(null);

  // Build matrix when axes change
  const buildMatrix = useCallback(async () => {
    if (!canBuildMatrix) {
      setMatrix(null);
      return;
    }

    try {
      setMatrixLoading(true);
      setMatrixError(null);

      const result = await getTagCoOccurrence(
        {
          x: state.x.tags,
          y: state.y.tags,
        },
        libraryId
      );

      setMatrix(result);
    } catch (err) {
      setMatrixError(
        err instanceof Error ? err.message : "Failed to build matrix"
      );
      setMatrix(null);
    } finally {
      setMatrixLoading(false);
    }
  }, [canBuildMatrix, state.x.tags, state.y.tags, libraryId]);

  // Auto-build matrix when tags change
  useEffect(() => {
    void buildMatrix();
  }, [buildMatrix]);

  const getHeatmapColor = (value: number, max: number): string => {
    if (value === 0) return "#1a1a1a";
    const intensity = Math.min(value / max, 1);
    // Blue gradient for dark theme
    const r = Math.floor(30 + intensity * 44);
    const g = Math.floor(30 + intensity * 128);
    const b = Math.floor(30 + intensity * 225);
    return `rgb(${r}, ${g}, ${b})`;
  };

  const maxValue = matrix?.matrix ? Math.max(...matrix.matrix.flat(), 1) : 1;

  const anyLoading = isLoading || matrixLoading;

  return (
    <Panel>
      <SectionHeader title="Tag Co-Occurrence Grid" />

      <Stack spacing={2} sx={{ mb: 2 }}>
        {/* X Axis Preset Selector */}
        <PresetSelector
          label="X Axis:"
          value={state.x.preset}
          onChange={(presetId) => selectPreset("x", presetId)}
          loading={anyLoading}
        />

        {/* Y Axis Preset Selector with Swap Button */}
        <PresetSelector
          label="Y Axis:"
          value={state.y.preset}
          onChange={(presetId) => selectPreset("y", presetId)}
          showSwap
          onSwap={swapAxes}
          loading={anyLoading}
        />

        {/* Manual Tag Selector Accordion */}
        <ManualTagSelector
          xTags={state.x.tags}
          yTags={state.y.tags}
          xIsManual={state.x.preset === "manual"}
          yIsManual={state.y.preset === "manual"}
          onAddToX={(tag) => addManualTag("x", tag)}
          onAddToY={(tag) => addManualTag("y", tag)}
          onRemoveFromX={(index) => removeTag("x", index)}
          onRemoveFromY={(index) => removeTag("y", index)}
        />
      </Stack>

      {/* Error Display */}
      {matrixError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {matrixError}
        </Alert>
      )}

      {/* Loading State */}
      {anyLoading && (
        <Box
          sx={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            py: 4,
          }}
        >
          <CircularProgress size={32} />
        </Box>
      )}

      {/* Matrix Display */}
      {!anyLoading && matrix && (
        <Box sx={{ overflowX: "auto" }}>
          <Box
            component="table"
            sx={{
              borderCollapse: "separate",
              borderSpacing: 0,
              width: "100%",
              minWidth: 300,
              fontSize: "0.875rem",
            }}
          >
            {/* Header Row */}
            <Box component="thead">
              <Box component="tr">
                {/* Corner cell - sticky top-left */}
                <Box
                  component="th"
                  sx={{
                    position: "sticky",
                    top: 0,
                    left: 0,
                    zIndex: 3,
                    bgcolor: "background.paper",
                    borderBottom: 2,
                    borderRight: 2,
                    borderColor: "divider",
                    p: 1,
                    fontWeight: 600,
                    minWidth: 100,
                  }}
                >
                  Y \ X
                </Box>

                {/* Column headers - sticky top */}
                {matrix.x.map((tag, index) => (
                  <Box
                    component="th"
                    key={index}
                    sx={{
                      position: "sticky",
                      top: 0,
                      zIndex: 2,
                      bgcolor: "background.paper",
                      borderBottom: 2,
                      borderColor: "divider",
                      p: 1,
                      fontWeight: 600,
                      whiteSpace: "nowrap",
                      minWidth: 80,
                    }}
                    title={`${tag.key}: ${tag.value}`}
                  >
                    {tag.value}
                  </Box>
                ))}
              </Box>
            </Box>

            {/* Data Rows */}
            <Box component="tbody">
              {matrix.y.map((yTag, yIndex) => (
                <Box component="tr" key={yIndex}>
                  {/* Row header - sticky left */}
                  <Box
                    component="th"
                    sx={{
                      position: "sticky",
                      left: 0,
                      zIndex: 1,
                      bgcolor: "background.paper",
                      borderRight: 2,
                      borderColor: "divider",
                      p: 1,
                      fontWeight: 600,
                      textAlign: "left",
                      whiteSpace: "nowrap",
                    }}
                    title={`${yTag.key}: ${yTag.value}`}
                  >
                    {yTag.value}
                  </Box>

                  {/* Data cells with tooltips */}
                  {matrix.x.map((xTag, xIndex) => (
                    <HeatmapCell
                      key={xIndex}
                      xTag={xTag}
                      yTag={yTag}
                      count={matrix.matrix[yIndex][xIndex]}
                      maxCount={maxValue}
                      bgcolor={getHeatmapColor(
                        matrix.matrix[yIndex][xIndex],
                        maxValue
                      )}
                    />
                  ))}
                </Box>
              ))}
            </Box>
          </Box>

          {/* Color Legend */}
          <ColorLegend maxValue={maxValue} />
        </Box>
      )}

      {/* Empty State */}
      {!anyLoading && !matrix && !matrixError && (
        <Box
          sx={{
            py: 4,
            textAlign: "center",
            color: "text.secondary",
          }}
        >
          {canBuildMatrix
            ? "No matching files found"
            : "Select presets or add tags to build matrix"}
        </Box>
      )}
    </Panel>
  );
}
