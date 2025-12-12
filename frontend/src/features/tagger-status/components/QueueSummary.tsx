/**
 * QueueSummary component.
 * Displays queue statistics badges and SSE connection status.
 */

import { Box, Chip, Stack, Typography } from "@mui/material";

import { Panel } from "@shared/components/ui";

interface QueueSummaryProps {
  summary: {
    pending: number;
    running: number;
    completed: number;
    errors: number;
  };
  connected: boolean;
}

export function QueueSummary({ summary, connected }: QueueSummaryProps) {
  return (
    <Panel>
      {/* SSE Status */}
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="body2" color="text.secondary">
          SSE Status:
        </Typography>
        <Chip
          label={connected ? "Connected" : "Disconnected"}
          size="small"
          color={connected ? "success" : "error"}
          sx={{ height: 20, fontSize: "0.7rem" }}
        />
      </Stack>

      {/* Summary badges */}
      <Stack direction="row" spacing={2} flexWrap="wrap">
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            p: 2,
            bgcolor: "background.default",
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
            minWidth: 100,
          }}
        >
          <Typography variant="h4" fontWeight="bold">
            {summary.pending}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Pending
          </Typography>
        </Box>
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            p: 2,
            bgcolor: "background.default",
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
            minWidth: 100,
          }}
        >
          <Typography variant="h4" fontWeight="bold">
            {summary.running}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Running
          </Typography>
        </Box>
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            p: 2,
            bgcolor: "background.default",
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
            minWidth: 100,
          }}
        >
          <Typography variant="h4" fontWeight="bold">
            {summary.completed}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Completed
          </Typography>
        </Box>
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            p: 2,
            bgcolor: "background.default",
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
            minWidth: 100,
          }}
        >
          <Typography variant="h4" fontWeight="bold">
            {summary.errors}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Errors
          </Typography>
        </Box>
      </Stack>
    </Panel>
  );
}
