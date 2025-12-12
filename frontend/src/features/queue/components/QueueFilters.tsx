/**
 * QueueFilters component.
 * Status filter buttons and action buttons for queue management.
 */

import { Refresh } from "@mui/icons-material";
import { Button, Stack, ToggleButton, ToggleButtonGroup } from "@mui/material";

import { Panel } from "@shared/components/ui";

type StatusFilter = "all" | "pending" | "running" | "done" | "error";

interface QueueFiltersProps {
  statusFilter: StatusFilter;
  onFilterChange: (filter: StatusFilter) => void;
  loading: boolean;
  actionLoading: boolean;
  summary: {
    pending: number;
    running: number;
    completed: number;
    errors: number;
  };
  onRefresh: () => void;
  onClearCompleted: () => Promise<void>;
  onClearErrors: () => Promise<void>;
  onClearAll: () => Promise<void>;
}

export function QueueFilters({
  statusFilter,
  onFilterChange,
  loading,
  actionLoading,
  summary,
  onRefresh,
  onClearCompleted,
  onClearErrors,
  onClearAll,
}: QueueFiltersProps) {
  return (
    <Panel>
      <Stack
        direction="row"
        spacing={2}
        alignItems="center"
        justifyContent="space-between"
        flexWrap="wrap"
        gap={2}
      >
        {/* Status Filters */}
        <ToggleButtonGroup
          value={statusFilter}
          exclusive
          onChange={(_, value) => value && onFilterChange(value)}
          size="small"
          disabled={loading}
        >
          {(["all", "pending", "running", "done", "error"] as StatusFilter[]).map(
            (filter) => (
              <ToggleButton key={filter} value={filter}>
                {filter.charAt(0).toUpperCase() + filter.slice(1)}
              </ToggleButton>
            )
          )}
        </ToggleButtonGroup>

        {/* Action Buttons */}
        <Stack direction="row" spacing={1}>
          <Button
            onClick={onRefresh}
            disabled={loading || actionLoading}
            variant="outlined"
            size="small"
            startIcon={<Refresh />}
          >
            Refresh
          </Button>
          <Button
            onClick={onClearCompleted}
            disabled={loading || actionLoading || summary.completed === 0}
            variant="outlined"
            size="small"
          >
            Clear Completed
          </Button>
          <Button
            onClick={onClearErrors}
            disabled={loading || actionLoading || summary.errors === 0}
            variant="outlined"
            size="small"
          >
            Clear Errors
          </Button>
          <Button
            onClick={onClearAll}
            disabled={loading || actionLoading}
            variant="outlined"
            color="error"
            size="small"
          >
            Clear All
          </Button>
        </Stack>
      </Stack>
    </Panel>
  );
}
