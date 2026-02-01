# Progressive Disclosure Implementation

## Overview

The code graph viewer now implements progressive disclosure - starting with only the 3 application entrypoints visible, then allowing users to explore the graph by expanding nodes on demand.

## Features Implemented

### 1. Entrypoint Detection

**File: `graph-loader.js`**

Added `findApplicationEntrypoints()` method that identifies exactly 3 nodes:

1. **CLI main**: `name === 'main'` in `interfaces/cli` files
2. **Worker start**: `name === 'start'` in `worker` files  
3. **API app**: `name === 'app' || 'main'` in `interfaces/api` or `start.py`

Returns a `Set<string>` of matching node IDs.

### 2. Expansion Manager

**File: `graph-expansion.js`** (NEW)

Created `ExpansionManager` class to manage visible graph subset:

**Methods:**
- `initializeEntrypoints()` - Returns only the 3 entrypoint nodes/edges
- `expandNode(nodeId)` - Adds all neighbors, returns only new nodes/edges
- `collapseNode(nodeId)` - Removes node + orphaned neighbors (with entrypoint protection)
- `tracePaths(nodeId, progressCallback)` - BFS backwards to entrypoints, cycle-safe
- `getVisibleGraph()` - Returns current visible subset
- `getHiddenNeighborCount(nodeId)` - For future badge display

**Key Features:**
- Tracks expanded/collapsed state per node
- Adjacency maps for efficient neighbor lookup
- Orphan pruning: removes nodes with no connections to visible nodes
- Never removes entrypoints (protected)
- Progress reporting for path tracing

### 3. Fixed Entrypoint Positioning

**File: `graph-filters.js`**

Modified node creation to:
- Detect entrypoints via `this.appEntrypoints.has(node.id)`
- Set `fixed: {x: true, y: true}, physics: false` for entrypoints
- Position entrypoints in horizontal row: `x: nodes.length * 300 - 600, y: 0`

This prevents entrypoints from moving during expansion animations.

### 4. Interaction Modes

**File: `graph-network/initialization.js`**

Replaced simple click handlers with multi-mode detection:

- **Single click**: Expand node (show neighbors)
- **Double click**: Collapse node (remove + orphans)
- **Shift+click**: Trace paths to entrypoints (highlight)
- **Ctrl/Cmd+click**: Select only (no expansion)
- **Edge click**: Navigate to target node (select only)

Implementation uses 250ms timeout to distinguish single from double clicks.

### 5. Main Application Integration

**File: `main.js`**

**New Methods:**

```javascript
async renderEntrypointsOnly()
// Initial render - shows only 3 entrypoint nodes
// Physics disabled (entrypoints are fixed)

async expandNode(nodeId)
// Expansion with animation:
// 1. Focus viewport on clicked node
// 2. Fix all currently visible nodes
// 3. Add new nodes incrementally (25ms/node bubble-in)
// 4. New nodes positioned in circle around parent
// 5. Enable physics for new nodes only
// 6. After 2s settle: fix new nodes, update stats

collapseNode(nodeId)
// Remove node + orphans from DataSets
// Update stats

async tracePathsFromNode(nodeId)
// Show progress indicator
// Call expansionManager.tracePaths()
// Apply PATH state via setPathHighlight()

selectNodeOnly(nodeId)
// Update left panel without expansion

focusNodeFromPanel(nodeId)
// Navigate from panel connection links
// Centers viewport, updates selection, no expansion
```

**Event Handlers:**
- `expandNode` - triggers expansion animation
- `collapseNode` - triggers removal
- `traceNode` - triggers path highlighting  
- `selectNodeOnly` - triggers panel update only
- `zoom`/`dragStart` - stops auto-centering during expansion animation

**Startup Flow:**
```javascript
setupViewer() {
    // Load all graph data
    const allData = this.filters.generateFilteredGraph();
    
    // Initialize expansion manager with full data
    this.expansionManager = new ExpansionManager(allData.nodes, allData.edges);
    
    // Render only entrypoints
    await this.renderEntrypointsOnly();
}
```

### 6. Path Highlighting

**File: `graph-network/index.js`**

Added `setPathHighlight(nodeIds, edgeIds)` method:
- Uses state-based styling system
- Applies `PATH` state to specified nodes/edges
- Applies `DIMMED` state to others
- Diff-based updates (only changes renderState if different)

Imports `getNodeStyle` and `getEdgeStyle` from `state-styles.js`.

### 7. Panel Navigation

**File: `graph-ui.js`**

Enhanced `renderEdgeItem()` to add click handlers:
```javascript
onclick="window.codeGraphViewer.focusNodeFromPanel('${connectedNodeId}')"
```

Clicking a connection in the left panel:
- Centers viewport on that node
- Updates selection
- Does NOT expand automatically
- Allows inspection before expansion

### 8. User Instructions

**File: `index.html`**

Added interaction instructions panel:
```
Interactions:
• Click: Expand node
• Double-click: Collapse node
• Shift+click: Trace paths
• Ctrl+click: Select only
• Panel links: Focus node
```

## Architecture

### Data Flow

```
All Data (full graph)
    ↓
ExpansionManager (tracks visible subset)
    ↓
DataSets (rendered nodes/edges)
    ↓
Vis.js Network (visualization)
```

### Key Separations

