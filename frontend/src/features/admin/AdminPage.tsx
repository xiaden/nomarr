/**
 * Admin page.
 *
 * Features:
 * - Worker control (pause/resume)
 * - Server restart
 * - Inspect tags (debug tool)
 */

import { Stack } from "@mui/material";

import { ConfirmDialog, PageContainer } from "@shared/components/ui";

import { InspectTags } from "./components/InspectTags";
import { SystemControls } from "./components/SystemControls";
import { WorkerControls } from "./components/WorkerControls";
import { useAdminActions } from "./hooks/useAdminActions";

export function AdminPage() {
  const { actionLoading, handlePauseWorker, handleResumeWorker, handleRestart, dialogState } =
    useAdminActions();

  return (
    <PageContainer title="Admin">
      <Stack spacing={2.5}>
        <WorkerControls
          onPause={handlePauseWorker}
          onResume={handleResumeWorker}
          actionLoading={actionLoading}
        />
        <SystemControls onRestart={handleRestart} actionLoading={actionLoading} />
        <InspectTags />
      </Stack>

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
    </PageContainer>
  );
}
