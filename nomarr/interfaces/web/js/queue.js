// Queue Management Module
import { UIHelpers } from './ui.js';

export class QueueManager {
    constructor(app) {
        this.app = app;
        this.queueState = { pending: 0, running: 0, completed: 0, jobs: [] };
        this.currentPage = 1;
        this.pageSize = 50;
        this.currentFilter = 'all';
    }
    
    setupQueueUI() {
        // Queue controls
        document.getElementById('btn-refresh-queue').onclick = () => this.loadQueueList();
        document.getElementById('btn-clear-completed').onclick = () => this.clearQueue('completed');
        document.getElementById('btn-clear-errors').onclick = () => this.clearQueue('errors');
        document.getElementById('btn-clear-all').onclick = () => this.clearQueue('all');
        
        // Queue filters
        document.querySelectorAll('.queue-filters button').forEach(btn => {
            btn.addEventListener('click', () => {
                this.currentFilter = btn.dataset.filter;
                this.currentPage = 1;
                this.loadQueueList();
                
                // Update active button
                document.querySelectorAll('.queue-filters button').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });
    }
    
    updateQueueState(data) {
        this.queueState = data;
        
        // Update summary badges
        document.getElementById('queue-pending').textContent = data.pending || 0;
        document.getElementById('queue-running').textContent = data.running || 0;
        document.getElementById('queue-completed').textContent = data.completed || 0;
        document.getElementById('queue-errors').textContent = data.errors || 0;
        
        // Refresh list if on queue tab
        const activeTab = document.querySelector('.tab-content.active');
        if (activeTab && activeTab.id === 'tab-queue') {
            this.loadQueueList();
        }
    }
    
    handleProcessingUpdate(data) {
        // Update specific job in the list
        const jobRow = document.querySelector(`tr[data-job-id="${data.job_id}"]`);
        if (jobRow) {
            const statusCell = jobRow.querySelector('.job-status');
            if (statusCell) {
                statusCell.textContent = data.status;
                statusCell.className = `job-status status-${data.status}`;
            }
            
            if (data.message) {
                const messageCell = jobRow.querySelector('.job-message');
                if (messageCell) {
                    messageCell.textContent = data.message;
                }
            }
        }
    }
    
    async loadQueueList() {
        try {
            const statusParam = this.currentFilter === 'all' ? '' : `&status=${this.currentFilter}`;
            const response = await fetch(
                `/web/api/list?limit=${this.pageSize}&offset=${(this.currentPage - 1) * this.pageSize}${statusParam}`,
                { headers: this.app.authManager.getAuthHeaders() }
            );
            
            if (!response.ok) {
                throw new Error('Failed to load queue');
            }
            
            const data = await response.json();
            this.renderQueueTable(data.jobs, data.total);
            
        } catch (error) {
            console.error('[Queue] Load error:', error);
            UIHelpers.showMessage('Failed to load queue', 'error');
        }
    }
    
    renderQueueTable(jobs, total) {
        const tbody = document.querySelector('#queue-table tbody');
        tbody.innerHTML = '';
        
        if (jobs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">No jobs found</td></tr>';
            return;
        }
        
        jobs.forEach(job => {
            const row = document.createElement('tr');
            row.dataset.jobId = job.id;
            row.innerHTML = `
                <td>${job.id}</td>
                <td title="${UIHelpers.escapeHtml(job.path)}">${UIHelpers.escapeHtml(this.truncatePath(job.path))}</td>
                <td><span class="job-status status-${job.status}">${job.status}</span></td>
                <td>${UIHelpers.formatTimestamp(job.created_at)}</td>
                <td class="job-message">${job.error_message || '-'}</td>
                <td>
                    ${job.status === 'pending' || job.status === 'error' 
        ? `<button class="btn-small btn-danger" onclick="app.queueManager.removeJob(${job.id})">Remove</button>`
        : '-'}
                </td>
            `;
            tbody.appendChild(row);
        });
        
        // Update pagination info
        const totalPages = Math.ceil(total / this.pageSize);
        document.getElementById('queue-pagination-info').textContent = 
            `Page ${this.currentPage} of ${totalPages} (${total} total jobs)`;
        
        // Setup pagination controls
        this.setupPagination(totalPages);
    }
    
    setupPagination(totalPages) {
        const paginationDiv = document.getElementById('queue-pagination');
        paginationDiv.innerHTML = '';
        
        if (totalPages <= 1) return;
        
        // Previous button
        const prevBtn = document.createElement('button');
        prevBtn.textContent = '← Previous';
        prevBtn.disabled = this.currentPage === 1;
        prevBtn.onclick = () => {
            this.currentPage--;
            this.loadQueueList();
        };
        paginationDiv.appendChild(prevBtn);
        
        // Page numbers (show max 5 pages)
        const startPage = Math.max(1, this.currentPage - 2);
        const endPage = Math.min(totalPages, startPage + 4);
        
        for (let i = startPage; i <= endPage; i++) {
            const pageBtn = document.createElement('button');
            pageBtn.textContent = i;
            pageBtn.className = i === this.currentPage ? 'active' : '';
            pageBtn.onclick = () => {
                this.currentPage = i;
                this.loadQueueList();
            };
            paginationDiv.appendChild(pageBtn);
        }
        
        // Next button
        const nextBtn = document.createElement('button');
        nextBtn.textContent = 'Next →';
        nextBtn.disabled = this.currentPage === totalPages;
        nextBtn.onclick = () => {
            this.currentPage++;
            this.loadQueueList();
        };
        paginationDiv.appendChild(nextBtn);
    }
    
    truncatePath(path, maxLength = 60) {
        if (path.length <= maxLength) return path;
        const start = path.substring(0, maxLength / 2);
        const end = path.substring(path.length - maxLength / 2);
        return `${start}...${end}`;
    }
    
    async removeJob(jobId) {
        if (!confirm('Remove this job from the queue?')) return;
        
        try {
            const response = await fetch('/web/api/queue/remove', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders(),
                body: JSON.stringify({ job_id: jobId })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to remove job');
            }
            
            UIHelpers.showMessage('Job removed', 'success');
            this.loadQueueList();
            
        } catch (error) {
            console.error('[Queue] Remove error:', error);
            UIHelpers.showMessage(`Failed to remove job: ${error.message}`, 'error');
        }
    }
    
    async clearQueue(filter) {
        const confirmMsg = filter === 'all' 
            ? 'Clear ALL jobs from the queue?'
            : `Clear all ${filter} jobs from the queue?`;
        
        if (!confirm(confirmMsg)) return;
        
        try {
            const endpoint = filter === 'all' 
                ? '/web/api/admin/queue/clear-all'
                : `/web/api/admin/queue/clear-${filter}`;
            
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to clear queue');
            }
            
            const data = await response.json();
            UIHelpers.showMessage(`Cleared ${data.removed} jobs`, 'success');
            this.loadQueueList();
            
        } catch (error) {
            console.error('[Queue] Clear error:', error);
            UIHelpers.showMessage(`Failed to clear queue: ${error.message}`, 'error');
        }
    }
}
