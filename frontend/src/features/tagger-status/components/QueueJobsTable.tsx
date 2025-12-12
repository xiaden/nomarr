/**
 * QueueJobsTable component.
 * Displays queue jobs in a MUI-styled list with pagination.
 */

import { Delete } from "@mui/icons-material";
import {
  Box,
  Button,
  Chip,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";

import { Panel } from "@shared/components/ui";

import type { QueueJob } from "../../../shared/types";

interface QueueJobsTableProps {
  jobs: QueueJob[];
  total: number;
  currentPage: number;
  totalPages: number;
  onRemoveJob: (jobId: number) => Promise<void>;
  onNextPage: () => void;
  onPrevPage: () => void;
  statusFilter: string;
}

export function QueueJobsTable({
  jobs,
  total,
  currentPage,
  totalPages,
  onRemoveJob,
  onNextPage,
  onPrevPage,
  statusFilter,
}: QueueJobsTableProps) {
  const formatTimestamp = (ts: number | null | undefined): string => {
    if (!ts) return "-";
    return new Date(ts * 1000).toLocaleString();
  };

  const truncatePath = (path: string, maxLen = 80): string => {
    if (path.length <= maxLen) return path;
    const start = path.substring(0, 40);
    const end = path.substring(path.length - 37);
    return start + "..." + end;
  };

  const getStatusColor = (
    status: string
  ): "default" | "warning" | "success" | "error" => {
    if (status === "running") return "warning";
    if (status === "done") return "success";
    if (status === "error") return "error";
    return "default";
  };

  if (jobs.length === 0 && total === 0) {
    return (
      <Panel>
        <Typography color="text.secondary" textAlign="center" py={8}>
          {statusFilter !== "all"
            ? `No ${statusFilter} jobs found`
            : "Queue is empty"}
        </Typography>
      </Panel>
    );
  }

  return (
    <>
      {/* Jobs List */}
      <Stack spacing={1}>
        {jobs.map((job) => (
          <Box
            key={job.id}
            sx={{
              bgcolor: "background.paper",
              border: 1,
              borderColor: "divider",
              borderRadius: 1,
              p: 2,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
            }}
          >
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Typography
                  variant="caption"
                  color="text.disabled"
                  sx={{ fontFamily: "monospace" }}
                >
                  #{job.id}
                </Typography>
                <Chip
                  label={job.status}
                  size="small"
                  color={getStatusColor(job.status)}
                  sx={{ height: 20, fontSize: "0.7rem" }}
                />
              </Stack>

              <Tooltip title={job.path} placement="top">
                <Typography
                  variant="body2"
                  sx={{
                    fontFamily: "monospace",
                    fontSize: "0.85rem",
                    mb: 0.5,
                    wordBreak: "break-all",
                  }}
                >
                  {truncatePath(job.path)}
                </Typography>
              </Tooltip>

              <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  Created: {formatTimestamp(job.created_at)}
                </Typography>
                {job.started_at && (
                  <Typography variant="caption" color="text.secondary">
                    Started: {formatTimestamp(job.started_at)}
                  </Typography>
                )}
              </Stack>

              {job.error_message && (
                <Typography
                  variant="caption"
                  color="error"
                  sx={{
                    display: "block",
                    mt: 1,
                    p: 1,
                    bgcolor: "error.dark",
                    borderRadius: 0.5,
                  }}
                >
                  {job.error_message}
                </Typography>
              )}
            </Box>

            <IconButton
              onClick={() => onRemoveJob(job.id)}
              disabled={job.status === "running"}
              color="error"
              size="small"
              sx={{ ml: 2 }}
            >
              <Delete fontSize="small" />
            </IconButton>
          </Box>
        ))}
      </Stack>

      {/* Pagination */}
      {totalPages > 1 && (
        <Box sx={{ mt: 3 }}>
          <Stack
            direction="row"
            spacing={2}
            alignItems="center"
            justifyContent="center"
          >
            <Button
              variant="outlined"
              onClick={onPrevPage}
              disabled={currentPage === 1}
            >
              Previous
            </Button>
            <Typography color="text.secondary">
              Page {currentPage} of {totalPages} ({total.toLocaleString()} total)
            </Typography>
            <Button
              variant="outlined"
              onClick={onNextPage}
              disabled={currentPage === totalPages}
            >
              Next
            </Button>
          </Stack>
        </Box>
      )}
    </>
  );
}
