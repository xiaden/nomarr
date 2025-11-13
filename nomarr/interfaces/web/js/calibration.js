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

        const applyBtn = document.getElementById("btn-apply-calibration");
        if (applyBtn) {
            applyBtn.addEventListener("click", () => this.applyCalibration());
        }

        const refreshStatusBtn = document.getElementById(
            "btn-refresh-recalib-status"
        );
        if (refreshStatusBtn) {
            refreshStatusBtn.addEventListener("click", () =>
                this.refreshRecalibrationStatus()
            );
        }

        const clearQueueBtn = document.getElementById("btn-clear-recalib-queue");
        if (clearQueueBtn) {
            clearQueueBtn.addEventListener("click", () =>
                this.clearRecalibrationQueue()
            );
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

    async applyCalibration() {
        const applyBtn = document.getElementById("btn-apply-calibration");
        const resultDiv = document.getElementById("recalibration-result");

        // Disable button and show loading state
        applyBtn.disabled = true;
        applyBtn.textContent = "Queueing files...";

        try {
            const response = await fetch("/web/api/calibration/apply", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }

            const result = await response.json();

            // Show results
            resultDiv.style.display = "block";
            document.getElementById("recalib-queued").textContent =
        result.queued.toLocaleString();

            UIHelpers.showSuccess(result.message);

            // Start polling for status
            this.startRecalibrationPolling();
        } catch (error) {
            console.error("Apply calibration failed:", error);
            UIHelpers.showError(`Failed to queue recalibration: ${error.message}`);
        } finally {
            applyBtn.disabled = false;
            applyBtn.textContent = "Apply Calibration to All Library Files";
        }
    }

    async refreshRecalibrationStatus() {
        try {
            const response = await fetch("/web/api/calibration/status");

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }

            const status = await response.json();

            // Update stats
            document.getElementById("recalib-pending").textContent =
        status.pending.toLocaleString();
            document.getElementById("recalib-running").textContent =
        status.running.toLocaleString();
            document.getElementById("recalib-done").textContent =
        status.done.toLocaleString();
            document.getElementById("recalib-error").textContent =
        status.error.toLocaleString();

            // Update progress bar
            const total =
        status.pending + status.running + status.done + status.error;
            const progress = total > 0 ? (status.done / total) * 100 : 0;
            const progressBar = document.getElementById("recalibration-progress");
            progressBar.style.width = `${progress}%`;
            progressBar.textContent = `${Math.round(progress)}%`;

            // Continue polling if there are pending or running jobs
            if (status.pending > 0 || status.running > 0) {
                if (!this.recalibrationPollingInterval) {
                    this.startRecalibrationPolling();
                }
            } else {
                this.stopRecalibrationPolling();
            }
        } catch (error) {
            console.error("Failed to get recalibration status:", error);
        }
    }

    startRecalibrationPolling() {
        if (this.recalibrationPollingInterval) return;

        this.recalibrationPollingInterval = setInterval(() => {
            this.refreshRecalibrationStatus();
        }, 2000); // Poll every 2 seconds
    }

    stopRecalibrationPolling() {
        if (this.recalibrationPollingInterval) {
            clearInterval(this.recalibrationPollingInterval);
            this.recalibrationPollingInterval = null;
        }
    }

    async clearRecalibrationQueue() {
        if (
            !confirm(
                "Are you sure you want to clear the recalibration queue? This will remove all pending and completed jobs."
            )
        ) {
            return;
        }

        try {
            const response = await fetch("/web/api/calibration/clear", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }

            const result = await response.json();

            UIHelpers.showSuccess(result.message);

            // Refresh status to show cleared queue
            this.refreshRecalibrationStatus();
        } catch (error) {
            console.error("Failed to clear recalibration queue:", error);
            UIHelpers.showError(`Failed to clear queue: ${error.message}`);
        }
    }
}
