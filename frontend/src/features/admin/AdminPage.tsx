/**
 * Admin page.
 *
 * Features:
 * - Worker control (pause/resume)
 * - Server restart
 */

import { ConfirmDialog } from "@shared/components/ui";
import { SystemControls } from "./components/SystemControls";
import { WorkerControls } from "./components/WorkerControls";
import { useAdminActions } from "./hooks/useAdminActions";

export function AdminPage() {
  const { actionLoading, handlePauseWorker, handleResumeWorker, handleRestart, dialogState } =
    useAdminActions();

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Admin</h1>

      <div style={{ display: "grid", gap: "20px" }}>
        <WorkerControls
          onPause={handlePauseWorker}
          onResume={handleResumeWorker}
          actionLoading={actionLoading}
        />
        <SystemControls onRestart={handleRestart} actionLoading={actionLoading} />
      </div>

      {/* Confirm dialog for admin actions */}
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
