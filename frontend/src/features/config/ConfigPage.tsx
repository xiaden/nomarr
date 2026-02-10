/**
 * Configuration page.
 *
 * Features:
 * - View current configuration
 * - Update individual config values
 * - Restart server to apply changes
 * - Admin controls (worker, system, inspect tags)
 */

import { ExpandMore } from "@mui/icons-material";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";

import { ConfirmDialog, PageContainer } from "@shared/components/ui";

import { InspectTags } from "../admin/components/InspectTags";
import { SystemControls } from "../admin/components/SystemControls";
import { WorkerControls } from "../admin/components/WorkerControls";
import { useAdminActions } from "../admin/hooks/useAdminActions";

import { ConfigSettings } from "./components/ConfigSettings";
import { useConfigData } from "./hooks/useConfigData";

export function ConfigPage() {
  const { config, loading, error, saveLoading, hasChanges, handleSaveAll, handleChange } =
    useConfigData();
  const { actionLoading, handlePauseWorker, handleResumeWorker, handleRestart, dialogState } =
    useAdminActions();

  return (
    <PageContainer title="Configuration">
      {loading && <CircularProgress />}
      {error && <Alert severity="error">Error: {error}</Alert>}

      {!loading && !error && (
        <Stack spacing={2}>
          {/* Settings accordion */}
          <Accordion defaultExpanded disableGutters>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                Settings
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <ConfigSettings
                config={config}
                hasChanges={hasChanges}
                saveLoading={saveLoading}
                onChange={handleChange}
                onSaveAll={handleSaveAll}
              />
            </AccordionDetails>
          </Accordion>

          {/* Admin accordion */}
          <Accordion disableGutters>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                Admin
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={2.5}>
                <WorkerControls
                  onPause={handlePauseWorker}
                  onResume={handleResumeWorker}
                  actionLoading={actionLoading}
                />
                <SystemControls onRestart={handleRestart} actionLoading={actionLoading} />
                <InspectTags />
              </Stack>
            </AccordionDetails>
          </Accordion>
        </Stack>
      )}

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
