/**
 * Configuration page.
 *
 * Features:
 * - View current configuration
 * - Update individual config values
 * - Restart server to apply changes
 */

import { ConfigSettings } from "./components/ConfigSettings";
import { useConfigData } from "./hooks/useConfigData";

export function ConfigPage() {
  const {
    config,
    loading,
    error,
    saveLoading,
    hasChanges,
    handleSaveAll,
    handleChange,
  } = useConfigData();

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Configuration</h1>

      {loading && <p>Loading configuration...</p>}
      {error && <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>}

      {!loading && !error && (
        <div style={{ display: "grid", gap: "20px" }}>
          <ConfigSettings
            config={config}
            hasChanges={hasChanges}
            saveLoading={saveLoading}
            onChange={handleChange}
            onSaveAll={handleSaveAll}
          />
        </div>
      )}
    </div>
  );
}
