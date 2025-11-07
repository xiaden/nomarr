// Navidrome Configuration Manager
import { UIHelpers } from './ui.js';

export class NavidromeManager {
    constructor(app) {
        this.app = app;
        this.currentConfig = null;
    }

    setupNavidromeUI() {
        console.log('[Navidrome] Setting up UI...');
        // No initial setup needed
    }

    async loadNavidromePreview() {
        console.log('[Navidrome] Loading tag preview...');
        const container = document.getElementById('navidrome-preview-container');
        
        try {
            container.innerHTML = '<p class="loading-text">Loading tag preview...</p>';
            
            const response = await fetch('/web/api/navidrome/preview', {
                method: 'GET',
                headers: this.app.authManager.getAuthHeaders()
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log('[Navidrome] Preview data:', data);
            
            this.renderPreview(data);
            UIHelpers.showSuccess('Tag preview loaded successfully');
        } catch (error) {
            console.error('[Navidrome] Failed to load preview:', error);
            container.innerHTML = `<p class="error-text">Failed to load preview: ${error.message}</p>`;
            UIHelpers.showError('Failed to load tag preview: ' + error.message);
        }
    }

    renderPreview(data) {
        const container = document.getElementById('navidrome-preview-container');
        
        if (!data.tags || data.tags.length === 0) {
            container.innerHTML = `
                <p class="info-text">No tags found in library.</p>
                <p class="info-text">Make sure you've scanned your library first (Library tab).</p>
            `;
            return;
        }

        const html = `
            <div class="info-banner">
                <strong>Namespace:</strong> ${data.namespace} | 
                <strong>Total Tags:</strong> ${data.tag_count}
            </div>
            <div class="table-container">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Tag Key</th>
                            <th>Type</th>
                            <th>Multi-Value</th>
                            <th>Count</th>
                            <th>Summary</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.tags.map(tag => `
                            <tr>
                                <td><code>${tag.tag_key || 'unknown'}</code></td>
                                <td><span class="badge badge-${tag.type || 'unknown'}">${tag.type || 'unknown'}</span></td>
                                <td>${tag.is_multivalue ? '✓' : '—'}</td>
                                <td>${(tag.total_count || 0).toLocaleString()}</td>
                                <td class="summary-values">${this.formatSummary(tag.summary, tag.type)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
        
        container.innerHTML = html;
    }

    formatSummary(summary, type) {
        if (!summary || summary === "No data") return '—';
        
        // For numeric types: show range and average
        if (type === 'float' || type === 'int') {
            if (typeof summary === 'object' && summary.min !== undefined) {
                const decimals = type === 'float' ? 3 : 0;
                return `Range: ${summary.min.toFixed(decimals)} - ${summary.max.toFixed(decimals)}, Avg: ${summary.avg.toFixed(decimals)}`;
            }
            return String(summary);
        }
        
        // For string/array types: show unique values with counts
        if (typeof summary === 'object') {
            const entries = Object.entries(summary);
            
            // Format as "value (count), value (count), ..."
            const formatted = entries.map(([value, count]) => {
                // Clean up byte string representations
                const cleanValue = String(value).replace(/^b['"]/, '').replace(/['"]$/, '');
                return `${cleanValue} (${count.toLocaleString()})`;
            }).join(', ');
            
            return formatted || '—';
        }
        
        return String(summary);
    }


    async generateNavidromeConfig() {
        console.log('[Navidrome] Generating config...');
        const container = document.getElementById('navidrome-config-container');
        const copyBtn = document.getElementById('copy-config-btn');
        
        try {
            container.innerHTML = '<p class="loading-text">Generating configuration...</p>';
            
            const response = await fetch('/web/api/navidrome/config', {
                method: 'GET',
                headers: this.app.authManager.getAuthHeaders()
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log('[Navidrome] Config data:', data);
            
            this.currentConfig = data.config;
            this.renderConfig(data);
            copyBtn.style.display = 'inline-block';
            
            UIHelpers.showSuccess('Configuration generated successfully');
        } catch (error) {
            console.error('[Navidrome] Failed to generate config:', error);
            container.innerHTML = `<p class="error-text">Failed to generate config: ${error.message}</p>`;
            copyBtn.style.display = 'none';
            UIHelpers.showError('Failed to generate config: ' + error.message);
        }
    }

    renderConfig(data) {
        const container = document.getElementById('navidrome-config-container');
        
        const html = `
            <div class="info-banner">
                <strong>Namespace:</strong> ${data.namespace}<br>
                <strong>Usage:</strong> Copy this configuration to your <code>navidrome.toml</code> file
            </div>
            <div class="config-output">
                <pre><code id="config-toml">${this.escapeHtml(data.config)}</code></pre>
            </div>
            <div class="info-text" style="margin-top: 1rem;">
                <strong>Next Steps:</strong>
                <ol>
                    <li>Copy the configuration above</li>
                    <li>Paste into your <code>navidrome.toml</code> file</li>
                    <li>Restart Navidrome</li>
                    <li>Tags will appear in Navidrome's web UI and API</li>
                </ol>
            </div>
        `;
        
        container.innerHTML = html;
    }

    async copyNavidromeConfig() {
        if (!this.currentConfig) {
            UIHelpers.showError('No config to copy. Generate config first.');
            return;
        }

        try {
            await navigator.clipboard.writeText(this.currentConfig);
            UIHelpers.showSuccess('Configuration copied to clipboard!');
            
            // Visual feedback
            const btn = document.getElementById('copy-config-btn');
            const originalText = btn.textContent;
            btn.textContent = 'Copied!';
            btn.classList.add('btn-success');
            
            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.remove('btn-success');
            }, 2000);
        } catch (error) {
            console.error('[Navidrome] Failed to copy:', error);
            UIHelpers.showError('Failed to copy to clipboard: ' + error.message);
        }
    }

    async previewPlaylist() {
        console.log('[Navidrome] Previewing playlist...');
        const container = document.getElementById('playlist-preview-container');
        const query = document.getElementById('playlist-query').value.trim();

        if (!query) {
            UIHelpers.showError('Please enter a playlist query');
            return;
        }

        try {
            container.innerHTML = '<p class="loading-text">Loading preview...</p>';

            const response = await fetch('/web/api/navidrome/playlists/preview', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.app.authManager.getAuthHeaders()
                },
                body: JSON.stringify({ query, preview_limit: 10 })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }

            const data = await response.json();
            console.log('[Navidrome] Preview data:', data);

            this.renderPlaylistPreview(data);
            UIHelpers.showSuccess(`Found ${data.total_count} matching tracks`);
        } catch (error) {
            console.error('[Navidrome] Failed to preview playlist:', error);
            container.innerHTML = `<p class="error-text">Failed to preview: ${error.message}</p>`;
            UIHelpers.showError('Failed to preview playlist: ' + error.message);
        }
    }

    renderPlaylistPreview(data) {
        const container = document.getElementById('playlist-preview-container');

        if (data.total_count === 0) {
            container.innerHTML = `
                <div class="info-banner">
                    <strong>No tracks found</strong> matching your query.<br>
                    Try adjusting your query or check that your library has been scanned.
                </div>
            `;
            return;
        }

        const html = `
            <div class="info-banner">
                <strong>Found ${data.total_count.toLocaleString()} tracks</strong> matching query<br>
                <code>${data.query}</code>
            </div>
            <div class="table-container">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Title</th>
                            <th>Artist</th>
                            <th>Album</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.sample_tracks.map(track => `
                            <tr>
                                <td>${this.escapeHtml(track.title)}</td>
                                <td>${this.escapeHtml(track.artist)}</td>
                                <td>${this.escapeHtml(track.album)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            ${data.total_count > 10 ? `<p class="info-text">Showing first 10 of ${data.total_count.toLocaleString()} tracks</p>` : ''}
        `;

        container.innerHTML = html;
    }

    async generatePlaylist() {
        console.log('[Navidrome] Generating playlist...');
        const query = document.getElementById('playlist-query').value.trim();
        const playlistName = document.getElementById('playlist-name').value.trim() || 'My Playlist';
        const limitInput = document.getElementById('playlist-limit').value;
        const limit = limitInput ? parseInt(limitInput, 10) : null;

        if (!query) {
            UIHelpers.showError('Please enter a playlist query');
            return;
        }

        try {
            UIHelpers.showInfo('Generating playlist...');

            const response = await fetch('/web/api/navidrome/playlists/generate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.app.authManager.getAuthHeaders()
                },
                body: JSON.stringify({
                    query,
                    playlist_name: playlistName,
                    comment: `Generated from: ${query}`,
                    limit,
                    sort: null
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || `HTTP ${response.status}`);
            }

            const data = await response.json();
            console.log('[Navidrome] Playlist generated:', data);

            this.currentPlaylistContent = data.content;
            this.currentPlaylistName = data.playlist_name;

            // Show download button
            const downloadBtn = document.getElementById('download-playlist-btn');
            downloadBtn.style.display = 'inline-block';
            downloadBtn.textContent = 'Download .nsp';

            UIHelpers.showSuccess('Playlist generated! Click "Download .nsp" to save for Navidrome.');
        } catch (error) {
            console.error('[Navidrome] Failed to generate playlist:', error);
            UIHelpers.showError('Failed to generate playlist: ' + error.message);
        }
    }

    downloadPlaylist() {
        if (!this.currentPlaylistContent) {
            UIHelpers.showError('No playlist to download. Generate one first.');
            return;
        }

        try {
            // Create blob and download
            const blob = new Blob([this.currentPlaylistContent], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${this.currentPlaylistName}.nsp`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

            UIHelpers.showSuccess('Playlist downloaded!');
        } catch (error) {
            console.error('[Navidrome] Failed to download:', error);
            UIHelpers.showError('Failed to download playlist: ' + error.message);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async loadTemplateList() {
        console.log('[Navidrome] Loading template list...');
        const container = document.getElementById('templates-container');
        
        try {
            container.innerHTML = '<p class="loading-text">Loading templates...</p>';
            
            const response = await fetch('/web/api/navidrome/templates/list', {
                method: 'GET',
                headers: this.app.authManager.getAuthHeaders()
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log('[Navidrome] Template list:', data);
            
            this.renderTemplateList(data.templates);
            
            // Show action buttons
            document.getElementById('generate-templates-btn').style.display = 'inline-block';
            document.getElementById('download-templates-btn').style.display = 'inline-block';
            
            UIHelpers.showSuccess('Templates loaded successfully');
        } catch (error) {
            console.error('[Navidrome] Failed to load templates:', error);
            container.innerHTML = `<p class="error-text">Failed to load templates: ${error.message}</p>`;
            UIHelpers.showError('Failed to load templates: ' + error.message);
        }
    }

    renderTemplateList(templates) {
        const container = document.getElementById('templates-container');
        
        if (!templates || templates.length === 0) {
            container.innerHTML = '<p class="info-text">No templates available.</p>';
            return;
        }

        const html = `
            <div class="table-container">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Filename</th>
                            <th>Playlist Name</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${templates.map(t => `
                            <tr>
                                <td><code>${this.escapeHtml(t.filename)}</code></td>
                                <td>${this.escapeHtml(t.name)}</td>
                                <td>${this.escapeHtml(t.comment)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            <p class="info-text" style="margin-top: 1rem;">
                <strong>${templates.length}</strong> templates available. 
                Click "Generate All Templates" to create them, then "Download as ZIP" to save.
            </p>
        `;
        
        container.innerHTML = html;
    }

    async generateAllTemplates() {
        console.log('[Navidrome] Generating all templates...');
        
        try {
            UIHelpers.showSuccess('Generating templates...');
            
            const response = await fetch('/web/api/navidrome/templates/generate', {
                method: 'POST',
                headers: this.app.authManager.getAuthHeaders()
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log('[Navidrome] Generated templates:', data);
            
            // Store templates for download
            this.currentTemplates = data.templates;
            
            UIHelpers.showSuccess(`Generated ${data.total_count} templates! Click "Download as ZIP" to save them.`);
        } catch (error) {
            console.error('[Navidrome] Failed to generate templates:', error);
            UIHelpers.showError('Failed to generate templates: ' + error.message);
        }
    }

    async downloadAllTemplates() {
        if (!this.currentTemplates) {
            UIHelpers.showError('No templates to download. Generate them first.');
            return;
        }

        try {
            // For now, just download individual files (ZIP would require JSZip library)
            let count = 0;
            for (const [filename, content] of Object.entries(this.currentTemplates)) {
                const blob = new Blob([content], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                count++;
                
                // Small delay between downloads to avoid browser blocking
                await new Promise(resolve => setTimeout(resolve, 200));
            }

            UIHelpers.showSuccess(`Downloaded ${count} template files!`);
        } catch (error) {
            console.error('[Navidrome] Failed to download templates:', error);
            UIHelpers.showError('Failed to download templates: ' + error.message);
        }
    }
}

