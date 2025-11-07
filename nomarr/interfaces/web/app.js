// Nomarr Web UI - Main Application Entry Point
import { AuthManager } from './js/auth.js';
import { SSEManager } from './js/sse.js';
import { ProcessingManager } from './js/processing.js';
import { QueueManager } from './js/queue.js';
import { AdminManager } from './js/admin.js';
import { LibraryManager } from './js/library.js';
import { AnalyticsManager } from './js/analytics.js';
import { NavidromeManager } from './js/navidrome.js';
import { ConfigManager } from './js/config.js';

class NomarrApp {
    constructor() {
        this.authManager = new AuthManager(this);
        this.sseManager = new SSEManager(this);
        this.processingManager = new ProcessingManager(this);
        this.queueManager = new QueueManager(this);
        this.adminManager = new AdminManager(this);
        this.libraryManager = new LibraryManager(this);
        this.analyticsManager = new AnalyticsManager(this);
        this.navidromeManager = new NavidromeManager(this);
        this.configManager = new ConfigManager(this);
        
        // Setup global fetch interceptor for auth errors
        this.setupFetchInterceptor();
        
        this.init();
    }
    
    setupFetchInterceptor() {
        // Store original fetch
        const originalFetch = window.fetch;
        const authManager = this.authManager;
        
        // Override fetch to intercept 401/403 responses
        window.fetch = async function(...args) {
            const response = await originalFetch(...args);
            
            // Check for auth errors on web API endpoints
            if ((response.status === 401 || response.status === 403) && 
                args[0].includes('/web/api/')) {
                console.warn('[App] Auth error detected, forcing logout');
                authManager.handleSessionExpired();
            }
            
            return response;
        };
    }
    
    init() {
        console.log('[App] Initializing...');
        
        // Check authentication
        if (this.authManager.init()) {
            this.showMainUI();
        } else {
            this.authManager.showLoginUI();
        }
    }
    
    // Called by AuthManager after successful login
    onLoginSuccess() {
        this.showMainUI();
    }
    
    showMainUI() {
        this.authManager.showMainUI();
        this.setupUI();
        this.sseManager.connect();
        this.queueManager.loadQueueList();
        this.updateDashboard();
    }
    
    setupUI() {
        // Setup tab switching
        document.querySelectorAll('.nav-tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
        });
        
        // Setup logout button
        document.getElementById('btn-logout').onclick = () => this.authManager.handleLogout();
        
