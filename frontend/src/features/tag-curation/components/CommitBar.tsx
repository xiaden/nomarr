import { Alert, Button, CircularProgress } from "@mui/material";

import { usePendingCommit } from "../hooks/usePendingCommit";

export function CommitBar(): React.JSX.Element {
  const { pendingCount, commit, isCommitting } = usePendingCommit();

  if (pendingCount === 0) {
    return <></>;
  }

  return (
    <Alert
      severity="warning"
      sx={{ mb: 2 }}
      action={
        <Button
          color="inherit"
          size="small"
          onClick={() => void commit()}
          disabled={isCommitting}
          startIcon={isCommitting ? <CircularProgress size={16} /> : undefined}
        >
          {isCommitting ? "Committing…" : "Commit Changes"}
        </Button>
      }
    >
      {pendingCount} file{pendingCount !== 1 ? "s" : ""} have pending tag
      changes
    </Alert>
  );
}
