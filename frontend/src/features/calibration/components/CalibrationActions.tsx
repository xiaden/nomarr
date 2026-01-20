/**
 * Calibration actions component.
 * Provides buttons to generate and apply calibration.
 */

import { Stack } from "@mui/material";

import { ActionCard, Panel, SectionHeader } from "@shared/components/ui";

interface CalibrationActionsProps {
  onGenerate: () => Promise<void>;
  onApply: () => Promise<void>;
  onUpdateFiles: () => void;
  actionLoading: boolean;
}

export function CalibrationActions({
  onGenerate,
  onApply,
  onUpdateFiles,
  actionLoading,
}: CalibrationActionsProps) {
  const actions = [
    {
      label: "Generate New Calibration",
      description:
        "Analyze all files in library to generate optimal calibration values. This will scan the entire library and may take some time.",
      onClick: onGenerate,
      color: "primary" as const,
      variant: "contained" as const,
    },
    {
      label: "Apply Calibration to Library",
      description:
        "Queue all files for reprocessing with current calibration. This will update all tags based on the current calibration values.",
      onClick: onApply,
      color: "primary" as const,
      variant: "contained" as const,
    },
    {
      label: "Update Calibration Files",
      description:
        "Download and import the latest calibration bundle files from the repository.",
      onClick: onUpdateFiles,
      color: "secondary" as const,
      variant: "outlined" as const,
    },
  ];

  return (
    <Panel>
      <SectionHeader title="Actions" />
      <Stack spacing={2}>
        {actions.map((action) => (
          <ActionCard
            key={action.label}
            label={action.label}
            description={action.description}
            onClick={action.onClick}
            disabled={actionLoading}
            variant={action.variant}
            color={action.color}
          />
        ))}
      </Stack>
    </Panel>
  );
}