        // Auto-reconnect on visibility change
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && !this.sseManager.isConnected && this.authManager.isAuthenticated) {
                this.sseManager.connect();
            }
        });
        
        // Setup all module UIs
        this.processingManager.setupProcessingUI();
        this.queueManager.setupQueueUI();
        this.adminManager.setupAdminUI();
        this.libraryManager.setupLibraryUI();
        this.analyticsManager.setupAnalyticsUI();
        this.navidromeManager.setupNavidromeUI();
        
        // Update worker status
        this.adminManager.updateWorkerStatus();
    }
    
    async updateDashboard() {
        try {
            const response = await fetch('/web/api/queue-depth', {
                headers: this.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                throw new Error('Failed to load dashboard stats');
            }
            
            const data = await response.json();
            
            // Update stat cards
            document.getElementById('stat-pending').textContent = data.pending || 0;
            document.getElementById('stat-running').textContent = data.running || 0;
            document.getElementById('stat-completed').textContent = data.completed || 0;
            
            // Update active jobs list (show running jobs only)
            const jobListDiv = document.getElementById('job-list');
            
            if (data.running === 0) {
                jobListDiv.innerHTML = '<div class="empty-state">No active jobs</div>';
            } else {
                // Fetch current running jobs
                const jobsResponse = await fetch('/web/api/list?limit=10&status=running', {
                    headers: this.authManager.getAuthHeaders()
                });
                
                if (jobsResponse.ok) {
                    const jobsData = await jobsResponse.json();
                    
                    if (jobsData.jobs && jobsData.jobs.length > 0) {
                        jobListDiv.innerHTML = jobsData.jobs.map(job => `
                            <div class="job-card">
                                <div class="job-info">
                                    <span class="job-id">#${job.id}</span>
                                    <span class="job-path" title="${job.path}">${this.truncatePath(job.path, 60)}</span>
                                </div>
                                <div class="job-status status-${job.status}">${job.status}</div>
                            </div>
                        `).join('');
                    } else {
                        jobListDiv.innerHTML = '<div class="empty-state">No active jobs</div>';
                    }
                }
            }
            
        } catch (error) {
            console.error('[App] Dashboard update error:', error);
        }
    }
    
    truncatePath(path, maxLength = 50) {
        if (path.length <= maxLength) return path;
        const filename = path.split('/').pop();
        const remaining = maxLength - filename.length - 3;
        if (remaining <= 0) return '...' + filename.slice(-(maxLength - 3));
        return path.slice(0, remaining) + '...' + filename;
    }
    
    switchTab(tabName) {
        document.querySelectorAll('.nav-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === tabName);
        });
        
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.toggle('active', content.id === `tab-${tabName}`);
        });
        
        // Load data for specific tabs
        if (tabName === 'dashboard') {
            this.updateDashboard();
        } else if (tabName === 'queue') {
            this.queueManager.loadQueueList();
        } else if (tabName === 'library') {
            this.libraryManager.loadStatus();
            this.libraryManager.loadScanHistory();
        } else if (tabName === 'analytics') {
            this.analyticsManager.loadLibraryOverview();
            this.analyticsManager.loadTagFrequencies();
            this.analyticsManager.loadMoodDistribution();
        } else if (tabName === 'config') {
            this.configManager.loadConfig();
        }
    }

    // Inspect Tags (called from inline onclick handler)
    async inspectTags() {
        const path = document.getElementById('inspect-path').value.trim();
        const resultDiv = document.getElementById('inspect-result');
        
        if (!path) {
            resultDiv.textContent = 'Please enter a file path';
            return;
        }
        
        try {
            const response = await fetch(`/web/api/show-tags?path=${encodeURIComponent(path)}`, {
                headers: this.authManager.getAuthHeaders()
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to load tags');
            }
            
            const data = await response.json();
            resultDiv.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
            
        } catch (error) {
            resultDiv.innerHTML = `<pre style="color: var(--danger);">Error: ${error.message}</pre>`;
        }
    }

    // Navidrome convenience methods (called from inline onclick handlers)
    loadNavidromePreview() {
        this.navidromeManager.loadNavidromePreview();
    }

    generateNavidromeConfig() {
        this.navidromeManager.generateNavidromeConfig();
    }

    copyNavidromeConfig() {
        this.navidromeManager.copyNavidromeConfig();
    }

    previewPlaylist() {
        this.navidromeManager.previewPlaylist();
    }

    generatePlaylist() {
        this.navidromeManager.generatePlaylist();
    }

    downloadPlaylist() {
        this.navidromeManager.downloadPlaylist();
    }

    loadTemplateList() {
        this.navidromeManager.loadTemplateList();
    }

    generateAllTemplates() {
        this.navidromeManager.generateAllTemplates();
    }

    downloadAllTemplates() {
        this.navidromeManager.downloadAllTemplates();
    }

    // Analytics convenience methods
    loadLibraryOverview() {
        this.analyticsManager.loadLibraryOverview();
    }

    loadTagFrequencies() {
        this.analyticsManager.loadTagFrequencies();
    }

    loadMoodDistribution() {
        this.analyticsManager.loadMoodDistribution();
    }

    loadCorrelationMatrix() {
        this.analyticsManager.loadCorrelationMatrix();
    }

    loadTagCoOccurrences() {
        this.analyticsManager.loadTagCoOccurrences();
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new NomarrApp();
});

