# G6 v5 API Compliance Verification

## Verification Process (Dec 16, 2025)

This document tracks verification of our G6 v5 API usage against official documentation in `docs/`.

## APIs Used and Documentation References

### 1. Graph Initialization
**File**: `graph-init.js`
**Doc Reference**: `docs/manual/getting-started/quick-start.en.md`, `docs/manual/graph/option.en.md`

✅ **Verified Correct**:
- `new G6.Graph({ container, width, height, ... })` - Standard constructor pattern
- `behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element']` - v5 array format (not v4 `modes` object)
- `node: { type, style: {...}, state: {...} }` - v5 node config (not v4 `defaultNode`)
- `edge: { type, style: {...}, state: {...} }` - v5 edge config (not v4 `defaultEdge`)
- `layout: { type: 'force', ... }` - Standard layout config

**Label Configuration**:
**Doc Reference**: `docs/manual/element/node/BaseNode.en.md` (lines 415-429)
- `labelFill`, `labelFontSize`, `labelPlacement`, `labelOffsetY` are documented v5 properties
- Placed in `node.style` object as per docs

### 2. Data Structure
**File**: `graph-renderer.js`
**Doc Reference**: `docs/manual/data.en.md` (lines 35-70)

✅ **Verified Correct**:
```javascript
{
  id: 'node-1',
  data: { label, layer, ... },  // Custom data
  style: { x, y, fill, stroke, size }  // Visual properties
}
```
Matches documented structure exactly.

### 3. Data Operations
**Files**: `graph-renderer.js`, `main.js`
**Doc Reference**: `docs/api/data.en.md` (lines 428-460)

✅ **Verified Correct**:
- `graph.setData({ nodes, edges })` - v5 API (replaces v4 `data()` and `changeData()`)
- `graph.getNodeData()` - v5 API to get all nodes (not v4 `getNodes()`)

### 4. Rendering
**File**: `graph-renderer.js`
**Doc Reference**: `docs/api/render.en.md` (lines 85-100)

✅ **Verified Correct**:
- `await graph.render()` - Complete rendering with layout
- `await graph.draw()` - Draw only, no layout recalc

### 5. Element State
**File**: `main.js` (handleTrace function)
**Doc Reference**: `docs/api/element.en.md` (lines 159-210)

✅ **Verified Correct**:
```javascript
graph.setElementState({
  'node1': ['selected'],
  'node2': ['dimmed']
})
```
Batch state setting with object map.

### 6. Viewport Operations
**File**: `main.js` (handleFit), `graph-renderer.js` (focusOnNode)
**Doc Reference**: `docs/api/viewport.en.md` (lines 1-150), `docs/api/element.en.md` (line 625)

✅ **Verified Correct**:
- `graph.fitView({ padding: [...] })` - Documented v5 API
- `graph.focusElement(id, { easing, duration })` - v5 API (replaces v4 `focusItem`)

### 7. Event Handling
**File**: `graph-behaviors.js`
**Doc Reference**: `docs/api/event.en.md` (lines 60-90, 432-437)

✅ **Verified Correct**:
- `graph.on('node:click', (evt) => { evt.target.id })` - v5 event object structure
- `evt.originalEvent` for browser event access
- Event naming: `node:click`, `canvas:click` matches docs

## Mismatches Found and Fixed

### 1. Label Property Name (FIXED)
**Issue**: Using `label` in data object instead of `labelText` in style
**Doc Reference**: `docs/manual/element/node/BaseNode.en.md` (line 431)
**Fix**: Changed `data: { label: ... }` to `style: { labelText: ... }`
**Files Changed**: `graph-renderer.js` (both `renderGraph` and `updateGraph` functions)

**Before**:
```javascript
{
  id: n.id,
  data: { label: n.data.label, ...n.data },
  style: { fill, stroke }
}
```

**After**:
```javascript
{
  id: n.id,
  data: n.data,
  style: { labelText: n.data.label, fill, stroke }
}
```

## Remaining Issues to Investigate

If errors persist, check:
1. G6 CDN version loaded (verify 5.0.50 in console)
2. Browser console for specific runtime errors
3. Data transformation edge cases in graph-renderer.js

## Documentation Files Used

Primary references:
- `docs/manual/getting-started/quick-start.en.md`
- `docs/manual/data.en.md`
- `docs/manual/graph/option.en.md`
- `docs/manual/element/node/BaseNode.en.md`
- `docs/api/data.en.md`
- `docs/api/render.en.md`
- `docs/api/element.en.md`
- `docs/api/viewport.en.md`
- `docs/api/event.en.md`

## UI/Util Cleanup (Dec 16, 2025 - Pass 4)

