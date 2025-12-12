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
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "10px" }}>Queue Management</h1>

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
        <div style={{ textAlign: "center", padding: "40px" }}>
          <p>Loading queue...</p>
        </div>
      )}

      {error && (
        <div
          style={{
            padding: "20px",
            backgroundColor: "var(--accent-red)",
            borderRadius: "6px",
            marginBottom: "20px",
          }}
        >
          <strong>Error:</strong> {error}
        </div>
      )}

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
    </div>
  );
}
