/**
 * Calibration Manager
 * Handles model calibration generation from library data.
 */

import { UIHelpers } from "./ui.js";

export class CalibrationManager {
  constructor(app) {
    this.app = app;
    this.init();
  }

  init() {
    const generateBtn = document.getElementById("btn-generate-calibration");
    if (generateBtn) {
      generateBtn.addEventListener("click", () => this.generateCalibration());
    }
  }

  async generateCalibration() {
    const method = document.getElementById("calibration-method").value;
    const generateBtn = document.getElementById("btn-generate-calibration");
    const resultDiv = document.getElementById("calibration-result");
    const consoleDiv = document.getElementById("calibration-console");

    // Disable button and show loading state
    generateBtn.disabled = true;
    generateBtn.textContent = "Analyzing library...";
    resultDiv.style.display = "none";
    consoleDiv.innerHTML = "";
    try {
      const response = await fetch("/web/api/calibration/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          save_sidecars: true,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || `HTTP ${response.status}`);
      }

      const result = await response.json();
      const data = result.data;
      const savedFiles = result.saved_files;

      // Show results
      resultDiv.style.display = "block";

      // Update stats
      document.getElementById("calib-library-size").textContent =
        data.library_size.toLocaleString();
      document.getElementById("calib-tags-calibrated").textContent =
        Object.keys(data.calibrations).length;
      document.getElementById("calib-files-saved").textContent = savedFiles
        ? savedFiles.total_files
        : 0;

      // Build console output
      let output = "✓ Calibration generation complete\n\n";
      output += `Method: ${method}\n`;
      output += `Library size: ${data.library_size.toLocaleString()} files\n`;
      output += `Min samples threshold: ${data.min_samples}\n`;
      output += `Tags calibrated: ${Object.keys(data.calibrations).length}\n`;
      output += `Tags skipped (low samples): ${data.skipped_tags}\n\n`;

      if (savedFiles && savedFiles.total_files > 0) {
        output += `✓ Saved ${savedFiles.total_files} calibration file(s):\n\n`;
        for (const [path, info] of Object.entries(savedFiles.saved_files)) {
          const filename = path.split(/[/\\]/).pop();
          output += `  • ${filename}\n`;
          output += `    Labels: ${info.labels.join(", ")}\n`;
        }
      } else {
        output += "⚠ No calibration files saved (no matching models found)\n";
      }

      consoleDiv.textContent = output;

      UIHelpers.showSuccess(
        `Generated calibrations for ${
          Object.keys(data.calibrations).length
        } tags, ` + `saved ${savedFiles ? savedFiles.total_files : 0} file(s)`
      );
    } catch (error) {
      console.error("Calibration generation failed:", error);
      UIHelpers.showError(`Calibration failed: ${error.message}`);
      consoleDiv.textContent = `✗ Error: ${error.message}`;
      resultDiv.style.display = "block";
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = "Generate Calibration for All Models";
    }
  }
}
