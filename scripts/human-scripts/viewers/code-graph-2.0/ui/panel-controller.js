/**
 * panel-controller.js - Left panel for node details and connections
 * Emits: jumpToNode
 */

/**
 * Initialize panel with jump callback
 */
export function initPanel({ onJumpToNode }) {
    const panel = document.getElementById('panel-content');
    
    if (!panel) {
        console.error('Panel element not found');
        return null;
    }
    
    const controller = {
        showNode(node, connections) {
            if (!node) {
                panel.innerHTML = '<p>No node selected</p>';
                return;
            }
            
            const { data } = node;
            const { incoming, outgoing } = connections;
            
            let html = `
                <div>
                    <h3>${data.label || node.id}</h3>
                    <div class="info-row">
                        <span class="info-label">Kind</span>
                        <span class="info-value">${data.kind || 'unknown'}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Layer</span>
                        <span class="info-value">${data.layer || 'unknown'}</span>
                    </div>
                    ${data.file ? `<div class="info-row">
                        <span class="info-label">File</span>
                        <span class="info-value">${data.file}</span>
                    </div>` : ''}
                    ${data.is_entrypoint ? `<div class="info-row">
                        <span class="info-label">Entrypoint</span>
                        <span class="info-value">Yes</span>
                    </div>` : ''}
                </div>
            `;
            
            if (incoming.length > 0) {
                html += `<div><h4>Incoming (${incoming.length})</h4><ul class="connection-list">`;
                incoming.forEach(n => {
                    html += `<li class="connection-item" data-node-id="${n.id}">${n.data.label || n.id}</li>`;
                });
                html += '</ul></div>';
            }
            
            if (outgoing.length > 0) {
                html += `<div><h4>Outgoing (${outgoing.length})</h4><ul class="connection-list">`;
                outgoing.forEach(n => {
                    html += `<li class="connection-item" data-node-id="${n.id}">${n.data.label || n.id}</li>`;
                });
                html += '</ul></div>';
            }
            
            panel.innerHTML = html;
            
            // Wire up connection clicks
            panel.querySelectorAll('.connection-item').forEach(item => {
                item.addEventListener('click', () => {
                    const targetId = item.getAttribute('data-node-id');
                    if (onJumpToNode) onJumpToNode(targetId);
                });
            });
        }
    };
    
    console.log('✓ Panel controller initialized');
    return controller;
}
