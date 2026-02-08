/**
 * Convergence summary component.
 * Displays aggregate statistics across all calibration heads.
 */

import { Box, Typography } from "@mui/material";

import { Panel, SectionHeader } from "@shared/components/ui";

import type { ConvergenceStatusResponse } from "../../../shared/api/calibration";

interface ConvergenceSummaryProps {
  data: ConvergenceStatusResponse;
}

export function ConvergenceSummary({ data }: ConvergenceSummaryProps) {
  const headKeys = Object.keys(data);
  const totalHeads = headKeys.length;
  const convergedCount = headKeys.filter((key) => data[key].converged).length;
  const totalSamples = headKeys.reduce((sum, key) => sum + data[key].n, 0);
  const averageSamples = totalHeads > 0 ? Math.round(totalSamples / totalHeads) : 0;

  return (
    <Panel>
      <SectionHeader title="Convergence Summary" />

      <Box sx={{ display: "flex", gap: 4 }}>
        <Box>
          <Typography variant="body2" color="text.secondary">
            Total Heads
          </Typography>
          <Typography variant="h5">{totalHeads}</Typography>
        </Box>

        <Box>
          <Typography variant="body2" color="text.secondary">
            Converged
          </Typography>
          <Typography variant="h5" color={convergedCount === totalHeads ? "success.main" : "warning.main"}>
            {convergedCount} / {totalHeads}
          </Typography>
        </Box>

        <Box>
          <Typography variant="body2" color="text.secondary">
            Average Samples
          </Typography>
          <Typography variant="h5">{averageSamples.toLocaleString()}</Typography>
        </Box>
      </Box>
    </Panel>
  );
}
