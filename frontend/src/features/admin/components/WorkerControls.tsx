/**
 * Worker control buttons component.
 * Provides pause/resume controls for the queue worker.
 */

import { Stack } from "@mui/material";

import { ActionCard, Panel, SectionHeader } from "@shared/components/ui";

interface WorkerControlsProps {
  onPause: () => Promise<void>;
  onResume: () => Promise<void>;
  actionLoading: boolean;
}

export function WorkerControls({
  onPause,
  onResume,
  actionLoading,
}: WorkerControlsProps) {
  return (
    <Panel>
      <SectionHeader title="Worker Controls" />
      <Stack spacing={1.25}>
        <ActionCard
          label="Pause Worker"
          description="Stops the worker from processing queue jobs. Jobs remain in the queue."
          onClick={onPause}
          disabled={actionLoading}
        />
        <ActionCard
          label="Resume Worker"
          description="Starts the worker to process queue jobs."
          onClick={onResume}
          disabled={actionLoading}
        />
      </Stack>
    </Panel>
  );
}
