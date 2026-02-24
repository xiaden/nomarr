/**
 * ML management controls component.
 * Provides VRAM probe re-scheduling functionality.
 */

import { ActionCard, Panel, SectionHeader } from "@shared/components/ui";

interface MLControlsProps {
  onVramProbe: () => Promise<void>;
  actionLoading: boolean;
}

export function MLControls({ onVramProbe, actionLoading }: MLControlsProps) {
  return (
    <Panel>
      <SectionHeader title="ML Controls" />
      <ActionCard
        label="Re-run VRAM Probe"
        description="Clears stored per-model VRAM measurements. The next worker startup will re-probe all models and record fresh measurements."
        onClick={onVramProbe}
        disabled={actionLoading}
        variant="contained"
        color="primary"
      />
    </Panel>
  );
}
