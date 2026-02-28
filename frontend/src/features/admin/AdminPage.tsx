/**
 * Admin page.
 *
 * Features:
 * - Server restart
 * - Inspect tags (debug tool)
 */

import { Stack } from "@mui/material";

import { ConfirmDialog, PageContainer } from "@shared/components/ui";

import { InspectTags } from "./components/InspectTags";
import { SystemControls } from "./components/SystemControls";
import { VectorMaintenance } from "./components/VectorMaintenance";
import { useAdminActions } from "./hooks/useAdminActions";

export function AdminPage() {
  const { actionLoading, handleRestart, dialogState } =
    useAdminActions();

  return (
    <PageContainer title="Admin">
      <Stack spacing={2.5}>
        <SystemControls onRestart={handleRestart} actionLoading={actionLoading} />
        <VectorMaintenance />
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
