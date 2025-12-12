/**
 * Calibration queue status display component.
 * Shows pending, running, completed, errors, and worker status.
 */

import { Box, Typography } from "@mui/material";

import { MetricCard, Panel, ResponsiveGrid, SectionHeader } from "@shared/components/ui";

interface CalibrationStatusProps {
  status: {
    pending: number;
    running: number;
    completed: number;
    errors: number;
    worker_alive: boolean;
    worker_busy: boolean;
  };
}

export function CalibrationStatus({ status }: CalibrationStatusProps) {
  const stats = [
    { label: "Pending", value: status.pending },
    { label: "Running", value: status.running },
    { label: "Completed", value: status.completed },
    { label: "Errors", value: status.errors },
  ];

  return (
    <Panel>
      <SectionHeader title="Calibration Queue Status" />
      <ResponsiveGrid minColumnWidth={150}>
        {stats.map((stat) => (
          <MetricCard
            key={stat.label}
            label={stat.label}
            value={stat.value}
            valueVariant="h5"
            centered
          />
        ))}
      </ResponsiveGrid>
      <Box sx={{ mt: 2 }}>
        <Typography variant="body1">
          Worker:{" "}
          <Typography
            component="span"
            sx={{
              color: status.worker_alive ? "success.main" : "error.main",
              fontWeight: 600,
            }}
          >
            {status.worker_alive ? "Alive" : "Not Running"}
          </Typography>
          {status.worker_alive && (
            <>
              {" • "}
              <Typography
                component="span"
                sx={{
                  color: status.worker_busy ? "info.main" : "success.main",
                  fontWeight: 600,
                }}
              >
                {status.worker_busy ? "Busy" : "Idle"}
              </Typography>
            </>
          )}
        </Typography>
      </Box>
    </Panel>
  );
}
