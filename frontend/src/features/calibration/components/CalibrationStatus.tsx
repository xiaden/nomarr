/**
 * Calibration status component.
 * Displays per-library calibration status with global version info.
 */

import {
    Box,
    Paper,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Typography,
} from "@mui/material";

import { Panel, SectionHeader } from "@shared/components/ui";

import type { CalibrationStatus as CalibrationStatusType } from "../../../shared/api/calibration";

interface CalibrationStatusProps {
  status: CalibrationStatusType;
}

export function CalibrationStatus({ status }: CalibrationStatusProps) {
  // Format last_run timestamp
  const lastRunDate = status.last_run 
    ? new Date(status.last_run * 1000).toLocaleString()
    : "Never";

  return (
    <Panel>
      <SectionHeader title="Calibration Status" />
      
      {/* Global version info */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="body2" color="text.secondary">
          <strong>Global Version:</strong> {status.global_version || "Not calibrated"}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          <strong>Last Run:</strong> {lastRunDate}
        </Typography>
      </Box>

      {/* Per-library status table */}
      {status.libraries.length > 0 ? (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Library</TableCell>
                <TableCell align="right">Total Files</TableCell>
                <TableCell align="right">Current</TableCell>
                <TableCell align="right">Outdated</TableCell>
                <TableCell align="right">Calibration %</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {status.libraries.map((lib) => (
                <TableRow key={lib.library_id}>
                  <TableCell>{lib.library_name}</TableCell>
                  <TableCell align="right">{lib.total_files.toLocaleString()}</TableCell>
                  <TableCell align="right">{lib.current_count.toLocaleString()}</TableCell>
                  <TableCell align="right">{lib.outdated_count.toLocaleString()}</TableCell>
                  <TableCell align="right">{lib.percentage.toFixed(1)}%</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Typography variant="body2" color="text.secondary">
          No libraries found.
        </Typography>
      )}
    </Panel>
  );
}
