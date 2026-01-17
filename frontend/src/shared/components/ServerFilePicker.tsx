/**
 * ServerFilePicker - Reusable component for browsing filesystem on server
 *
 * Allows users to navigate directories and select files or folders relative
 * to the library root. Provides breadcrumb navigation and sorted directory listing.
 *
 * Props:
 * - value: Current selected path (relative to library root)
 * - onChange: Callback when path is selected
 * - mode: Selection mode (optional, defaults to "directory"):
 *   - "file"      → only files are selectable
 *   - "directory" → only directories are selectable
 *   - "either"    → both files and directories can be selected
 * - label: Optional label to display above picker
 */

import { useCallback, useEffect, useState } from "react";

import { listFs } from "../api/filesystem";
import type { FsEntry } from "../types";

import "./ServerFilePicker.css";

export interface ServerFilePickerProps {
  /** Current selected path (relative to library root) */
  value: string;

  /** Callback when path is selected */
  onChange: (path: string) => void;

  /** Selection mode: "file" (files only), "directory" (directories only), or "either" (both) */
  mode?: "file" | "directory" | "either";

  /** Optional label to display above picker */
  label?: string;

  /**
   * Optional library root path to enforce as boundary.
   * If provided, navigation is restricted to this path and its subdirectories.
   * Paths are resolved server-side.
   */
  libraryRoot?: string;
}

/**
 * ServerFilePicker Component
 *
 * Provides server-side filesystem browsing with:
 * - Breadcrumb navigation
 * - Directory traversal
 * - File/directory selection based on mode
 * - Error handling
 *
 * Behavior by mode:
 * - "file": Click directories to navigate, click files to select
 * - "directory": Click directories to navigate, use "Select this folder" button to select
 * - "either": Click directories to navigate or use button to select, click files to select
 */
export function ServerFilePicker({
  value,
  onChange,
  mode = "directory",
  label,
  libraryRoot,
}: ServerFilePickerProps) {
  const effectiveMode = mode ?? "directory";

  const [currentPath, setCurrentPath] = useState<string>("");
  const [entries, setEntries] = useState<FsEntry[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Load directory contents from server
   */
  const loadDirectory = useCallback(
    async (path: string) => {
      setLoading(true);
      setError(null);

      try {
        // If libraryRoot is set, prepend it to the path for the API call
        const apiPath = libraryRoot
          ? path
            ? `${libraryRoot}/${path}`
            : libraryRoot
          : path || undefined;

        const response = await listFs(apiPath);
        setEntries(response.entries);
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to load directory";
        setError(errorMessage);
        setEntries([]);
      } finally {
        setLoading(false);
      }
    },
    [libraryRoot]
  );

  // Load directory on mount and when currentPath changes
  useEffect(() => {
    loadDirectory(currentPath);
  }, [currentPath, loadDirectory]);

  /**
   * Navigate into a subdirectory
   */
  const navigateToDirectory = (dirName: string) => {
    const newPath = currentPath ? `${currentPath}/${dirName}` : dirName;
    setCurrentPath(newPath);
  };

  /**
   * Navigate to a specific breadcrumb segment
   */
  const navigateToBreadcrumb = (index: number) => {
    const segments = currentPath.split("/").filter((s) => s);
    const newPath = segments.slice(0, index + 1).join("/");
    setCurrentPath(newPath);
  };

  /**
   * Navigate to library root
   */
  const navigateToRoot = () => {
    setCurrentPath("");
  };

  /**
   * Handle selection of a file or directory
   *
   * Behavior:
   * - Directories: Always navigate into them (selection via button only)
   * - Files:
   *   - mode="file" or mode="either": Select the file
   *   - mode="directory": Do nothing (files not selectable)
   */
  const handleSelect = (entry: FsEntry) => {
    if (entry.is_dir) {
      // Always navigate into directories when clicked
      navigateToDirectory(entry.name);
    } else {
      // File clicked
      if (effectiveMode === "file" || effectiveMode === "either") {
        // Select file if mode allows it
        const selectedPath = currentPath
          ? `${currentPath}/${entry.name}`
          : entry.name;
        onChange(selectedPath);
      }
      // If mode === "directory", do nothing (files not selectable)
    }
  };

  /**
   * Handle selecting the current directory (when mode is "directory" or "either")
   */
  const handleSelectCurrentDirectory = () => {
    if (effectiveMode === "directory" || effectiveMode === "either") {
      onChange(currentPath);
    }
  };

  /**
   * Check if an entry is selectable (for styling purposes)
   */
  const isEntrySelectable = (entry: FsEntry): boolean => {
    if (entry.is_dir) {
      return false; // Directories are for navigation only
    }
    // Files are selectable in "file" or "either" mode
    return effectiveMode === "file" || effectiveMode === "either";
  };

  // Build breadcrumb segments
  const pathSegments = currentPath.split("/").filter((s) => s);

  return (
    <div className="server-file-picker">
      {label && <label className="picker-label">{label}</label>}

      {/* Breadcrumb Navigation */}
      <div className="breadcrumbs">
        <button
          type="button"
          className="breadcrumb-item root"
          onClick={navigateToRoot}
        >
          Library Root
        </button>
        {pathSegments.map((segment, index) => (
          <span key={index}>
            <span className="breadcrumb-separator">/</span>
            <button
              type="button"
              className="breadcrumb-item"
              onClick={() => navigateToBreadcrumb(index)}
            >
              {segment}
            </button>
          </span>
        ))}
      </div>

      {/* Current Path Display */}
      <div className="current-path">
        <strong>Current:</strong> /{currentPath || ""}
      </div>

      {/* Select Current Directory Button (for directory or either mode) */}
      {(effectiveMode === "directory" || effectiveMode === "either") && (
        <div className="select-current">
          <button
            type="button"
            className="btn-select-current"
            onClick={handleSelectCurrentDirectory}
          >
            Select This Folder
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading && <div className="loading">Loading...</div>}

      {/* Error State */}
      {error && <div className="error">{error}</div>}

      {/* Directory Listing */}
      {!loading && !error && entries.length === 0 && (
        <div className="empty">Empty directory</div>
      )}

      {!loading && !error && entries.length > 0 && (
        <ul className="entries-list">
          {entries.map((entry, index) => {
            const selectable = isEntrySelectable(entry);
            const isSelected =
              value &&
              value ===
                (currentPath ? `${currentPath}/${entry.name}` : entry.name);

            return (
              <li key={index} className="entry-item">
                <button
                  type="button"
                  className={`entry-button ${
                    entry.is_dir ? "directory" : "file"
                  } ${selectable ? "selectable" : "non-selectable"} ${
                    isSelected ? "selected" : ""
                  }`}
                  onClick={() => handleSelect(entry)}
                  disabled={!entry.is_dir && !selectable}
                >
                  <span className="entry-icon">
                    {entry.is_dir ? "📁" : "🎵"}
                  </span>
                  <span className="entry-name">{entry.name}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {/* Selected Value Display */}
      <div className="selected-value">
        <strong>Selected:</strong> {value || "(none)"}
      </div>
    </div>
  );
}
