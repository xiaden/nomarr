# Code Graph Viewer

Interactive visualization tool for exploring Nomarr's code dependency graph.

## Structure

```
scripts/viewers/code-graph/
├── index.html              # Main HTML shell (~100 lines)
├── css/
│   └── viewer.css          # All styles (~270 lines)
└── js/
    ├── main.js             # Application orchestration (~160 lines)
    ├── graph-loader.js     # Data loading & validation (~230 lines)
    ├── graph-filters.js    # Filter logic & graph generation (~340 lines)
    ├── graph-network.js    # vis.js network management (~180 lines)
    └── graph-ui.js         # UI interactions & display (~380 lines)
```

## Module Responsibilities

### `graph-loader.js` - Data Management
- Load graph from URL or file
- Validate JSON structure
- Build interface connection map (BFS from each entrypoint)
- Provide data access methods

### `graph-filters.js` - Filtering Logic
- Manage filter state (layers, kinds, edges, search, interface)
- Apply filters to nodes and edges
- Compute transitive edges through hidden nodes
- Generate filtered graph data for visualization

### `graph-network.js` - Network Visualization
- Initialize and manage vis.js network
- Handle network events (click, double-click)
- Update graph data
- Control network view (fit, focus, selection)

### `graph-ui.js` - User Interface
- Initialize filter controls (dropdowns, checkboxes)
- Handle user interactions
- Update statistics display
- Show node details
- Manage loading/error states

### `main.js` - Orchestration
- Wire all modules together
- Coordinate initialization flow
- Handle file loading fallback
- Connect UI events to network updates

## Usage

### Running the Viewer

**Option 1: Local server (recommended)**
```bash
cd scripts/viewers/code-graph
python -m http.server 8000
# Open http://localhost:8000
```

**Option 2: File protocol**
Open `index.html` directly in browser and use file picker to load `../../outputs/code_graph.json`.

### Generating Graph Data

Run the code graph builder:
```bash
python scripts/build_code_graph.py
```

This creates `scripts/outputs/code_graph.json` which the viewer loads.

## Features

- **Interface Filtering**: Filter graph to show only code reachable from specific entrypoints
- **Layer/Kind Filtering**: Show/hide by architecture layer or node type
- **Search**: Filter by node name or ID
- **Transitive Edges**: Show connections through hidden nodes
- **Node Details**: Click nodes to see documentation, edges, and metadata
- **Interactive Network**: Pan, zoom, drag nodes, use navigation buttons

## Development

### Adding New Features

1. **New filter type**: Add to `GraphFilters` class
2. **New visualization option**: Add to `GraphNetwork` class
3. **New UI control**: Add to `GraphUI` class
4. **New data source**: Extend `GraphLoader` class

### Architecture Notes

- Uses ES6 modules (`type="module"`)
- Event-driven communication between modules
- No framework dependencies (vanilla JS + vis.js)
- Follows separation of concerns:
  - Data layer (`graph-loader`)
  - Business logic (`graph-filters`)
  - Visualization (`graph-network`)
  - Presentation (`graph-ui`)
  - Orchestration (`main`)

## Future Enhancements

- Export filtered graph as JSON or image
- URL parameters for sharing filter state
- Metrics dashboard (most connected nodes, dead code)
- Graph comparison mode
- Keyboard shortcuts
- Performance optimizations for large graphs
