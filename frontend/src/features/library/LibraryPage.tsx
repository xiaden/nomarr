/**
 * Library management page.
 *
 * Features:
 * - Library statistics
 * - Library CRUD operations
 * - Per-library scanning
 */

import { Stack, Typography } from "@mui/material";

import { ErrorMessage, PageContainer, Panel } from "@shared/components/ui";

import { LibraryManagement } from "./components/LibraryManagement";
import { LibraryStats } from "./components/LibraryStats";
import { useLibraryStats } from "./hooks/useLibraryStats";

export function LibraryPage() {
  const { stats, loading, error } = useLibraryStats();

  return (
    <PageContainer title="Library Management">
      {loading && <Typography>Loading library statistics...</Typography>}
      {error && <ErrorMessage>Error: {error}</ErrorMessage>}

      {stats && (
        <Stack spacing={2.5}>
          <LibraryStats stats={stats} />
          <Panel>
            <LibraryManagement />
          </Panel>
        </Stack>
      )}
    </PageContainer>
  );
}
