/**
 * Configuration page.
 *
 * Features:
 * - View current configuration
 * - Update individual config values
 * - Restart server to apply changes
 */

import { useEffect, useState } from "react";

import { api } from "../../shared/api";

export function ConfigPage() {
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [originalConfig, setOriginalConfig] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveLoading, setSaveLoading] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  const loadConfig = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.config.get();
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
          await api.config.update(key, String(value));
          changes.push(key);
        }
      }
      
      if (changes.length === 0) {
        alert("No changes to save");
        return;
      }
      
      alert(`Saved ${changes.length} config change(s). Use "Restart Server" in Admin page to apply.`);
      await loadConfig(); // Reload to sync state
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to save config");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleChange = (key: string, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const renderField = (key: string, value: unknown) => {
    // Convert null/undefined to empty string instead of "null"/"undefined"
    const stringValue = value === null || value === undefined ? "" : String(value);
    const isBool = typeof value === "boolean";

    return (
      <div key={key} style={styles.field}>
        <label style={styles.label}>{key}</label>
        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          {isBool ? (
            <select
              value={stringValue}
              onChange={(e) => handleChange(key, e.target.value)}
              style={styles.input}
              disabled={saveLoading}
            >
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          ) : (
            <input
              type="text"
              value={stringValue}
              onChange={(e) => handleChange(key, e.target.value)}
              style={styles.input}
              disabled={saveLoading}
            />
          )}
        </div>
      </div>
    );
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Configuration</h1>

      {loading && <p>Loading configuration...</p>}
      {error && <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>}

      {!loading && !error && (
        <div style={{ display: "grid", gap: "20px" }}>
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Settings</h2>
            <p
              style={{
                color: "#888",
                marginBottom: "20px",
                fontSize: "0.875rem",
              }}
            >
              Changes are saved to the database and will take effect on server
              restart. Use "Restart Server" in Admin page to apply changes.
            </p>
            <div style={{ display: "grid", gap: "15px" }}>
              {Object.entries(config).map(([key, value]) =>
                renderField(key, value)
              )}
            </div>
            
            <div style={{ marginTop: "30px", display: "flex", gap: "10px", alignItems: "center" }}>
              <button
                onClick={handleSaveAll}
                style={{
                  ...styles.saveButton,
                  opacity: hasChanges && !saveLoading ? 1 : 0.5,
                  cursor: hasChanges && !saveLoading ? "pointer" : "not-allowed",
                }}
                disabled={!hasChanges || saveLoading}
              >
                {saveLoading ? "Saving..." : "Save All Changes"}
              </button>
              {hasChanges && (
                <span style={{ color: "#ff9800", fontSize: "0.875rem" }}>
                  Unsaved changes
                </span>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

const styles = {
  section: {
    backgroundColor: "#1a1a1a",
    padding: "20px",
    borderRadius: "8px",
    border: "1px solid #333",
  },
  sectionTitle: {
    fontSize: "1.25rem",
    marginBottom: "15px",
    color: "#fff",
  },
  field: {
    display: "grid",
    gap: "8px",
  },
  label: {
    fontSize: "0.875rem",
    color: "#888",
    fontWeight: "bold" as const,
  },
  input: {
    flex: 1,
    padding: "10px",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
  },
  saveButton: {
    padding: "10px 20px",
    backgroundColor: "#4a9eff",
    border: "none",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
    cursor: "pointer",
    whiteSpace: "nowrap" as const,
  },
  browseButton: {
    padding: "10px 20px",
    backgroundColor: "#6c757d",
    border: "none",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
    cursor: "pointer",
    whiteSpace: "nowrap" as const,
  },
};
