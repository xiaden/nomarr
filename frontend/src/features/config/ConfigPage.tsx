/**
 * Configuration page.
 *
 * Features:
 * - View current configuration
 * - Update individual config values
 * - Restart server to apply changes
 * - Manage libraries (CRUD operations)
 */

import { Alert, CircularProgress, Stack } from "@mui/material";

import { PageContainer } from "@shared/components/ui";

import { LibraryManagement } from "../library/components/LibraryManagement";

import { ConfigSettings } from "./components/ConfigSettings";
import { useConfigData } from "./hooks/useConfigData";

export function ConfigPage() {
  const { config, loading, error, saveLoading, hasChanges, handleSaveAll, handleChange } =
    useConfigData();

  return (
    <PageContainer title="Configuration">
      {loading && <CircularProgress />}
      {error && <Alert severity="error">Error: {error}</Alert>}

      {!loading && !error && (
        <Stack spacing={2.5}>
          <LibraryManagement />
          <ConfigSettings
            config={config}
            hasChanges={hasChanges}
            saveLoading={saveLoading}
            onChange={handleChange}
            onSaveAll={handleSaveAll}
          />
        </Stack>
      )}
    </PageContainer>
  );
}
