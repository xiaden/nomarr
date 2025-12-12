/**
 * Queue management page.
 *
 * Features:
 * - List all queue jobs with pagination
 * - Filter by status (all, pending, running, done, error)
 * - Real-time updates via SSE
 * - Job removal actions
 * - Clear completed/error jobs
 */

import { Typography } from "@mui/material";

import { ErrorMessage, PageContainer } from "@shared/components/ui";

import { QueueFilters } from "./components/QueueFilters";
import { QueueJobsTable } from "./components/QueueJobsTable";
import { QueueSummary } from "./components/QueueSummary";
import { useQueueData } from "./hooks/useQueueData";

export function QueuePage() {
  const {
    jobs,
    summary,
    total,
    loading,
    error,
    actionLoading,
    connected,
    statusFilter,
    currentPage,
    totalPages,
    loadQueue,
    removeJob,
    clearCompleted,
    clearErrors,
    clearAll,
    handleFilterChange,
    nextPage,
    prevPage,
  } = useQueueData();

  return (
    <PageContainer title="Queue Management">
      <QueueSummary summary={summary} connected={connected} />

      <QueueFilters
        statusFilter={statusFilter}
        onFilterChange={handleFilterChange}
        loading={loading}
        actionLoading={actionLoading}
        summary={summary}
        onRefresh={loadQueue}
        onClearCompleted={clearCompleted}
        onClearErrors={clearErrors}
        onClearAll={clearAll}
      />

      {loading && (
        <Typography textAlign="center" py={5} color="text.secondary">
          Loading queue...
        </Typography>
      )}

      {error && <ErrorMessage>{error}</ErrorMessage>}

      {!loading && !error && (
        <QueueJobsTable
          jobs={jobs}
          total={total}
          currentPage={currentPage}
          totalPages={totalPages}
          onRemoveJob={removeJob}
          onNextPage={nextPage}
          onPrevPage={prevPage}
          statusFilter={statusFilter}
        />
      )}
    </PageContainer>
  );
}
