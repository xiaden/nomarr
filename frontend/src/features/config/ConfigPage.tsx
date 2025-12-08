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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updateLoading, setUpdateLoading] = useState(false);

  const loadConfig = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.config.get();
      setConfig(data);
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

  const handleUpdate = async (key: string, value: string) => {
    try {
      setUpdateLoading(true);
      const result = await api.config.update(key, value);
      alert(result.message);
      await loadConfig(); // Reload to show updated values
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to update config");
    } finally {
      setUpdateLoading(false);
    }
  };

  const handleChange = (key: string, value: string) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e: React.FormEvent, key: string) => {
    e.preventDefault();
    const value = String(config[key]);
    handleUpdate(key, value);
  };

  const renderField = (key: string, value: unknown) => {
    const stringValue = String(value);
    const isBool = typeof value === "boolean";

    return (
      <div key={key} style={styles.field}>
        <label style={styles.label}>{key}</label>
        <form
          onSubmit={(e) => handleSubmit(e, key)}
          style={{ display: "flex", gap: "10px", alignItems: "center" }}
        >
          {isBool ? (
            <select
              value={stringValue}
              onChange={(e) => handleChange(key, e.target.value)}
              style={styles.input}
              disabled={updateLoading}
            >
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          ) : (
            <>
              <input
                type="text"
                value={stringValue}
                onChange={(e) => handleChange(key, e.target.value)}
                style={styles.input}
                disabled={updateLoading}
              />
            </>
          )}
          <button
            type="submit"
            style={styles.saveButton}
            disabled={updateLoading}
          >
            Save
          </button>
        </form>
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
