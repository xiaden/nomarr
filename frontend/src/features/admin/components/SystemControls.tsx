/**
 * System control buttons component.
 * Provides server restart functionality.
 */

import { ActionCard, Panel, SectionHeader } from "@shared/components/ui";

interface SystemControlsProps {
  onRestart: () => Promise<void>;
  actionLoading: boolean;
}

export function SystemControls({
  onRestart,
  actionLoading,
}: SystemControlsProps) {
  return (
    <Panel>
      <SectionHeader title="System Controls" />
      <ActionCard
        label="Restart Server"
        description="Stops and restarts the API server. Config changes will take effect. Page will reload automatically after restart."
        onClick={onRestart}
        disabled={actionLoading}
        variant="contained"
        color="error"
      />
    </Panel>
  );
}
