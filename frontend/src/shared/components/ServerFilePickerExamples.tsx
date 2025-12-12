/**
 * ServerFilePicker Usage Examples
 *
 * This file demonstrates how to integrate the ServerFilePicker component
 * into your forms and pages.
 *
 * The component supports three modes:
 * - "file": Only files are selectable
 * - "directory": Only directories are selectable (default)
 * - "either": Both files and directories can be selected
 */

import { useState } from "react";

import { ServerFilePicker } from "../components/ServerFilePicker";

/**
 * Example 1: File Selection (mode="file")
 *
 * Use case: User needs to select a single audio file for processing or tagging.
 */
export function FileSelectionExample() {
  const [selectedFile, setSelectedFile] = useState<string>("");

  const handleSubmit = () => {
    console.log("Selected file:", selectedFile);
    // Process the selected file...
  };

  return (
    <div>
      <h2>Select an Audio File</h2>
      <ServerFilePicker
        value={selectedFile}
        onChange={setSelectedFile}
        mode="file"
        label="Audio File"
      />
      <button onClick={handleSubmit} disabled={!selectedFile}>
        Process File
      </button>
    </div>
  );
}

/**
 * Example 2: Directory Selection (mode="directory")
 *
 * Use case: User needs to select a library directory for scanning.
 */
export function DirectorySelectionExample() {
  const [selectedDir, setSelectedDir] = useState<string>("");

  const handleScan = () => {
    console.log("Scanning directory:", selectedDir);
    // Start library scan...
  };

  return (
    <div>
      <h2>Select Library Directory</h2>
      <ServerFilePicker
        value={selectedDir}
        onChange={setSelectedDir}
        mode="directory"
        label="Library Directory"
      />
      <button onClick={handleScan} disabled={!selectedDir}>
        Scan Library
      </button>
    </div>
  );
}

/**
 * Example 3: Either File or Directory (mode="either")
 *
 * Use case: User can select either a specific file or an entire directory.
 */
export function EitherModeExample() {
  const [selectedPath, setSelectedPath] = useState<string>("");

  const handleProcess = () => {
    console.log("Processing path:", selectedPath);
    // Process file or directory...
  };

  return (
    <div>
      <h2>Select File or Directory</h2>
      <ServerFilePicker
        value={selectedPath}
        onChange={setSelectedPath}
        mode="either"
        label="Path"
      />
      <button onClick={handleProcess} disabled={!selectedPath}>
        Process
      </button>
    </div>
  );
}

/**
 * Example 4: Form Integration with Manual Path Input
 *
 * Use case: User can either browse with picker OR manually type a path.
 */
export function FormIntegrationExample() {
  const [libraryPath, setLibraryPath] = useState<string>("");
  const [showPicker, setShowPicker] = useState<boolean>(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    console.log("Library path:", libraryPath);
    // Save configuration...
  };

  return (
    <form onSubmit={handleSubmit}>
      <h2>Library Configuration</h2>

      <div className="form-field">
        <label htmlFor="library-path">Library Path</label>
        <input
          id="library-path"
          type="text"
          value={libraryPath}
          onChange={(e) => setLibraryPath(e.target.value)}
          placeholder="e.g., music/albums"
        />
        <button type="button" onClick={() => setShowPicker(!showPicker)}>
          {showPicker ? "Hide" : "Browse..."}
        </button>
      </div>

      {showPicker && (
        <ServerFilePicker
          value={libraryPath}
          onChange={(newPath) => {
            setLibraryPath(newPath);
            setShowPicker(false); // Close picker after selection
          }}
          mode="directory"
          label="Browse Library"
        />
      )}

      <button type="submit" disabled={!libraryPath}>
        Save Configuration
      </button>
    </form>
  );
}

/**
 * Example 5: Modal/Dialog Integration
 *
 * Use case: Open picker in a modal dialog for cleaner UI.
 */
export function ModalPickerExample() {
  const [selectedPath, setSelectedPath] = useState<string>("");
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [tempPath, setTempPath] = useState<string>("");

  const handleOpenModal = () => {
    setTempPath(selectedPath);
    setIsModalOpen(true);
  };

  const handleConfirm = () => {
    setSelectedPath(tempPath);
    setIsModalOpen(false);
  };

  const handleCancel = () => {
    setIsModalOpen(false);
  };

  return (
    <div>
      <h2>Path Selection with Modal</h2>

      <div className="form-field">
        <label>Selected Path:</label>
        <input type="text" value={selectedPath} readOnly />
        <button type="button" onClick={handleOpenModal}>
          Browse...
        </button>
      </div>

      {isModalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Select a File</h3>
            <ServerFilePicker
              value={tempPath}
              onChange={setTempPath}
              mode="file"
            />
            <div className="modal-actions">
              <button onClick={handleConfirm}>Confirm</button>
              <button onClick={handleCancel}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
