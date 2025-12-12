/**
 * Admin page.
 *
 * Features:
 * - Worker control (pause/resume)
 * - Server restart
 */

import { SystemControls } from "./components/SystemControls";
import { WorkerControls } from "./components/WorkerControls";
import { useAdminActions } from "./hooks/useAdminActions";

export function AdminPage() {
  const { actionLoading, handlePauseWorker, handleResumeWorker, handleRestart } =
    useAdminActions();

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Admin</h1>

      <div style={{ display: "grid", gap: "20px" }}>
        <WorkerControls
          onPause={handlePauseWorker}
          onResume={handleResumeWorker}
          actionLoading={actionLoading}
        />
        <SystemControls onRestart={handleRestart} actionLoading={actionLoading} />
      </div>
    </div>
  );
}
