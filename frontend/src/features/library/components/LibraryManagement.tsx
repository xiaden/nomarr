/**
 * LibraryManagement - CRUD interface for managing multiple libraries
 *
 * Features:
 * - List all libraries with status indicators
 * - Create new libraries with path picker
 * - Edit library properties (name, path, enabled)
 * - Scan individual libraries
 */

import {
  Box,
  Button,
  Checkbox,
  Chip,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog, ErrorMessage, Panel, SectionHeader } from "@shared/components/ui";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { useNotification } from "../../../hooks/useNotification";
import { getConfig } from "../../../shared/api/config";
import {
  create as createLibrary,
  deleteLibrary,
  getReconcileStatus,
  list as listLibraries,
  reconcileTags,
  scan as scanLibrary,
  update as updateLibrary,
} from "../../../shared/api/library";
import { getWorkStatus } from "../../../shared/api/processing";
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
  const [libraryRoot, setLibraryRoot] = useState<string | null>(null);

  // Create/edit form state
  const [formName, setFormName] = useState("");
  const [formRootPath, setFormRootPath] = useState("");
  const [formIsEnabled, setFormIsEnabled] = useState(true);
  const [formWatchMode, setFormWatchMode] = useState<string>("off");
  const [formFileWriteMode, setFormFileWriteMode] = useState<"none" | "minimal" | "full">("full");
  const [showPathPicker, setShowPathPicker] = useState(false);
  const [reconcilingId, setReconcilingId] = useState<string | null>(null);
  const [reconcileStatus, setReconcileStatus] = useState<Record<string, { pending: number; inProgress: boolean }>>({});

  // Initial load - shows loading state
  const loadLibraries = useCallback(async () => {
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
  }, []);

  // Silent refresh - merges updates without loading state, only updates changed fields
  const refreshLibraries = useCallback(async () => {
    try {
      const freshData = await listLibraries();
      setLibraries(prev => {
        // If lengths differ, full replacement needed (library added/removed)
        if (prev.length !== freshData.length) {
          return freshData;
        }
        // Build lookup for quick access
        const freshMap = new Map(freshData.map(lib => [lib.library_id, lib]));
        
        // Check if any library actually changed
        let hasChanges = false;
        for (const lib of prev) {
          const fresh = freshMap.get(lib.library_id);
          if (!fresh) {
            // Library removed
            hasChanges = true;
            break;
          }
          // Check fields that can change during scan
          if (
            lib.scanStatus !== fresh.scanStatus ||
            lib.scanProgress !== fresh.scanProgress ||
            lib.scanTotal !== fresh.scanTotal ||
            lib.scanError !== fresh.scanError ||
            lib.scannedAt !== fresh.scannedAt ||
            lib.fileCount !== fresh.fileCount ||
            lib.folderCount !== fresh.folderCount
          ) {
            hasChanges = true;
            break;
          }
        }
        
        // No changes - return same reference to prevent re-render
        if (!hasChanges) {
          return prev;
        }
        
        // Merge: keep existing objects where unchanged, update only changed libraries
        return prev.map(lib => {
          const fresh = freshMap.get(lib.library_id);
          if (!fresh) return lib;
          
          // Check if this specific library changed
          if (
            lib.scanStatus === fresh.scanStatus &&
            lib.scanProgress === fresh.scanProgress &&
            lib.scanTotal === fresh.scanTotal &&
            lib.scanError === fresh.scanError &&
            lib.scannedAt === fresh.scannedAt &&
            lib.fileCount === fresh.fileCount &&
            lib.folderCount === fresh.folderCount
          ) {
            return lib; // Same reference - no re-render for this item
          }
          
          return fresh; // New object - triggers re-render for this item only
        });
      });
    } catch (err) {
      // Silent fail during background refresh - don't disrupt UI
      console.error("[LibraryManagement] Refresh error:", err);
    }
  }, []);

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
  }, [loadLibraries]);

  // Poll for scan/work status updates using unified work-status endpoint
  useEffect(() => {
    // Check work status to determine if we should poll
    let active = true;
    let interval: ReturnType<typeof setInterval> | null = null;

    const checkAndPoll = async () => {
      try {
        const status = await getWorkStatus();
        if (!active) return;

        // If busy (scanning or processing), poll with silent refresh
        if (status.is_busy) {
          if (!interval) {
            // Use 500ms for smoother updates during active work
            interval = setInterval(() => {
              refreshLibraries();
            }, 500);
          }
        } else {
          // Not busy - stop polling and do one final refresh
          if (interval) {
            clearInterval(interval);
            interval = null;
            // Final refresh to catch any last updates
            refreshLibraries();
          }
        }
      } catch (err) {
        console.error("[LibraryManagement] Failed to check work status:", err);
      }
    };

    // Initial check
    checkAndPoll();

    // Check work status every 5 seconds to adapt polling
    const statusInterval = setInterval(checkAndPoll, 5000);

    return () => {
      active = false;
      if (interval) clearInterval(interval);
      clearInterval(statusInterval);
    };
  }, [refreshLibraries]);

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
    setFormWatchMode("off");
    setFormFileWriteMode("full");
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
    setFormWatchMode(library.watchMode);
    setFormFileWriteMode(library.fileWriteMode);
    setEditingId(library.library_id);
    setIsCreating(false);
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
        watchMode: formWatchMode,
        fileWriteMode: formFileWriteMode,
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
        watchMode: formWatchMode,
        fileWriteMode: formFileWriteMode,
      });
      await loadLibraries();
      resetForm();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update library"
      );
    }
  };

  const handleScan = async (id: string, scanType: "quick" | "full") => {
    try {
      setError(null);
      setScanningId(id);

      const result = await scanLibrary(id, scanType);
      showSuccess(
        result.message || `Library scan started (${result.stats?.files_queued ?? 0} files)`
      );
      await loadLibraries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to scan library");
    } finally {
      setScanningId(null);
    }
  };

  const handleDelete = async (id: string, name: string) => {
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

  const handleWatchModeChange = async (id: string, newMode: string) => {
    try {
      setError(null);
      await updateLibrary(id, { watchMode: newMode });
      await loadLibraries();
      showSuccess(`File watching mode changed to ${newMode}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change watch mode");
    }
  };

  const getWatchModeLabel = (mode: string) => {
    switch (mode) {
      case "event": return "Event";
      case "poll": return "Poll";
      default: return "Off";
    }
  };

  const getWatchModeColor = (mode: string): "default" | "success" | "warning" => {
    switch (mode) {
      case "event": return "success";
      case "poll": return "warning";
      default: return "default";
    }
  };

  const getWriteModeLabel = (mode: "none" | "minimal" | "full") => {
    switch (mode) {
      case "none": return "None";
      case "minimal": return "Minimal";
      case "full": return "Full";
    }
  };

  const getWriteModeColor = (mode: "none" | "minimal" | "full"): "default" | "primary" | "secondary" => {
    switch (mode) {
      case "none": return "default";
      case "minimal": return "secondary";
      case "full": return "primary";
    }
  };

  const handleReconcileTags = async (libraryId: string) => {
    try {
      setError(null);
      setReconcilingId(libraryId);
      const result = await reconcileTags(libraryId);
      showSuccess(
        `Reconciled ${result.processed} files (${result.remaining} remaining, ${result.failed} failed)`
      );
      // Update reconcile status
      const status = await getReconcileStatus(libraryId);
      setReconcileStatus(prev => ({
        ...prev,
        [libraryId]: { pending: status.pending_count, inProgress: status.in_progress }
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reconcile tags");
    } finally {
      setReconcilingId(null);
    }
  };

  const loadReconcileStatus = async (libraryId: string) => {
    try {
      const status = await getReconcileStatus(libraryId);
      setReconcileStatus(prev => ({
        ...prev,
        [libraryId]: { pending: status.pending_count, inProgress: status.in_progress }
      }));
    } catch {
      // Silently ignore errors for status checks
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

            {/* Watch Mode Selection */}
            <Box>
              <FormControl fullWidth>
                <InputLabel id="watch-mode-label">File Watching</InputLabel>
                <Select
                  labelId="watch-mode-label"
                  value={formWatchMode}
                  label="File Watching"
                  onChange={(e) => setFormWatchMode(e.target.value)}
                >
                  <MenuItem value="off">
                    <Stack>
                      <Typography><strong>Off</strong> - No automatic scanning</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Manual scans only
                      </Typography>
                    </Stack>
                  </MenuItem>
                  <MenuItem value="event">
                    <Stack>
                      <Typography><strong>Event</strong> - Real-time file watching</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Fast (2-5s response), local filesystems only
                      </Typography>
                    </Stack>
                  </MenuItem>
                  <MenuItem value="poll">
                    <Stack>
                      <Typography><strong>Poll</strong> - Periodic scanning</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Slower (60s interval), network-mount-safe
                      </Typography>
                    </Stack>
                  </MenuItem>
                </Select>
              </FormControl>
            </Box>

            {/* File Write Mode Selection */}
            <Box>
              <FormControl fullWidth>
                <InputLabel id="write-mode-label">Tag Writing Mode</InputLabel>
                <Select
                  labelId="write-mode-label"
                  value={formFileWriteMode}
                  label="Tag Writing Mode"
                  onChange={(e) => setFormFileWriteMode(e.target.value as "none" | "minimal" | "full")}
                >
                  <MenuItem value="none">
                    <Stack>
                      <Typography><strong>None</strong> - Don't write tags to files</Typography>
                      <Typography variant="caption" color="text.secondary">
                        DB is source of truth; clears existing nomarr tags
                      </Typography>
                    </Stack>
                  </MenuItem>
                  <MenuItem value="minimal">
                    <Stack>
                      <Typography><strong>Minimal</strong> - Mood tags only</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Write mood-strict, mood-regular, mood-loose
                      </Typography>
                    </Stack>
                  </MenuItem>
                  <MenuItem value="full">
                    <Stack>
                      <Typography><strong>Full</strong> - All tags</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Write all ML-derived tags to audio files
                      </Typography>
                    </Stack>
                  </MenuItem>
                </Select>
              </FormControl>
            </Box>

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
            <Panel key={lib.library_id}>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="flex-start"
                sx={{ mb: 2 }}
              >
                <Box>
                  <Stack direction="row" alignItems="center" spacing={1.25} sx={{ mb: 0.5 }}>
                    <Typography variant="h6">{lib.name}</Typography>
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
                  {/* File and Folder Statistics */}
                  <Stack direction="row" spacing={2} sx={{ mt: 0.5 }}>
                    <Typography variant="body2" color="text.secondary">
                      <strong>{lib.fileCount.toLocaleString()}</strong> files
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      <strong>{lib.folderCount.toLocaleString()}</strong> folders
                    </Typography>
                  </Stack>
                  {/* Scan Progress Indicator */}
                  {lib.scanStatus === "scanning" && (
                    <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 0.5 }}>
                      <Chip 
                        label="Scanning..." 
                        color="info" 
                        size="small"
                        sx={{ animation: "pulse 1.5s infinite" }}
                      />
                      {lib.scanProgress != null && lib.scanTotal != null && lib.scanTotal > 0 && (
                        <Typography variant="body2" color="info.main">
                          {lib.scanProgress.toLocaleString()} / {lib.scanTotal.toLocaleString()} files
                          {" "}({Math.round((lib.scanProgress / lib.scanTotal) * 100)}%)
                        </Typography>
                      )}
                    </Stack>
                  )}
                  {lib.scanStatus === "error" && lib.scanError && (
                    <Typography variant="caption" color="error.main" sx={{ mt: 0.5 }}>
                      ⚠ Scan error: {lib.scanError}
                    </Typography>
                  )}
                  {isOutsideLibraryRoot(lib.rootPath) && (
                    <Typography variant="caption" color="warning.main" sx={{ mt: 0.5 }}>
                      ⚠ This library is outside the configured library_root ({libraryRoot})
                    </Typography>
                  )}
                  {/* Watch Mode Indicator and Quick Changer */}
                  <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 1 }}>
                    <Typography variant="caption" color="text.secondary">
                      File Watching:
                    </Typography>
                    <FormControl size="small" sx={{ minWidth: 120 }}>
                      <Select
                        value={lib.watchMode}
                        onChange={(e) => handleWatchModeChange(lib.library_id, e.target.value)}
                        size="small"
                        sx={{ fontSize: "0.75rem" }}
                        disabled={scanningId === lib.library_id}
                      >
                        <MenuItem value="off">Off</MenuItem>
                        <MenuItem value="event">Event</MenuItem>
                        <MenuItem value="poll">Poll</MenuItem>
                      </Select>
                    </FormControl>
                    <Tooltip title={
                      lib.watchMode === "event" 
                        ? "Real-time file watching (local filesystems)"
                        : lib.watchMode === "poll"
                        ? "Periodic scanning (network-mount-safe)"
                        : "No automatic file watching"
                    }>
                      <Chip 
                        label={getWatchModeLabel(lib.watchMode)}
                        color={getWatchModeColor(lib.watchMode)}
                        size="small"
                      />
                    </Tooltip>
                  </Stack>
                  {/* Tag Write Mode Indicator */}
                  <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 0.5 }}>
                    <Typography variant="caption" color="text.secondary">
                      Tag Writing:
                    </Typography>
                    <Tooltip title={
                      lib.fileWriteMode === "full"
                        ? "All ML-derived tags written to audio files"
                        : lib.fileWriteMode === "minimal"
                        ? "Only mood tags written to audio files"
                        : "No tags written to audio files (DB only)"
                    }>
                      <Chip 
                        label={getWriteModeLabel(lib.fileWriteMode)}
                        color={getWriteModeColor(lib.fileWriteMode)}
                        size="small"
                      />
                    </Tooltip>
                    {reconcileStatus[lib.library_id]?.pending > 0 && (
                      <Chip 
                        label={`${reconcileStatus[lib.library_id].pending} pending`}
                        color="warning"
                        size="small"
                      />
                    )}
                  </Stack>
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
                  disabled={scanningId === lib.library_id}
                >
                  Edit
                </Button>
                <Button
                  variant="outlined"
                  color="success"
                  size="small"
                  onClick={() => handleScan(lib.library_id, "quick")}
                  disabled={
                    !lib.isEnabled || 
                    scanningId === lib.library_id || 
                    lib.scanStatus === "scanning" ||
                    isOutsideLibraryRoot(lib.rootPath) ||
                    !lib.scannedAt  // Disable if never scanned
                  }
                  title={
                    !lib.scannedAt
                      ? "Run a Full Scan first before using Quick Scan"
                      : lib.scanStatus === "scanning"
                      ? "Scan already in progress"
                      : isOutsideLibraryRoot(lib.rootPath)
                      ? "Cannot scan: library is outside library_root"
                      : "Scan only new and modified files"
                  }
                >
                  {scanningId === lib.library_id || lib.scanStatus === "scanning"
                    ? "Scanning..."
                    : "Quick Scan"}
                </Button>
                <Button
                  variant="contained"
                  color="success"
                  size="small"
                  onClick={() => handleScan(lib.library_id, "full")}
                  disabled={
                    !lib.isEnabled || 
                    scanningId === lib.library_id || 
                    lib.scanStatus === "scanning" ||
                    isOutsideLibraryRoot(lib.rootPath)
                  }
                  title={
                    lib.scanStatus === "scanning"
                      ? "Scan already in progress"
                      : isOutsideLibraryRoot(lib.rootPath)
                      ? "Cannot scan: library is outside library_root"
                      : "Rescan all files in the library"
                  }
                >
                  {scanningId === lib.library_id || lib.scanStatus === "scanning"
                    ? "Scanning..."
                    : "Full Scan"}
                </Button>
                <Button
                  variant="outlined"
                  color="secondary"
                  size="small"
                  onClick={() => handleReconcileTags(lib.library_id)}
                  disabled={
                    !lib.isEnabled || 
                    reconcilingId === lib.library_id ||
                    lib.scanStatus === "scanning"
                  }
                  title={
                    reconcilingId === lib.library_id
                      ? "Reconciling tags..."
                      : "Write tags from database to audio files"
                  }
                  onMouseEnter={() => loadReconcileStatus(lib.library_id)}
                >
                  {reconcilingId === lib.library_id
                    ? "Reconciling..."
                    : "Reconcile Tags"}
                </Button>
                <Button
                  variant="contained"
                  color="error"
                  size="small"
                  onClick={() => handleDelete(lib.library_id, lib.name)}
                  disabled={scanningId === lib.library_id}
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

