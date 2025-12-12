/**
 * Example: How to use the new notification and confirm dialog system
 * 
 * Replace browser alert() and confirm() with proper MUI components
 */

import { useConfirmDialog } from "@hooks/useConfirmDialog";
import { useNotification } from "@hooks/useNotification";
import { Button, Stack } from "@mui/material";
import { ConfirmDialog } from "@shared/components/ui";
import { useState } from "react";

export function ExampleUsage() {
  const { showSuccess, showError, showInfo } = useNotification();
  const { isOpen, options, confirm, handleConfirm, handleCancel } = useConfirmDialog();
  const [actionLoading, setActionLoading] = useState(false);

  // Example 1: Simple success/error notifications (replaces alert())
  const handleSimpleAction = async () => {
    try {
      setActionLoading(true);
      // ... do something
      showSuccess("Operation completed successfully!");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Operation failed");
    } finally {
      setActionLoading(false);
    }
  };

  // Example 2: Confirmation dialog (replaces confirm())
  const handleDeleteAction = async () => {
    const confirmed = await confirm({
      title: "Delete Item?",
      message: "This action cannot be undone. Are you sure?",
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      severity: "error",
    });

    if (!confirmed) return;

    try {
      setActionLoading(true);
      // ... do delete
      showSuccess("Item deleted successfully");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setActionLoading(false);
    }
  };

  // Example 3: Multi-line success message (replaces alert with detailed info)
  const handleGenerateCalibration = async () => {
    const confirmed = await confirm({
      title: "Generate Calibration?",
      message: "This analyzes all library files and may take some time.",
      confirmLabel: "Generate",
      severity: "warning",
    });

    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = { library_size: 1000, calibrations: 42, skipped: 3 };
      
      // For multi-line success, use showInfo with formatted message
      showInfo(
        `Calibration generated! Library: ${result.library_size} files, ` +
        `Calibrations: ${result.calibrations}, Skipped: ${result.skipped}`
      );
    } catch (err) {
      showError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <>
      <Stack spacing={2}>
        <Button onClick={handleSimpleAction} disabled={actionLoading}>
          Simple Action (with notification)
        </Button>
        <Button onClick={handleDeleteAction} disabled={actionLoading}>
          Delete Action (with confirm)
        </Button>
        <Button onClick={handleGenerateCalibration} disabled={actionLoading}>
          Generate Calibration (confirm + detailed notification)
        </Button>
      </Stack>

      {/* Required: Render the confirm dialog */}
      <ConfirmDialog
        open={isOpen}
        title={options.title}
        message={options.message}
        confirmLabel={options.confirmLabel}
        cancelLabel={options.cancelLabel}
        severity={options.severity}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </>
  );
}

/**
 * MIGRATION GUIDE:
 * 
 * Old way:
 *   if (!confirm("Are you sure?")) return;
 *   alert("Success!");
 * 
 * New way:
 *   const { showSuccess } = useNotification();
 *   const { confirm, isOpen, options, handleConfirm, handleCancel } = useConfirmDialog();
 *   
 *   const confirmed = await confirm({
 *     title: "Confirm Action",
 *     message: "Are you sure?",
 *   });
 *   if (!confirmed) return;
 *   
 *   showSuccess("Success!");
 *   
 *   // Don't forget to render the dialog:
 *   <ConfirmDialog
 *     open={isOpen}
 *     title={options.title}
 *     message={options.message}
 *     onConfirm={handleConfirm}
 *     onCancel={handleCancel}
 *   />
 */
