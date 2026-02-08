/**
 * Calibration management page.
 *
 * Features:
 * - Generate new calibration from library data
 * - Apply calibration to library (recalibrate all files)
 * - View calibration status
 */

import { Alert, Box, CircularProgress, Stack, Typography } from "@mui/material";

import {
  ConfirmDialog,
  PageContainer,
  Panel,
  ProgressBar,
} from "@shared/components/ui";

import { CalibrationActions } from "./components/CalibrationActions";
import { CalibrationStatus } from "./components/CalibrationStatus";
import { ConvergenceSummary } from "./components/ConvergenceSummary";
import { ConvergenceTable } from "./components/ConvergenceTable";
import { useCalibrationStatus } from "./hooks/useCalibrationStatus";
import { useConvergenceStatus } from "./hooks/useConvergenceStatus";

export function CalibrationPage() {
  const {
    status,
    loading,
    error,
    actionLoading,
    generationState,
    handleGenerate,
    handleApply,
    handleUpdateFiles,
    dialogState,
  } = useCalibrationStatus();

  const {
    data: convergenceData,
    loading: convergenceLoading,
    error: convergenceError,
  } = useConvergenceStatus();

  const { isGenerating, progress } = generationState;

  return (
    <PageContainer title="Calibration">
      {loading && <CircularProgress />}
      {error && <Alert severity="error">Error: {error}</Alert>}

      {/* Generation progress panel */}
      {isGenerating && (
        <Panel sx={{ mb: 2.5 }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 2 }}>
            <CircularProgress size={20} />
            <Typography variant="subtitle1" fontWeight={500}>
              Generating Calibration...
            </Typography>
          </Box>
          {progress && progress.total_heads > 0 && (
            <ProgressBar
              label={`Processing heads`}
              value={progress.completed_heads}
              total={progress.total_heads}
            />
          )}
          {progress && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              {progress.completed_heads} / {progress.total_heads} heads
              {progress.remaining_heads > 0 &&
                ` (${progress.remaining_heads} remaining)`}
            </Typography>
          )}
        </Panel>
      )}

      {status && (
        <Stack spacing={2.5}>
          <CalibrationStatus status={status} />
          {convergenceLoading && (
            <Panel>
              <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
                <CircularProgress size={20} />
                <Typography variant="body2">Loading convergence data...</Typography>
              </Box>
            </Panel>
          )}
          {convergenceError && (
            <Alert severity="error">
              Failed to load convergence data: {convergenceError}
            </Alert>
          )}
          {convergenceData && (
            <>
              <ConvergenceSummary data={convergenceData} />
              <ConvergenceTable data={convergenceData} />
            </>
          )}
          <CalibrationActions
            onGenerate={handleGenerate}
            onApply={handleApply}
            onUpdateFiles={handleUpdateFiles}
            actionLoading={actionLoading || isGenerating}
          />
        </Stack>
      )}

      {/* Confirm dialog for calibration actions */}
      <ConfirmDialog
        open={dialogState.isOpen}
        title={dialogState.options.title}
        message={dialogState.options.message}
        confirmLabel={dialogState.options.confirmLabel}
        cancelLabel={dialogState.options.cancelLabel}
        severity={dialogState.options.severity}
        onConfirm={dialogState.handleConfirm}
        onCancel={dialogState.handleCancel}
      />
    </PageContainer>
  );
}
