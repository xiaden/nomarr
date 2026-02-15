# Tag Co-Occurrence Grid

Redesigned co-occurrence visualization with preset-first UX.

## Component Structure

```
TagCoOccurrenceGrid/
├── index.ts                 # Public export
├── types.ts                 # Type definitions
├── TagCoOccurrenceGrid.tsx  # Main container
├── useAxisState.ts          # Axis state management hook
├── usePresetData.ts         # Preset data fetching hook
├── PresetSelector.tsx       # Axis preset picker (segmented buttons)
├── HeatmapGrid.tsx          # Grid rendering with sticky headers
├── HeatmapCell.tsx          # Individual cell with tooltip
├── ColorLegend.tsx          # Gradient legend explaining scale
└── ManualTagSelector.tsx    # Advanced accordion for manual selection
```

## Layout (Panel + SectionHeader)

```
┌────────────────────────────────────────────────────────────────┐
│  Tag Co-Occurrence Grid                            [?]  │  <- SectionHeader
├────────────────────────────────────────────────────────────────┤
│                                                        │
│  X Axis: [ Genre ] [ Mood ] [ Year ] [ Manual ]        │  <- PresetSelector
│  Y Axis: [ Genre ] [ Mood ] [ Year ] [ Manual ]   [⇄]  │  <- PresetSelector + Swap
│                                                        │
│  ▶ Advanced (Manual Tag Selection)                     │  <- Accordion (collapsed)
│                                                        │
├────────────────────────────────────────────────────────────────┤
│                                                        │
│           │ Rock │ Pop │ Jazz │ Elec │ ...            │  <- Sticky column headers
│     ─────┼──────┼─────┼──────┼──────┼─────             │
│  2020 │  42  │  18 │   3  │  27  │ ...            │  <- Rows with sticky
│  2021 │  38  │  22 │   5  │  31  │ ...            │     first column
│  2022 │  45  │  19 │   8  │  29  │ ...            │
│  ...  │  ... │ ... │  ... │  ... │ ...            │
│                                                        │
├────────────────────────────────────────────────────────────────┤
│  [0] ───────────── [max]                               │  <- ColorLegend
│   Low                    High                          │
└────────────────────────────────────────────────────────────────┘
```

## UI Components

### PresetSelector
- MUI ToggleButtonGroup (exclusive selection)
- Options: Genre | Mood | Year | Manual
- Changing preset triggers data fetch and auto-populates axis tags
- Displayed for both X and Y axes
- Swap button (⇄) between the two selectors swaps entire axis states

### HeatmapGrid
- MUI Table with sticky positioning:
  - Column headers: sticky top
  - Row headers (first column): sticky left
  - Corner cell: sticky top + left
- Horizontal scroll for wide matrices
- Vertical scroll contained within panel

### HeatmapCell
- Background color computed from count/max ratio
- Color scale: dark (#1a1a1a) → blue gradient (#4a9eff)
- MUI Tooltip on hover showing:
  - X tag: {key}: {value}
  - Y tag: {key}: {value}
  - Count: {n} files
  - Percentage: {n/total * 100}% of max

### ColorLegend
- Horizontal gradient bar showing scale
- Labels: "0" on left, "{max}" on right
- Caption: "Files matching both tags"

### ManualTagSelector (Advanced Accordion)
- Collapsed by default
- Expands to show:
  - Tag key dropdown (ComboBox)
  - Tag value dropdown (ComboBox, filtered by key)
  - "Add to X" / "Add to Y" buttons
  - Chip lists showing manually added tags with delete
- Only enabled when respective axis preset is "Manual"
- Retains original duplicate prevention logic

## State Flow

1. **Initial Load**
   - X axis: Genre preset (auto-fetch genre values)
   - Y axis: Year preset (auto-fetch year values)
   - Build matrix immediately with defaults

2. **Preset Change**
   - User clicks different preset button
   - Fetch values for that preset
   - Replace axis tags with fetched values (capped at 16)
   - Rebuild matrix

3. **Swap Axes**
   - User clicks swap button
   - X and Y states swap (preset + tags)
   - Matrix transposed visually (re-fetch with swapped params)

4. **Manual Mode**
   - User selects "Manual" preset
   - Advanced accordion becomes active for that axis
   - User adds/removes individual tags
   - Matrix rebuilds on each change

## Color Scale Implementation

```typescript
function getHeatmapColor(count: number, maxCount: number): string {
  if (count === 0) return "#1a1a1a"; // Dark for zero
  const intensity = Math.min(count / maxCount, 1);
  // Blue gradient for dark theme
  const r = Math.floor(30 + intensity * 44);   // 30 → 74
  const g = Math.floor(30 + intensity * 128);  // 30 → 158
  const b = Math.floor(30 + intensity * 225);  // 30 → 255
  return `rgb(${r}, ${g}, ${b})`;
}
```

## Tooltip Content

```
┌───────────────────────┐
│ genre: Rock           │
│ year: 2022            │
│ ───────────────────── │
│ 45 files              │
│ (73% of max)          │
└───────────────────────┘
```

## Empty/Loading/Error States

- **Loading preset**: Skeleton placeholder in grid area
- **Loading matrix**: Spinner overlay on grid
- **No data**: "No files match the selected tag combinations"
- **Error**: Alert banner with retry button
