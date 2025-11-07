// Library Management Module
import { UIHelpers } from './ui.js';

export class LibraryManager {
    constructor(app) {
        this.app = app;
        this.statusPollInterval = null;
        this.scannerConfigured = false;
        this.scannerEnabled = false;
        this.currentScanId = null;
    }
    
    setupLibraryUI() {
        document.getElementById('btn-start-scan').onclick = () => this.startScan();
        document.getElementById('btn-cancel-scan').onclick = () => this.cancelScan();
        document.getElementById('btn-pause-scanner').onclick = () => this.pauseScanner();
        document.getElementById('btn-resume-scanner').onclick = () => this.resumeScanner();
        document.getElementById('btn-clear-library').onclick = () => this.clearLibrary();
    }
    
    async loadStatus() {
        try {
            const response = await fetch('/web/api/library/scan/status', {
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to load library scanner status');
            }
            
            const data = await response.json();
            this.updateStatus(data);
            
            // Start polling if scan is running
            if (data.current_scan_id && !this.statusPollInterval) {
                console.log('[Library] Detected running scan, starting status polling');
                this.startStatusPolling();
            }
            
        } catch (error) {
            console.error('[Library] Status error:', error);
        }
    }
    
    updateStatus(data) {
        this.scannerConfigured = data.configured;
        this.scannerEnabled = data.enabled;
        this.currentScanId = data.current_scan_id;
        
        // Update status badge
        const statusBadge = document.getElementById('library-scanner-status');
        if (!data.configured) {
            statusBadge.textContent = 'Not Configured';
            statusBadge.className = 'status-badge error';
            document.getElementById('library-path').textContent = 'Not configured';
            document.getElementById('btn-start-scan').disabled = true;
            return;
        }
        
        // Show library path when configured
        if (data.library_path) {
            document.getElementById('library-path').textContent = data.library_path;
        }
        
        // Enable start button when configured
        document.getElementById('btn-start-scan').disabled = false;
        
        if (!data.enabled) {
            statusBadge.textContent = 'Paused';
            statusBadge.className = 'status-badge warning';
        } else if (data.current_scan_id) {
            statusBadge.textContent = 'Scanning';
            statusBadge.className = 'status-badge success';
        } else {
            statusBadge.textContent = 'Ready';
            statusBadge.className = 'status-badge success';
        }
        
        // Update current scan status
        if (data.current_scan_id && data.current_progress) {
            document.getElementById('current-scan-status').textContent = `Scan #${data.current_scan_id} running...`;
            document.getElementById('scan-progress').style.display = 'block';
            document.getElementById('btn-start-scan').style.display = 'none';
            document.getElementById('btn-cancel-scan').style.display = 'inline-block';
            
            const progress = data.current_progress;
            document.getElementById('scan-files-scanned').textContent = progress.files_scanned.toLocaleString();
            document.getElementById('scan-files-added').textContent = progress.files_added.toLocaleString();
            document.getElementById('scan-files-updated').textContent = progress.files_updated.toLocaleString();
            document.getElementById('scan-files-removed').textContent = progress.files_removed.toLocaleString();
        } else {
            document.getElementById('current-scan-status').textContent = 'Idle';
            document.getElementById('scan-progress').style.display = 'none';
            document.getElementById('btn-start-scan').style.display = 'inline-block';
            document.getElementById('btn-cancel-scan').style.display = 'none';
        }
        
        // Update pause/resume buttons
        if (data.enabled) {
            document.getElementById('btn-pause-scanner').style.display = 'inline-block';
            document.getElementById('btn-resume-scanner').style.display = 'none';
        } else {
            document.getElementById('btn-pause-scanner').style.display = 'none';
            document.getElementById('btn-resume-scanner').style.display = 'inline-block';
        }
    }
    
    async startScan() {
        if (!this.scannerConfigured) {
            UIHelpers.showMessage('Library scanner not configured', 'error');
            return;
        }
        
        const btn = document.getElementById('btn-start-scan');
        btn.disabled = true;
        btn.textContent = 'Starting...';
        
        try {
            const response = await fetch('/web/api/library/scan/start', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to start scan');
            }
            
            const data = await response.json();
            UIHelpers.showMessage(`Library scan started (Scan #${data.scan_id})`, 'success');
            
            // Start polling for status
            this.startStatusPolling();
            
        } catch (error) {
            console.error('[Library] Start scan error:', error);
            UIHelpers.showMessage(`Failed to start scan: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Start Library Scan';
        }
    }
    
    async cancelScan() {
        if (!confirm('Cancel the current library scan?')) return;

        const btn = document.getElementById('btn-cancel-scan');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Canceling...';

        try {
            const response = await fetch('/web/api/library/scan/cancel', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to cancel scan');
            }

            UIHelpers.showMessage('Scan cancellation requested', 'success');

        } catch (error) {
            console.error('[Library] Cancel scan error:', error);
            UIHelpers.showMessage(`Failed to cancel scan: ${error.message}`, 'error');
        } finally {
            // UI will update via status polling, so we don't need to manually reset the button
            btn.textContent = originalText;
            btn.disabled = false;
        }
    }
    
    async pauseScanner() {
        try {
            const response = await fetch('/web/api/library/scan/pause', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to pause scanner');
            }
            
            UIHelpers.showMessage('Library scanner paused', 'success');
            this.loadStatus();
            
        } catch (error) {
            console.error('[Library] Pause error:', error);
            UIHelpers.showMessage(`Failed to pause scanner: ${error.message}`, 'error');
        }
    }
    
    async resumeScanner() {
        try {
            const response = await fetch('/web/api/library/scan/resume', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to resume scanner');
            }
            
            UIHelpers.showMessage('Library scanner resumed', 'success');
            this.loadStatus();
            
        } catch (error) {
            console.error('[Library] Resume error:', error);
            UIHelpers.showMessage(`Failed to resume scanner: ${error.message}`, 'error');
        }
    }
    
    async clearLibrary() {
        if (!confirm('Clear all library data? This will delete all file records and tags, requiring a fresh scan. The job queue and settings will not be affected.')) {
            return;
        }

        try {
            // Auto-cancel any running scan first
            if (this.currentScanId) {
                UIHelpers.showMessage('Canceling running scan...', 'info');
                const cancelResponse = await fetch('/web/api/library/scan/cancel', {
                    method: 'POST',
                    headers: this.app.authManager.getAuthHeaders()
                });

                if (!cancelResponse.ok) {
                    throw new Error('Failed to cancel running scan');
                }

                // Wait a moment for the scan to actually stop
                await new Promise(resolve => setTimeout(resolve, 1000));
            }

            // Now clear the library data
            const response = await fetch('/web/api/library/clear', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to clear library');
            }

            UIHelpers.showMessage('Library data cleared successfully', 'success');
            this.loadStatus();
            this.loadScanHistory();

        } catch (error) {
            console.error('[Library] Clear library error:', error);
            UIHelpers.showMessage(`Failed to clear library: ${error.message}`, 'error');
        }
    }
    
    async loadScanHistory() {
        try {
            const response = await fetch('/web/api/library/scan/history?limit=20', {
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to load scan history');
            }
            
            const data = await response.json();
            this.renderScanHistory(data.scans);
            
        } catch (error) {
            console.error('[Library] History error:', error);
            UIHelpers.showMessage('Failed to load scan history', 'error');
        }
    }
    
    renderScanHistory(scans) {
        const tbody = document.getElementById('scan-history-table');
        tbody.innerHTML = '';
        
        if (scans.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align: center;">No scans found</td></tr>';
            return;
        }
        
        scans.forEach(scan => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${scan.id}</td>
                <td>${UIHelpers.formatTimestamp(scan.started_at)}</td>
                <td>${UIHelpers.formatTimestamp(scan.finished_at)}</td>
                <td><span class="status-badge status-${scan.status}">${scan.status}</span></td>
                <td>${(scan.files_scanned || 0).toLocaleString()}</td>
                <td>${(scan.files_added || 0).toLocaleString()}</td>
                <td>${(scan.files_updated || 0).toLocaleString()}</td>
                <td>${(scan.files_removed || 0).toLocaleString()}</td>
            `;
            tbody.appendChild(row);
        });
    }
    
    startStatusPolling() {
        // Poll every 2 seconds while scanning
        if (this.statusPollInterval) {
            clearInterval(this.statusPollInterval);
        }
        
        this.statusPollInterval = setInterval(async () => {
            await this.loadStatus();
            
            // Stop polling if no scan is running
            if (!this.currentScanId) {
                this.stopStatusPolling();
                this.loadScanHistory(); // Refresh history when scan completes
            }
        }, 2000);
    }
    
    stopStatusPolling() {
        if (this.statusPollInterval) {
            clearInterval(this.statusPollInterval);
            this.statusPollInterval = null;
        }
    }
}
