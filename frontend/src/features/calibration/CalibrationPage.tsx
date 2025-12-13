/**
 * Calibration management page.
 *
 * Features:
 * - Generate new calibration from library data
 * - Apply calibration to library (recalibrate all files)
 * - View calibration queue status
 * - Clear calibration queue
 */

import { ConfirmDialog } from "@shared/components/ui";
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
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Calibration</h1>

      {loading && <p>Loading calibration status...</p>}
      {error && <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>}

      {status && (
        <div style={{ display: "grid", gap: "20px" }}>
          <CalibrationStatus status={status} />
          <CalibrationActions
            onGenerate={handleGenerate}
            onApply={handleApply}
            onClear={handleClear}
            actionLoading={actionLoading}
          />
        </div>
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
    </div>
  );
}