1. **All vs Visible**: `allNodes`/`allEdges` vs `network.nodes`/`network.edges`
2. **Fixed vs Physics**: Entrypoints fixed, new nodes animated, then frozen
3. **Expansion State**: Tracked by ExpansionManager, not by DataSets
4. **Progressive Rendering**: Incremental add (25ms/node) for smooth animation

## Physics Behavior

### During Expansion
1. Fix all currently visible nodes (`fixed: {x:true, y:true}, physics: false`)
2. Add new nodes with `physics: true` around parent in circle pattern
3. Let new nodes settle for 2 seconds
4. Fix new nodes (`fixed: {x:true, y:true}, physics: false`)

### Auto-Center Interrupt
- User zoom/drag during expansion sets `autoCenterDuringExpansion = false`
- Stops viewport from auto-following new nodes
- User can pan away to inspect other areas while expansion continues

## Statistics

Stats display shows:
- **Total Nodes/Edges**: Full graph size (all data)
- **Visible Nodes/Edges**: Currently rendered subset

Updated after:
- Initial render (entrypoints only)
- Each expansion (incremental add)
- Each collapse (decremental remove)

## Edge Cases Handled

### Entrypoint Protection
- `collapseNode()` never removes entrypoints
- `findOrphans()` never returns entrypoints
- Entrypoints always remain visible

### Cycle Safety
- `tracePaths()` uses `visited` set
- Prevents infinite loops in cyclic graphs

### Already Expanded
- `expandNode()` returns early if node already expanded
- No duplicate nodes added

### Orphan Detection
- Node is orphan if all its connections lead to invisible nodes
- Checks both incoming and outgoing edges
- BFS to verify no path to any visible node

## Performance Considerations

### Incremental Rendering
- Adding 50 nodes takes 50 * 25ms = 1.25 seconds
- Smooth bubble-in animation
- Prevents blocking main thread

### Adjacency Maps
- O(1) neighbor lookup
- Pre-computed during initialization
- Efficient expansion/collapse operations

### State Tracking
- ExpansionManager maintains expansion state
- No need to query DataSets for state
- Fast operations even with large graphs

## Future Enhancements

### Badge Display
- `getHiddenNeighborCount(nodeId)` ready
- Could show "• 5 hidden" badge on nodes
- Visual indicator of expandable neighbors

### Expansion Depth Limits
- Could limit expansion to N levels deep
- Prevent accidental expansion of entire graph
- "Expand All Children" explicit action

### Partial Expansion
- Instead of expanding all neighbors
- Could allow selecting which edges to follow
- More fine-grained control

### Expansion History
- Track expansion order
- "Undo" button to reverse last expansion
- Breadcrumb trail of exploration path

## Testing Recommendations

1. **Verify Entrypoint Detection**
   - Check that exactly 3 nodes appear initially
   - Confirm they match expected locations

2. **Test Expansion**
   - Click each entrypoint
   - Verify neighbors appear
   - Check physics animation

3. **Test Collapse**
   - Expand a node, then double-click it
   - Verify orphans are removed
   - Verify entrypoints never removed

4. **Test Path Tracing**
   - Expand several levels deep
   - Shift+click a leaf node
   - Verify path highlighting back to entrypoint

5. **Test Panel Navigation**
   - Click connections in left panel
   - Verify viewport centers without expansion

6. **Test Auto-Center Interrupt**
   - Click to expand
   - Zoom or pan during animation
   - Verify auto-centering stops

## Known Limitations

1. **No Partial Load**: All graph data loaded upfront, only rendering is progressive
2. **No Depth Limits**: User can expand entire graph if they click every node
3. **No Badge Display**: Hidden neighbor counts computed but not shown yet
4. **No Expansion History**: Can't undo expansions (must collapse manually)

## Files Modified

1. `graph-loader.js` - Added `findApplicationEntrypoints()`
2. `graph-filters.js` - Entrypoint marking and positioning
3. `graph-expansion.js` - NEW - ExpansionManager class
4. `graph-network/initialization.js` - Multi-mode click handlers
5. `graph-network/index.js` - Added `setPathHighlight()`
6. `main.js` - Integration, event handlers, expansion methods
7. `graph-ui.js` - Panel navigation click handlers
8. `index.html` - Interaction instructions

## Lines of Code

- **graph-expansion.js**: ~210 lines (new file)
- **main.js**: +~115 lines (expansion methods)
- **initialization.js**: +~35 lines (click mode detection)
- **graph-network/index.js**: +~32 lines (setPathHighlight)
- **Other files**: ~20 lines total

**Total**: ~412 new lines of code

## Implementation Status

✅ **Complete:**
- Entrypoint detection (3 specific nodes)
- Expansion manager (track visibility)
- Fixed positioning (entrypoints don't move)
- Click mode detection (single/double/shift/ctrl)
- Expansion animation (bubble-in, physics wave)
- Collapse with orphan pruning
- Path tracing with progress
- Panel navigation without expansion
- Stats updates
- User instructions

🚧 **Not Implemented:**
- Badge display (hidden neighbor counts)
- Expansion depth limits
- Expansion history/undo
- Partial expansion (selective edge following)

---

**Status**: Feature complete and ready for testing.
**Implementation Date**: 2025-01-09
**Implemented By**: GitHub Copilot + User
