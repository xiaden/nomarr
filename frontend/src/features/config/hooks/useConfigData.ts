/**
 * Custom hook for managing configuration data.
 * Handles loading, saving, and change tracking.
 */

import { useEffect, useState } from "react";

import { useNotification } from "../../../hooks/useNotification";
import { getConfig, updateConfig } from "../../../shared/api/config";

export function useConfigData() {
  const { showSuccess, showError, showInfo } = useNotification();
  
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [originalConfig, setOriginalConfig] = useState<
    Record<string, unknown>
  >({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveLoading, setSaveLoading] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  const loadConfig = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getConfig();
      setConfig(data);
      setOriginalConfig(data);
      setHasChanges(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load config");
      console.error("[Config] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  useEffect(() => {
    // Check if any values changed
    const changed = Object.keys(config).some(
      (key) => config[key] !== originalConfig[key]
    );
    setHasChanges(changed);
  }, [config, originalConfig]);

  const handleSaveAll = async () => {
    try {
      setSaveLoading(true);
      const changes: string[] = [];

      // Update all changed keys (skip empty/null values)
      for (const key of Object.keys(config)) {
        if (config[key] !== originalConfig[key]) {
          const value = config[key];
          // Skip null, undefined, or empty string values
          if (value === null || value === undefined || value === "") {
            continue;
          }
          await updateConfig(key, String(value));
          changes.push(key);
        }
      }

      if (changes.length === 0) {
        showInfo("No changes to save");
        return;
      }

      showSuccess(
        `Saved ${changes.length} config change(s). Use "Restart Server" in the Admin section to apply.`
      );
      await loadConfig(); // Reload to sync state
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to save config");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleChange = (key: string, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  return {
    config,
    loading,
    error,
    saveLoading,
    hasChanges,
    handleSaveAll,
    handleChange,
  };
}
