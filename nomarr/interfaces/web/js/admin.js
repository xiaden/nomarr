// Admin/Worker Control Module
import { UIHelpers } from './ui.js';

export class AdminManager {
    constructor(app) {
        this.app = app;
        this.workerEnabled = true;
    }
    
    setupAdminUI() {
        document.getElementById('btn-pause-worker').onclick = () => this.pauseWorker();
        document.getElementById('btn-resume-worker').onclick = () => this.resumeWorker();
        document.getElementById('btn-refresh-cache').onclick = () => this.refreshCache();
    }
    
    async pauseWorker() {
        try {
            const response = await fetch('/web/api/admin/worker/pause', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to pause worker');
            }
            
            this.workerEnabled = false;
            this.updateWorkerStatus();
            UIHelpers.showMessage('Worker paused', 'success');
            
        } catch (error) {
            console.error('[Admin] Pause error:', error);
            UIHelpers.showMessage(`Failed to pause worker: ${error.message}`, 'error');
        }
    }
    
    async resumeWorker() {
        try {
            const response = await fetch('/web/api/admin/worker/resume', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to resume worker');
            }
            
            this.workerEnabled = true;
            this.updateWorkerStatus();
            UIHelpers.showMessage('Worker resumed', 'success');
            
        } catch (error) {
            console.error('[Admin] Resume error:', error);
            UIHelpers.showMessage(`Failed to resume worker: ${error.message}`, 'error');
        }
    }
    
    async refreshCache() {
        const btn = document.getElementById('btn-refresh-cache');
        btn.disabled = true;
        btn.textContent = 'Refreshing...';
        
        try {
            const response = await fetch('/web/api/admin/cache-refresh', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to refresh cache');
            }
            
            const data = await response.json();
            UIHelpers.showMessage(data.message || 'Cache refreshed', 'success');
            
        } catch (error) {
            console.error('[Admin] Cache refresh error:', error);
            UIHelpers.showMessage(`Failed to refresh cache: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Refresh Model Cache';
        }
    }
    
    async cleanupOldJobs() {
        if (!confirm('Remove completed and error jobs older than 7 days?')) {
            return;
        }
        
        try {
            const response = await fetch('/web/api/admin/cleanup', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to cleanup old jobs');
            }
            
            const data = await response.json();
            UIHelpers.showMessage(`Removed ${data.removed} old job(s)`, 'success');
            this.app.queueManager.loadQueueList();
            
        } catch (error) {
            console.error('[Admin] Cleanup error:', error);
            UIHelpers.showMessage(`Failed to cleanup jobs: ${error.message}`, 'error');
        }
    }
    
    async resetJobs(type) {
        const typeLabel = type === 'stuck' ? 'stuck (running)' : 'error';
        if (!confirm(`Reset all ${typeLabel} jobs to pending?`)) {
            return;
        }
        
        try {
            const response = await fetch('/web/api/admin/reset', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders(),
                body: JSON.stringify({
                    stuck: type === 'stuck',
                    errors: type === 'errors'
                })
            });
            
            if (!response.ok) {
                throw new Error('Failed to reset jobs');
            }
            
            const data = await response.json();
            UIHelpers.showMessage(`Reset ${data.reset} job(s) to pending`, 'success');
            this.app.queueManager.loadQueueList();
            
        } catch (error) {
            console.error('[Admin] Reset error:', error);
            UIHelpers.showMessage(`Failed to reset jobs: ${error.message}`, 'error');
        }
    }
    
    async restartServer() {
        if (!confirm('Restart the API server? This will apply config changes. The page will reconnect automatically.')) {
            return;
        }
        
        try {
            const response = await fetch('/web/api/admin/restart', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to restart server');
            }
            
            UIHelpers.showSuccess('Server is restarting... Page will reload automatically.');
            
            // Wait a bit, then reload the page
            setTimeout(() => {
                window.location.reload();
            }, 3000);
            
        } catch (error) {
            console.error('[Admin] Restart error:', error);
            UIHelpers.showError('Failed to restart server: ' + error.message);
        }
    }
    
    updateWorkerStatus() {
        const statusBadge = document.getElementById('worker-status');
        const pauseBtn = document.getElementById('btn-pause-worker');
        const resumeBtn = document.getElementById('btn-resume-worker');
        
        if (this.workerEnabled) {
            statusBadge.textContent = 'Running';
            statusBadge.className = 'status-badge success';
            pauseBtn.style.display = 'inline-block';
            resumeBtn.style.display = 'none';
        } else {
            statusBadge.textContent = 'Paused';
            statusBadge.className = 'status-badge warning';
            pauseBtn.style.display = 'none';
            resumeBtn.style.display = 'inline-block';
        }
    }
}
