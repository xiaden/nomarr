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

import {
    Box,
    Button,
    Checkbox,
    Chip,
    FormControlLabel,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { ConfirmDialog, ErrorMessage, Panel, SectionHeader } from "@shared/components/ui";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { useNotification } from "../../../hooks/useNotification";
import { getConfig } from "../../../shared/api/config";
import {
    create as createLibrary,
    deleteLibrary,
    list as listLibraries,
    preview as previewLibrary,
    scan as scanLibrary,
    setDefault as setDefaultLibrary,
    update as updateLibrary,
} from "../../../shared/api/library";
import { ServerFilePicker } from "../../../shared/components/ServerFilePicker";
import type { Library } from "../../../shared/types";

export function LibraryManagement() {
  const { showSuccess } = useNotification();
  const { confirm, isOpen, options, handleConfirm, handleCancel } = useConfirmDialog();

  const [libraries, setLibraries] = useState<Library[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [scanningId, setScanningId] = useState<string | null>(null);
  const [scanningState, setScanningState] = useState<"preparing" | "queueing" | null>(null);
  const [libraryRoot, setLibraryRoot] = useState<string | null>(null);

  // Create/edit form state
  const [formName, setFormName] = useState("");
  const [formRootPath, setFormRootPath] = useState("");
  const [formIsEnabled, setFormIsEnabled] = useState(true);
  const [formIsDefault, setFormIsDefault] = useState(false);
  const [showPathPicker, setShowPathPicker] = useState(false);
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const loadLibraries = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listLibraries();
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

  const loadConfig = async () => {
    try {
      const config = await getConfig();
      setLibraryRoot(config.library_root as string || null);
    } catch (err) {
      console.error("[LibraryManagement] Failed to load config:", err);
    }
  };

  useEffect(() => {
    loadLibraries();
    loadConfig();
  }, []);

  const isOutsideLibraryRoot = (path: string): boolean => {
    if (!libraryRoot) return false;
    // Normalize paths for comparison (handle trailing slashes)
    const normalizedRoot = libraryRoot.replace(/\/+$/, "");
    const normalizedPath = path.replace(/\/+$/, "");
    return !normalizedPath.startsWith(normalizedRoot);
  };

  const resetForm = () => {
    setFormName("");
    setFormRootPath("");
    setFormIsEnabled(true);
    setFormIsDefault(false);
    setShowPathPicker(false);
    setPreviewCount(null);
    setPreviewLoading(false);
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
    setPreviewCount(null);
    setPreviewLoading(false);
  };

  const handlePreview = async () => {
    if (!formRootPath.trim()) {
      setError("Path is required for preview");
      return;
    }

    // Need library ID for preview - only works when editing existing library
    if (editingId === null) {
      // For new libraries, we can't preview until they're created
      setError("Create the library first to preview file count");
      return;
    }

    try {
      setError(null);
      setPreviewLoading(true);
      // Don't send paths - let backend use library's root_path directly
      const result = await previewLibrary(editingId, {
        recursive: true,
      });
      setPreviewCount(result.file_count);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to preview library"
      );
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!formRootPath.trim()) {
      setError("Path is required");
      return;
    }

    try {
      setError(null);
      await createLibrary({
        name: formName.trim() || null,  // Optional: backend will auto-generate from path
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
    if (!formRootPath.trim()) {
      setError("Path is required");
      return;
    }

    try {
      setError(null);
      await updateLibrary(editingId, {
        name: formName.trim() || undefined,  // Keep existing name if empty
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

  const handleSetDefault = async (id: string) => {
    try {
      setError(null);
      await setDefaultLibrary(id);
      await loadLibraries();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to set default library"
      );
    }
  };

  const handleScan = async (id: string) => {
    try {
      setError(null);
      setScanningId(id);
      setScanningState("preparing");

      // Get preview first
      const preview = await previewLibrary(id, {
        recursive: true,
      });

      const confirmed = await confirm({
        title: "Start Library Scan?",
        message: `Found ${preview.file_count.toLocaleString()} audio files. Start scan?`,
      });

      if (!confirmed) {
        return;
      }

      // User confirmed - now queue the scan
      setScanningState("queueing");

      const result = await scanLibrary(id, {
        recursive: true,
        force: false,
        cleanMissing: true,
      });
      showSuccess(
        `Scan ${result.status}: ${result.message || "Library scan queued"}`
      );
      await loadLibraries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to scan library");
    } finally {
      setScanningId(null);
      setScanningState(null);
    }
  };

  const handleDelete = async (id: string, name: string, isDefault: boolean) => {
    if (isDefault) {
      setError("Cannot delete the default library. Set another library as default first.");
      return;
    }

    const confirmed = await confirm({
      title: "Delete Library?",
      message: `Delete library "${name}"?\n\nThis will remove the library entry but will NOT delete files on disk.`,
      severity: "warning",
    });

    if (!confirmed) return;

    try {
      setError(null);
      await deleteLibrary(id);
      await loadLibraries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete library");
    }
  };

  const isFormMode = isCreating || editingId !== null;

  return (
    <Stack spacing={2.5}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h5">Libraries</Typography>
        {!isFormMode && (
          <Button variant="contained" onClick={startCreate}>
            + Add Library
          </Button>
        )}
      </Stack>

      {error && <ErrorMessage>{error}</ErrorMessage>}

      {/* Create/Edit Form */}
      {isFormMode && (
        <Panel>
          <SectionHeader
            title={isCreating ? "Create Library" : "Edit Library"}
          />

          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                Name (optional)
              </Typography>
              <TextField
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="Auto-generated from path if left empty"
                fullWidth
              />
            </Box>

            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                Root Path
              </Typography>
              <Stack direction="row" spacing={1.25}>
                <TextField
                  value={formRootPath}
                  onChange={(e) => setFormRootPath(e.target.value)}
                  placeholder="/music"
                  fullWidth
                />
                <Button
                  variant="outlined"
                  onClick={() => setShowPathPicker(!showPathPicker)}
                  sx={{ minWidth: 120 }}
                >
                  {showPathPicker ? "Hide Picker" : "Browse..."}
                </Button>
              </Stack>
              {showPathPicker && (
                <Box
                  sx={{
                    mt: 1.25,
                    p: 2,
                    bgcolor: "background.default",
                    borderRadius: 1,
                    border: 1,
                    borderColor: "divider",
                  }}
                >
                  <ServerFilePicker
                    value={formRootPath}
                    onChange={(path) => {
                      setFormRootPath(path);
                      setShowPathPicker(false);
                    }}
                    mode="directory"
                    label="Select Library Root Directory"
                  />
                </Box>
              )}
            </Box>

            <FormControlLabel
              control={
                <Checkbox
                  checked={formIsEnabled}
                  onChange={(e) => setFormIsEnabled(e.target.checked)}
                />
              }
              label="Enabled"
            />

            <FormControlLabel
              control={
                <Checkbox
                  checked={formIsDefault}
                  onChange={(e) => setFormIsDefault(e.target.checked)}
                />
              }
              label="Default Library"
            />

            {/* Preview file count (only for existing libraries) */}
            {editingId !== null && (
              <Box>
                <Button
                  variant="outlined"
                  onClick={handlePreview}
                  disabled={!formRootPath.trim() || previewLoading}
                >
                  {previewLoading ? "Checking..." : "Preview File Count"}
                </Button>
                {previewCount !== null && (
                  <Box
                    sx={{
                      mt: 1,
                      p: 1.5,
                      bgcolor: "background.paper",
                      borderRadius: 1,
                      border: 1,
                      borderColor: "divider",
                    }}
                  >
                    <Typography>
                      <strong>{previewCount.toLocaleString()}</strong> audio files
                      found
                    </Typography>
                  </Box>
                )}
              </Box>
            )}

            <Stack direction="row" spacing={1.25}>
              <Button
                variant="contained"
                onClick={isCreating ? handleCreate : handleUpdate}
              >
                {isCreating ? "Create" : "Update"}
              </Button>
              <Button variant="outlined" onClick={resetForm}>
                Cancel
              </Button>
            </Stack>
          </Stack>
        </Panel>
      )}

      {/* Libraries List */}
      {loading && <Typography>Loading libraries...</Typography>}

      {!loading && !isFormMode && libraries.length === 0 && (
        <Panel>
          <Typography color="text.secondary" textAlign="center" fontStyle="italic">
            No libraries configured. Click "Add Library" to get started.
          </Typography>
        </Panel>
      )}

      {!loading && !isFormMode && libraries.length > 0 && (
        <Stack spacing={2}>
          {libraries.map((lib) => (
            <Panel key={lib.id}>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="flex-start"
                sx={{ mb: 2 }}
              >
                <Box>
                  <Stack direction="row" alignItems="center" spacing={1.25} sx={{ mb: 0.5 }}>
                    <Typography variant="h6">{lib.name}</Typography>
                    {lib.isDefault && (
                      <Chip label="Default" color="primary" size="small" />
                    )}
                    {isOutsideLibraryRoot(lib.rootPath) && (
                      <Chip
                        label="Outside library_root"
                        color="warning"
                        size="small"
                      />
                    )}
                  </Stack>
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ fontFamily: "monospace" }}
                  >
                    {lib.rootPath}
                  </Typography>
                  {isOutsideLibraryRoot(lib.rootPath) && (
                    <Typography variant="caption" color="warning.main" sx={{ mt: 0.5 }}>
                      ⚠ This library is outside the configured library_root ({libraryRoot})
                    </Typography>
                  )}
                </Box>
                <Stack direction="row" alignItems="center" spacing={1}>
                  <Box
                    sx={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      bgcolor: lib.isEnabled ? "success.main" : "text.disabled",
                    }}
                  />
                  <Typography variant="body2" color="text.secondary">
                    {lib.isEnabled ? "Enabled" : "Disabled"}
                  </Typography>
                </Stack>
              </Stack>

              <Stack direction="row" spacing={1.25} flexWrap="wrap">
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => startEdit(lib)}
                  disabled={scanningId === lib.id}
                >
                  Edit
                </Button>
                {!lib.isDefault && (
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() => handleSetDefault(lib.id)}
                    disabled={scanningId === lib.id}
                  >
                    Set Default
                  </Button>
                )}
                <Button
                  variant="contained"
                  color="success"
                  size="small"
                  onClick={() => handleScan(lib.id)}
                  disabled={
                    !lib.isEnabled || 
                    scanningId === lib.id || 
                    isOutsideLibraryRoot(lib.rootPath)
                  }
                  title={
                    isOutsideLibraryRoot(lib.rootPath)
                      ? "Cannot scan: library is outside library_root"
                      : undefined
                  }
                >
                  {scanningId === lib.id
                    ? scanningState === "preparing"
                      ? "Preparing..."
                      : "Queueing..."
                    : "Scan"}
                </Button>
                <Button
                  variant="contained"
                  color="error"
                  size="small"
                  onClick={() => handleDelete(lib.id, lib.name, lib.isDefault)}
                  disabled={scanningId === lib.id}
                >
                  Delete
                </Button>
              </Stack>
            </Panel>
          ))}
        </Stack>
      )}

      {/* Confirm dialog for scan and delete actions */}
      <ConfirmDialog
        open={isOpen}
        title={options.title}
        message={options.message}
        confirmLabel={options.confirmLabel}
        cancelLabel={options.cancelLabel}
        severity={options.severity}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Stack>
  );
}

