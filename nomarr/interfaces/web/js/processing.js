// File Processing Module
import { UIHelpers } from './ui.js';

export class ProcessingManager {
    constructor(app) {
        this.app = app;
    }
    
    setupProcessingUI() {
        // Single file processing
        document.getElementById('btn-process-file').onclick = () => this.processFile();
        
        // Batch processing
        document.getElementById('btn-batch-process').onclick = () => this.batchProcess();
    }
    
    async processFile() {
        const path = document.getElementById('file-path').value.trim();
        const force = document.getElementById('force-reprocess').checked;
        
        if (!path) {
            UIHelpers.showMessage('Please enter a file path', 'error');
            return;
        }
        
        const btn = document.getElementById('btn-process-file');
        btn.disabled = true;
        btn.textContent = 'Processing...';
        
        const progressDiv = document.getElementById('progress');
        progressDiv.innerHTML = '<div class="progress-item">Starting...</div>';
        
        try {
            await this.streamProgress(path, force, progressDiv);
            UIHelpers.showMessage('File processed successfully', 'success');
        } catch (error) {
            console.error('[Processing] Error:', error);
            UIHelpers.showMessage(`Processing failed: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Process File';
        }
    }
    
    async batchProcess() {
        const paths = document.getElementById('batch-paths').value
            .split('\n')
            .map(p => p.trim())
            .filter(p => p.length > 0);
        
        const force = document.getElementById('batch-force-reprocess').checked;
        
        if (paths.length === 0) {
            UIHelpers.showMessage('Please enter at least one file path', 'error');
            return;
        }
        
        const btn = document.getElementById('btn-batch-process');
        btn.disabled = true;
        btn.textContent = 'Processing...';
        
        const resultsDiv = document.getElementById('batch-results');
        resultsDiv.innerHTML = '<div class="progress-item">Starting batch processing...</div>';
        
        try {
            const response = await fetch('/web/api/batch-process', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders(),
                body: JSON.stringify({ paths, force })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Batch processing failed');
            }
            
            const data = await response.json();
            
            // Display results
            resultsDiv.innerHTML = `
                <div class="batch-summary">
                    <p><strong>Queued:</strong> ${data.queued}</p>
                    <p><strong>Skipped:</strong> ${data.skipped}</p>
                    <p><strong>Errors:</strong> ${data.errors}</p>
                </div>
            `;
            
            if (data.results && data.results.length > 0) {
                const resultsList = document.createElement('div');
                resultsList.className = 'batch-results-list';
                
                data.results.forEach(result => {
                    const item = document.createElement('div');
                    item.className = `result-item ${result.status}`;
                    item.innerHTML = `
                        <strong>${UIHelpers.escapeHtml(result.path)}</strong>
                        <span class="status">${result.status}</span>
                        ${result.message ? `<p>${UIHelpers.escapeHtml(result.message)}</p>` : ''}
                    `;
                    resultsList.appendChild(item);
                });
                
                resultsDiv.appendChild(resultsList);
            }
            
            UIHelpers.showMessage(`Batch processing complete: ${data.queued} queued, ${data.errors} errors`, 'success');
            
            // Refresh queue
            this.app.queueManager.loadQueueList();
            
        } catch (error) {
            console.error('[Processing] Batch error:', error);
            UIHelpers.showMessage(`Batch processing failed: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Process Batch';
        }
    }
    
    async streamProgress(path, force, progressDiv) {
        const response = await fetch('/web/api/process', {
            method: 'POST',
            headers: this.app.authManager.getAuthHeaders(),
            body: JSON.stringify({ path, force })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Processing failed');
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { done, value } = await reader.read();
            
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            
            for (const line of lines) {
                if (!line.trim() || !line.startsWith('data: ')) continue;
                
                try {
                    const data = JSON.parse(line.substring(6));
                    
                    if (data.event === 'progress') {
                        const item = document.createElement('div');
                        item.className = 'progress-item';
                        item.textContent = data.message;
                        progressDiv.appendChild(item);
                        
                    } else if (data.event === 'complete') {
                        const item = document.createElement('div');
                        item.className = 'progress-item success';
                        item.innerHTML = `<strong>✓ Complete</strong> - Tags written successfully`;
                        progressDiv.appendChild(item);
                        
                        if (data.tags) {
                            const tagsDiv = document.createElement('div');
                            tagsDiv.className = 'tags-display';
                            tagsDiv.innerHTML = '<strong>Tags:</strong><ul>' +
                                Object.entries(data.tags)
                                    .map(([key, value]) => `<li><code>${UIHelpers.escapeHtml(key)}</code>: ${UIHelpers.escapeHtml(String(value))}</li>`)
                                    .join('') +
                                '</ul>';
                            progressDiv.appendChild(tagsDiv);
                        }
                        
                    } else if (data.event === 'error') {
                        const item = document.createElement('div');
                        item.className = 'progress-item error';
                        item.innerHTML = `<strong>✗ Error:</strong> ${UIHelpers.escapeHtml(data.message)}`;
                        progressDiv.appendChild(item);
                        throw new Error(data.message);
                    }
                    
                } catch (error) {
                    if (error.message !== 'Processing failed') {
                        console.error('[Processing] Stream parse error:', error);
                    } else {
                        throw error;
                    }
                }
            }
        }
    }
}
