import { Alert, Button, CircularProgress } from "@mui/material";

import { usePendingCommit } from "../hooks/usePendingCommit";

export function CommitBar(): React.JSX.Element {
  const { pendingCount, commit, isCommitting, commitError } = usePendingCommit();

  if (pendingCount === 0) {
    return <></>;
  }

  return (
    <Alert
      severity={commitError ? "error" : "warning"}
      sx={{ mb: 2 }}
      action={
        <Button
          color="inherit"
          size="small"
          onClick={() => void commit().catch(() => undefined)}
          disabled={isCommitting}
          startIcon={isCommitting ? <CircularProgress size={16} /> : undefined}
        >
          {isCommitting ? "Committing…" : "Commit Changes"}
        </Button>
      }
    >
      {commitError ? `Commit failed: ${commitError}. ` : ""}
      {pendingCount} file{pendingCount !== 1 ? "s" : ""} have pending tag
      changes
    </Alert>
  );
}
