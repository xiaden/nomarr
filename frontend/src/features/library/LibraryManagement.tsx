/**
 * LibraryManagement - CRUD interface for managing multiple libraries
 *
 * Features:
 * - List all libraries with status indicators
 * - Create new libraries with path picker
 * - Edit library properties (name, path, enabled, default)
 * - Scan individual libraries
 * - Set default library
 */

import { useEffect, useState } from "react";

import { ServerFilePicker } from "../../components/ServerFilePicker";
import { api } from "../../shared/api";
import type { Library } from "../../shared/types";

export function LibraryManagement() {
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [scanningId, setScanningId] = useState<number | null>(null);

  // Create/edit form state
  const [formName, setFormName] = useState("");
  const [formRootPath, setFormRootPath] = useState("");
  const [formIsEnabled, setFormIsEnabled] = useState(true);
  const [formIsDefault, setFormIsDefault] = useState(false);
  const [showPathPicker, setShowPathPicker] = useState(false);

  const loadLibraries = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.library.list();
      setLibraries(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load libraries"
      );
      console.error("[LibraryManagement] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLibraries();
  }, []);

  const resetForm = () => {
    setFormName("");
    setFormRootPath("");
    setFormIsEnabled(true);
    setFormIsDefault(false);
    setShowPathPicker(false);
    setIsCreating(false);
    setEditingId(null);
  };

  const startCreate = () => {
    resetForm();
    setIsCreating(true);
  };

  const startEdit = (library: Library) => {
    setFormName(library.name);
    setFormRootPath(library.rootPath);
    setFormIsEnabled(library.isEnabled);
    setFormIsDefault(library.isDefault);
    setEditingId(library.id);
    setIsCreating(false);
  };

  const handleCreate = async () => {
    if (!formName.trim() || !formRootPath.trim()) {
      setError("Name and path are required");
      return;
    }

    try {
      setError(null);
      await api.library.create({
        name: formName,
        rootPath: formRootPath,
        isEnabled: formIsEnabled,
        isDefault: formIsDefault,
      });
      await loadLibraries();
      resetForm();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create library"
      );
    }
  };

  const handleUpdate = async () => {
    if (editingId === null) return;
    if (!formName.trim() || !formRootPath.trim()) {
      setError("Name and path are required");
      return;
    }

    try {
      setError(null);
      await api.library.update(editingId, {
        name: formName,
        rootPath: formRootPath,
        isEnabled: formIsEnabled,
        isDefault: formIsDefault,
      });
      await loadLibraries();
      resetForm();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update library"
      );
    }
  };

  const handleSetDefault = async (id: number) => {
    try {
      setError(null);
      await api.library.setDefault(id);
      await loadLibraries();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to set default library"
      );
    }
  };

  const handleScan = async (id: number) => {
    try {
      setError(null);
      setScanningId(id);
      const result = await api.library.scan(id, {
        recursive: true,
        force: false,
        cleanMissing: true,
      });
      alert(
        `Scan ${result.status}: ${result.message || "Library scan queued"}`
      );
      await loadLibraries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to scan library");
    } finally {
      setScanningId(null);
    }
  };

  const isFormMode = isCreating || editingId !== null;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={styles.title}>Libraries</h2>
        {!isFormMode && (
          <button style={styles.btnPrimary} onClick={startCreate}>
            + Add Library
          </button>
        )}
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {/* Create/Edit Form */}
      {isFormMode && (
        <div style={styles.form}>
          <h3 style={styles.formTitle}>
            {isCreating ? "Create Library" : "Edit Library"}
          </h3>

          <div style={styles.formField}>
            <label style={styles.label}>Name</label>
            <input
              type="text"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              style={styles.input}
              placeholder="My Music Library"
            />
          </div>

          <div style={styles.formField}>
            <label style={styles.label}>Root Path</label>
            <div style={styles.pathFieldRow}>
              <input
                type="text"
                value={formRootPath}
                onChange={(e) => setFormRootPath(e.target.value)}
                style={styles.input}
                placeholder="/music"
              />
              <button
                style={styles.btnSecondary}
                onClick={() => setShowPathPicker(!showPathPicker)}
              >
                {showPathPicker ? "Hide Picker" : "Browse..."}
              </button>
            </div>
            {showPathPicker && (
              <div style={styles.pickerContainer}>
                <ServerFilePicker
                  value={formRootPath}
                  onChange={(path) => {
                    setFormRootPath(path);
                    setShowPathPicker(false);
                  }}
                  mode="directory"
                  label="Select Library Root Directory"
                />
              </div>
            )}
          </div>

          <div style={styles.formField}>
            <label style={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={formIsEnabled}
                onChange={(e) => setFormIsEnabled(e.target.checked)}
                style={styles.checkbox}
              />
              Enabled
            </label>
          </div>

          <div style={styles.formField}>
            <label style={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={formIsDefault}
                onChange={(e) => setFormIsDefault(e.target.checked)}
                style={styles.checkbox}
              />
              Default Library
            </label>
          </div>

          <div style={styles.formActions}>
            <button
              style={styles.btnPrimary}
              onClick={isCreating ? handleCreate : handleUpdate}
            >
              {isCreating ? "Create" : "Update"}
            </button>
            <button style={styles.btnSecondary} onClick={resetForm}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Libraries List */}
      {loading && <p>Loading libraries...</p>}

      {!loading && !isFormMode && libraries.length === 0 && (
        <p style={styles.emptyState}>
          No libraries configured. Click "Add Library" to get started.
        </p>
      )}

      {!loading && !isFormMode && libraries.length > 0 && (
        <div style={styles.librariesList}>
          {libraries.map((lib) => (
            <div key={lib.id} style={styles.libraryCard}>
              <div style={styles.libraryHeader}>
                <div>
                  <h3 style={styles.libraryName}>
                    {lib.name}
                    {lib.isDefault && (
                      <span style={styles.badge}>Default</span>
                    )}
                  </h3>
                  <p style={styles.libraryPath}>{lib.rootPath}</p>
                </div>
                <div style={styles.libraryStatus}>
                  <span
                    style={{
                      ...styles.statusDot,
                      backgroundColor: lib.isEnabled ? "#4caf50" : "#999",
                    }}
                  />
                  {lib.isEnabled ? "Enabled" : "Disabled"}
                </div>
              </div>

              <div style={styles.libraryActions}>
                <button
                  style={styles.btnSmall}
                  onClick={() => startEdit(lib)}
                  disabled={scanningId === lib.id}
                >
                  Edit
                </button>
                {!lib.isDefault && (
                  <button
                    style={styles.btnSmall}
                    onClick={() => handleSetDefault(lib.id)}
                    disabled={scanningId === lib.id}
                  >
                    Set Default
                  </button>
                )}
                <button
                  style={{
                    ...styles.btnSmall,
                    ...styles.btnScan,
                  }}
                  onClick={() => handleScan(lib.id)}
                  disabled={!lib.isEnabled || scanningId === lib.id}
                >
                  {scanningId === lib.id ? "Scanning..." : "Scan"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const styles = {
  container: {
    display: "flex" as const,
    flexDirection: "column" as const,
    gap: "20px",
  },
  header: {
    display: "flex" as const,
    justifyContent: "space-between" as const,
    alignItems: "center" as const,
  },
  title: {
    fontSize: "1.25rem",
    margin: 0,
    color: "#fff",
  },
  error: {
    padding: "12px",
    backgroundColor: "#ff4444",
    color: "#fff",
    borderRadius: "6px",
    fontSize: "0.9rem",
  },
  form: {
    backgroundColor: "#1a1a1a",
    padding: "20px",
    borderRadius: "8px",
    border: "1px solid #333",
  },
  formTitle: {
    fontSize: "1.1rem",
    marginBottom: "15px",
    color: "#fff",
  },
  formField: {
    marginBottom: "15px",
  },
  label: {
    display: "block" as const,
    marginBottom: "5px",
    fontSize: "0.9rem",
    color: "#ccc",
  },
  input: {
    width: "100%",
    padding: "8px 12px",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "0.9rem",
  },
  pathFieldRow: {
    display: "flex" as const,
    gap: "10px",
  },
  pickerContainer: {
    marginTop: "10px",
    padding: "15px",
    backgroundColor: "#222",
    borderRadius: "6px",
    border: "1px solid #444",
  },
  checkboxLabel: {
    display: "flex" as const,
    alignItems: "center" as const,
    gap: "8px",
    fontSize: "0.9rem",
    color: "#ccc",
    cursor: "pointer" as const,
  },
  checkbox: {
    width: "18px",
    height: "18px",
    cursor: "pointer" as const,
  },
  formActions: {
    display: "flex" as const,
    gap: "10px",
    marginTop: "20px",
  },
  btnPrimary: {
    padding: "10px 20px",
    backgroundColor: "#4a9eff",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    fontSize: "0.9rem",
    fontWeight: "bold" as const,
    cursor: "pointer" as const,
  },
  btnSecondary: {
    padding: "10px 20px",
    backgroundColor: "#333",
    color: "#fff",
    border: "1px solid #555",
    borderRadius: "6px",
    fontSize: "0.9rem",
    cursor: "pointer" as const,
  },
  emptyState: {
    padding: "40px",
    textAlign: "center" as const,
    color: "#888",
    fontStyle: "italic" as const,
  },
  librariesList: {
    display: "flex" as const,
    flexDirection: "column" as const,
    gap: "15px",
  },
  libraryCard: {
    backgroundColor: "#1a1a1a",
    padding: "20px",
    borderRadius: "8px",
    border: "1px solid #333",
  },
  libraryHeader: {
    display: "flex" as const,
    justifyContent: "space-between" as const,
    alignItems: "flex-start" as const,
    marginBottom: "15px",
  },
  libraryName: {
    fontSize: "1.1rem",
    margin: "0 0 5px 0",
    color: "#fff",
    display: "flex" as const,
    alignItems: "center" as const,
    gap: "10px",
  },
  libraryPath: {
    fontSize: "0.85rem",
    color: "#888",
    margin: 0,
    fontFamily: "monospace",
  },
  libraryStatus: {
    display: "flex" as const,
    alignItems: "center" as const,
    gap: "6px",
    fontSize: "0.85rem",
    color: "#ccc",
  },
  statusDot: {
    width: "8px",
    height: "8px",
    borderRadius: "50%",
  },
  badge: {
    fontSize: "0.75rem",
    padding: "3px 8px",
    backgroundColor: "#4a9eff",
    color: "#fff",
    borderRadius: "4px",
    fontWeight: "bold" as const,
  },
  libraryActions: {
    display: "flex" as const,
    gap: "10px",
  },
  btnSmall: {
    padding: "6px 12px",
    backgroundColor: "#333",
    color: "#fff",
    border: "1px solid #555",
    borderRadius: "4px",
    fontSize: "0.85rem",
    cursor: "pointer" as const,
  },
  btnScan: {
    backgroundColor: "#4caf50",
    borderColor: "#4caf50",
  },
};