### Issue 1: Duplicate File-Input Wiring (FIXED)
**Problem**: File-input change listener registered in both toolbar-controller.js and main.js
**Root Cause**: Selecting a file triggered initializeGraph twice
**Fix**: 
- Removed duplicate listener from main.js (lines 68-71)
- toolbar-controller.js now owns file-input wiring exclusively
- Updated handleFileUpload() in main.js to accept file parameter from toolbar callback
- Moved initializeGraph() to module scope (was nested in DOMContentLoaded, causing ReferenceError)
**Files**: `main.js`, `toolbar-controller.js`
**Result**: File selection triggers graph initialization exactly once without runtime errors

### Issue 2: Panel Styling Mismatch (FIXED)
**Problem**: panel-controller.js generated classes (detail-row, node-details) that don't exist in style.css
**Existing CSS**: Uses info-row, info-label, info-value, connection-list
**Fix**: Updated panel-controller.js markup to use existing CSS classes
**Changes**:
- `<div class="detail-row"><strong>X:</strong> Y</div>` → `<div class="info-row"><span class="info-label">X</span><span class="info-value">Y</span></div>`
- Removed unused node-details and connections-section wrappers
- Added connection-list class to `<ul>` elements
**File**: `panel-controller.js`
**Result**: Panel details now styled correctly per existing CSS

### Issue 3: Incorrect V4 Detection (FIXED)
**Problem**: detectV4Usage() warned about graph.render() which exists in v5
**Old Warnings**: 
- "graph.data() exists. Use graph.changeData()" (changeData doesn't exist in v5)
- "graph.render() exists. G6 v5 renders automatically." (v5 HAS graph.render())
**Fix**: Check actual v4 patterns instead of API presence
**New Checks**:
- `modes` config object (v4) vs `behaviors` array (v5)
- `defaultNode`/`defaultEdge` (v4) vs `node`/`edge` (v5)
**File**: `guards.js`
**Result**: No false warnings on valid v5 code

## Collapse Manager Optimization (Dec 16, 2025 - Pass 3)

### Edge Consistency
**Verification**: ExpansionManager.getVisibleGraph() deterministically rebuilds edges
**Implementation**: Filters `graphModel.edges` by checking both source and target in `visibleNodeIds`
**Result**: No dangling edges possible - edges automatically excluded when either endpoint removed

### Orphan Pruning Performance Improvements
**File**: `collapse-manager.js` - _pruneOrphans()

**Optimization 1: Early-Exit Neighbor Check**
- Replaced `Array.from(set).filter(id => visibleIds.has(id))` with early-exit loop
- New `_hasVisibleNeighbor()` method returns immediately on first visible neighbor found
- Avoids allocating arrays and iterating full adjacency lists

**Optimization 2: Collect-Then-Delete Pattern**
- Collects orphan IDs in array first, deletes after iteration completes
- Avoids mutating Set while iterating over it (undefined behavior)
- Maintains cascade prune behavior with iterative loop

**Optimization 3: Documentation**
- Added inline docs explaining edge consistency guarantee
- Clarified entrypoint protection and cascade behavior

**Impact**: Large graphs with many orphans prune significantly faster without changing behavior

## Correctness Fixes (Dec 16, 2025 - Pass 2)

### 1. Position Preservation During Updates
**Issue**: updateGraph() recreated nodes without x/y, causing layout jumps
**Fix**: Read current graph node positions before update, preserve them in new data
**File**: `graph-renderer.js` - updateGraph()
**Impact**: Expanding/collapsing nodes maintains stable positions

### 2. Entrypoint Protection During Collapse  
**Issue**: Verify entrypoints cannot be collapsed or pruned
**Status**: ✅ Already correctly implemented
**File**: `collapse-manager.js` - collapse() and _pruneOrphans()
**Protection**: Both check `this.entrypointIds.has(nodeId)` before removal

### 3. Path Tracing State Merge
**Issue**: handleTrace() replaced all states, losing 'selected' state
**Fix**: Merge states - preserve 'selected', add 'path'/'dimmed' appropriately
**File**: `main.js` - handleTrace()
**Impact**: Tracing paths no longer deselects nodes

### 4. Streamed Expansion Preparation
**Issue**: expand() returned only graph, no info about what was added
**Fix**: expand() now returns `{ graph, added }` with array of new node IDs
**Files**: `expansion-manager.js` - expand(), `main.js` - handleExpand()
**Impact**: Enables future streaming/progressive rendering without blocking

## Current Status

✅ All APIs match G6 v5 documentation
✅ No v4 patterns detected
✅ UX behaviors preserved per requirements
✅ Position stability maintained
✅ Entrypoint protection verified
✅ State management improved
