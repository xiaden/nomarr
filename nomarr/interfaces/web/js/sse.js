// Server-Sent Events (SSE) Manager

export class SSEManager {
    constructor(app) {
        this.app = app;
        this.connection = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
    }
    
    connect() {
        if (this.connection) {
            console.log('[SSE] Already connected');
            return;
        }
        
        console.log('[SSE] Connecting to status stream...');
        const token = this.app.authManager.sessionToken;
        this.connection = new EventSource(`/web/events/status?token=${encodeURIComponent(token)}`);
        
        this.connection.onopen = () => {
            console.log('[SSE] Connected to status stream');
            this.isConnected = true;
            this.reconnectAttempts = 0;
            document.getElementById('connection-status').textContent = 'Connected';
            document.getElementById('connection-status').className = 'status-badge success';
        };
        
        this.connection.onerror = (error) => {
            console.error('[SSE] Connection error:', error);
            this.isConnected = false;
            document.getElementById('connection-status').textContent = 'Disconnected';
            document.getElementById('connection-status').className = 'status-badge error';
            
            this.connection.close();
            this.connection = null;
            
            // Try to reconnect
            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
                console.log(`[SSE] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
                setTimeout(() => this.connect(), delay);
            }
        };
        
        this.connection.addEventListener('queue_update', (event) => {
            const data = JSON.parse(event.data);
            console.log('[SSE] Queue update:', data);
            this.app.queueManager.updateQueueState(data);
            // Also update dashboard if it's the active tab
            const activeTab = document.querySelector('.tab-content.active');
            if (activeTab && activeTab.id === 'tab-dashboard') {
                this.app.updateDashboard();
            }
        });
        
        this.connection.addEventListener('processing_update', (event) => {
            const data = JSON.parse(event.data);
            console.log('[SSE] Processing update:', data);
            this.app.queueManager.handleProcessingUpdate(data);
        });
    }
    
    disconnect() {
        if (this.connection) {
            console.log('[SSE] Disconnecting...');
            this.connection.close();
            this.connection = null;
            this.isConnected = false;
        }
    }
}
