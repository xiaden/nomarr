/**
 * graph-normalize.js - Fix missing IDs, duplicates, legacy formats
 * Guarantees unique node/edge IDs
 */

import { checkEdgeIdCollisions } from '../utils/guards.js';
import { generateEdgeId, isValidEdgeId, isValidNodeId } from '../utils/id-utils.js';

/**
 * Normalize raw graph data
 * Returns GraphModel: { nodes, edges, entrypointIds }
 */
export function normalizeGraph(rawData) {
    const entrypointIds = [];
    
    // Normalize nodes
    const nodes = rawData.nodes.map(node => {
        if (!isValidNodeId(node.id)) {
            console.warn(`Invalid node ID:`, node);
            node.id = `node_${Math.random().toString(36).substr(2, 9)}`;
        }
        
        const isEntrypoint = detectEntrypoint(node);
        if (isEntrypoint) entrypointIds.push(node.id);
        
        return {
            id: node.id,
            data: {
                label: node.name || node.id,
                layer: node.layer || 'other',
                kind: node.kind || 'unknown',
                file: node.file || 'unknown',
                is_entrypoint: isEntrypoint
            }
        };
    });
    
    // Normalize edges
    const edges = rawData.edges.map((edge, index) => {
        const source = edge.source || edge.from || edge.source_id;
        const target = edge.target || edge.to || edge.target_id;
        const type = edge.type || 'calls';
        
        let id = edge.id;
        if (!isValidEdgeId(id)) {
            id = generateEdgeId(source, target, type, index);
        }
        
        return {
            id,
            source,
            target,
            data: { type }
        };
    });
    
    // Check for collisions
    checkEdgeIdCollisions(edges);
    
    return { nodes, edges, entrypointIds };
}

/**
 * Detect entrypoint nodes
 */
function detectEntrypoint(node) {
    // CLI: main in interfaces/cli/cli_main.py
    if (node.name === 'main' && node.file.includes('interfaces/cli/cli_main.py')) {
        return true;
    }
    
    // Worker: run in workers/base.py
    if (node.name === 'run' && node.file.includes('workers/base.py')) {
        return true;
    }
    
    // API: api_app in interfaces/api/api_app.py
    if (node.name === 'api_app' && node.file.includes('interfaces/api/api_app.py')) {
        return true;
    }
    
    return false;
}
