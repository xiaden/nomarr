/**
 * Calibration management page.
 *
 * Features:
 * - Generate new calibration from library data
 * - Apply calibration to library (recalibrate all files)
 * - View calibration queue status
 * - Clear calibration queue
 */

import { Alert, CircularProgress, Stack } from "@mui/material";

import { ConfirmDialog, PageContainer } from "@shared/components/ui";
import { CalibrationActions } from "./components/CalibrationActions";
import { CalibrationStatus } from "./components/CalibrationStatus";
import { useCalibrationStatus } from "./hooks/useCalibrationStatus";

export function CalibrationPage() {
  const {
    status,
    loading,
    error,
    actionLoading,
    handleGenerate,
    handleApply,
    handleClear,
    dialogState,
  } = useCalibrationStatus();

  return (
    <PageContainer title="Calibration">
      {loading && <CircularProgress />}
      {error && <Alert severity="error">Error: {error}</Alert>}

      {status && (
        <Stack spacing={2.5}>
          <CalibrationStatus status={status} />
          <CalibrationActions
            onGenerate={handleGenerate}
            onApply={handleApply}
            onClear={handleClear}
            actionLoading={actionLoading}
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
