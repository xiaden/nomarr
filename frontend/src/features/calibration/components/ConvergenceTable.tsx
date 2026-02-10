/**
 * Convergence table component.
 * Displays per-head calibration convergence metrics in tabular format.
 */

import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import WarningIcon from "@mui/icons-material/Warning";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";

import type { ConvergenceStatusResponse } from "../../../shared/api/calibration";

interface ConvergenceTableProps {
  data: ConvergenceStatusResponse;
}

export function ConvergenceTable({ data }: ConvergenceTableProps) {
  const headKeys = Object.keys(data).sort();

  if (headKeys.length === 0) {
    return (
      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle1" fontWeight={500}>Per-Head Convergence</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="body2" color="text.secondary">
            No convergence data available.
          </Typography>
        </AccordionDetails>
      </Accordion>
    );
  }

  return (
    <Accordion>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle1" fontWeight={500}>Per-Head Convergence</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ p: 0 }}>
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Head</TableCell>
                <TableCell align="right">P5</TableCell>
                <TableCell align="right">P95</TableCell>
                <TableCell align="right">P5 Δ</TableCell>
                <TableCell align="right">P95 Δ</TableCell>
                <TableCell align="right">Samples</TableCell>
                <TableCell align="center">Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {headKeys.map((key) => {
                const head = data[key];
                const { latest_snapshot, p5_delta, p95_delta, n, converged } = head;

                return (
                  <TableRow key={key}>
                    <TableCell>
                      <Typography variant="body2" sx={{ fontFamily: "monospace", fontSize: "0.85rem" }}>
                        {key}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">{latest_snapshot.p5.toFixed(4)}</TableCell>
                    <TableCell align="right">{latest_snapshot.p95.toFixed(4)}</TableCell>
                    <TableCell align="right">
                      {p5_delta !== null ? p5_delta.toFixed(4) : "—"}
                    </TableCell>
                    <TableCell align="right">
                      {p95_delta !== null ? p95_delta.toFixed(4) : "—"}
                    </TableCell>
                    <TableCell align="right">{n.toLocaleString()}</TableCell>
                    <TableCell align="center">
                      {converged ? (
                        <CheckCircleIcon color="success" fontSize="small" titleAccess="Converged" />
                      ) : (
                        <WarningIcon color="warning" fontSize="small" titleAccess="Not converged" />
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </AccordionDetails>
    </Accordion>
  );
}
