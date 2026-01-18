/**
 * Tagger Status page.
 *
 * Features:
 * - List all tagger jobs with pagination
 * - Filter by status (all, pending, running, done, error)
 * - Real-time updates via SSE
 * - Job removal actions
 * - Clear completed/error jobs
 */

import { Typography } from "@mui/material";

import { ConfirmDialog, ErrorMessage, PageContainer } from "@shared/components/ui";

import { QueueFilters } from "./components/QueueFilters";
import { QueueJobsTable } from "./components/QueueJobsTable";
import { QueueSummary } from "./components/QueueSummary";
import { useQueueData } from "./hooks/useQueueData";

export function TaggerStatusPage() {
  const {
    jobs,
    summary,
    total,
    loading,
    error,
    actionLoading,
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
    dialogState,
  } = useQueueData();

  return (
    <PageContainer title="Tagger Status">
      <QueueSummary summary={summary} />

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
          Loading tagger status...
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

      {/* Confirm dialog for queue actions */}
      <ConfirmDialog
        open={dialogState.isOpen}
        title={dialogState.options.title}
        message={dialogState.options.message}
        confirmLabel={dialogState.options.confirmLabel}
        cancelLabel={dialogState.options.cancelLabel}
        severity={dialogState.options.severity}
        onConfirm={dialogState.handleConfirm}
        onCancel={dialogState.handleCancel}
      />
    </PageContainer>
  );
}
