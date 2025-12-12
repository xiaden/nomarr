# MUI Design System Integration

## Overview

The Nomarr frontend now fully supports Material-UI (MUI) components, providing a comprehensive design system with:

- **@mui/material** (v7.3.6) - Core UI components
- **@mui/icons-material** (v7.3.6) - Icon library
- **@emotion/react** + **@emotion/styled** - Required styling engine
- **@mui/x-charts** (v8.22.0) - Charting components (Bar, Line, Heatmap, etc.)
- **@mui/x-data-grid** (v8.22.0) - High-performance data tables

## Architecture

### Theme Configuration

The MUI theme is configured in `src/theme.ts` with:

- **Dark mode** matching the existing application aesthetic
- **Custom color palette**:
  - Primary: `#4a9eff` (accent blue)
  - Secondary: `#6c757d` (gray)
  - Background: `#0a0a0a` (very dark) / `#1a1a1a` (paper)
  - Text: `#ffffff` (primary) / `#888888` (secondary)
- **Typography** using system fonts
- **Component overrides**:
  - Buttons with normal text transform (not uppercase)
  - Cards/Paper without default gradients

### Global Setup

The theme is applied globally in `src/main.tsx`:

```tsx
import { ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import { theme } from "./theme";

<ThemeProvider theme={theme}>
  <CssBaseline />
  <App />
</ThemeProvider>
```

## Integration Examples

### 1. MUI Demo Page

**Location**: `src/components/MuiDemo.tsx`  
**Route**: `/mui-demo`

Demonstrates all major MUI features:

- **Buttons**: Contained, outlined, text variants with icons
- **Layout**: Box, Stack, Card components
- **Charts**: BarChart and LineChart with sample data
- **DataGrid**: Paginated table with checkbox selection

### 2. Browse Files Page Updates

**Location**: `src/pages/BrowseFilesPage.tsx`

Applied MUI components to existing page:

- **Search button**: Replaced native button with MUI `Button` with `Search` icon
- **Pagination**: Replaced native buttons with MUI `Button` in `Stack` layout using `Box` container
- **File Tags Display**: Replaced card-based tag grid with `FileTagsDataGrid` component

### 3. File Tags DataGrid Component

**Location**: `src/components/FileTagsDataGrid.tsx`

A modernized, scalable tag viewing component built with MUI X DataGrid:

**Features**:
- **Sortable columns**: Click headers to sort by key, value, type, or Nomarr status
- **Quick filter**: Text field to filter tags by key, value, or type
- **Nomarr toggle**: Switch to show only Nomarr tags (`nom:` prefixed)
- **Smart value display**: Tooltip for values longer than 50 characters
- **Type chips**: Visual chip display for tag types (string, float, int, etc.)
- **Nomarr badges**: Primary-colored chip for Nomarr tags
- **Pagination**: 25 tags per page (configurable: 10/25/50/100)
- **Responsive layout**: Fixed 400px height with scrolling

**Columns**:
- `Key` - Tag key (bold + primary color for Nomarr tags)
- `Value` - Tag value (truncated with tooltip for long values)
- `Type` - Tag type as outlined chip
- `Nomarr` - Primary chip badge for Nomarr tags

**Usage**:
```tsx
import { FileTagsDataGrid } from "../components/FileTagsDataGrid";

<FileTagsDataGrid tags={file.tags} />
```

## Available Components

### Core Components (@mui/material)

Layout:
- `Box` - Flexible container with sx prop
- `Stack` - Flexbox layout with spacing
- `Container`, `Grid`, `Paper`, `Card`

Inputs:
- `Button`, `IconButton`, `ButtonGroup`
- `TextField`, `Select`, `Checkbox`, `Radio`
- `Switch`, `Slider`, `Autocomplete`

Display:
- `Typography`, `Chip`, `Badge`, `Avatar`
- `Divider`, `List`, `Table`, `Tooltip`
- `Dialog`, `Drawer`, `Menu`, `Snackbar`

### Charts (@mui/x-charts)

Available chart types:
- `BarChart` - Bar charts with horizontal/vertical orientation
- `LineChart` - Line charts with multiple series
- `PieChart` - Pie and donut charts
- `ScatterChart` - Scatter plots
- `Sparkline` - Compact inline charts
- `Gauge` - Gauge/progress indicators

**Usage example**:

```tsx
import { BarChart } from "@mui/x-charts/BarChart";

<BarChart
  xAxis={[{ scaleType: "band", data: ["A", "B", "C"] }]}
  series={[{ data: [4, 3, 5] }]}
  height={300}
/>
```

### Data Grid (@mui/x-data-grid)

High-performance table component with:
- Sorting, filtering, pagination
- Column resizing and reordering
- Row selection (single/multiple)
- Virtualization for large datasets
- Excel export capabilities

**Usage example**:

```tsx
import { DataGrid, type GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "id", headerName: "ID", width: 90 },
  { field: "name", headerName: "Name", width: 150 },
];

const rows = [
  { id: 1, name: "John" },
  { id: 2, name: "Jane" },
];

<DataGrid rows={rows} columns={columns} />
```

**See `FileTagsDataGrid` component** for a production implementation with:
- Custom cell renderers (chips, tooltips)
- Quick filter integration
- Toggle-based row filtering
- Responsive layout with fixed height

## Styling Approaches

### 1. sx Prop (Recommended)

Use the `sx` prop for inline styling with theme awareness:

```tsx
<Box sx={{ 
  p: 3,              // padding: theme.spacing(3)
  mt: 2,             // marginTop: theme.spacing(2)
  bgcolor: "background.paper",
  borderRadius: 1,
}}>
  Content
</Box>
```

### 2. styled Components

For reusable styled components:

```tsx
import { styled } from "@mui/material/styles";

const StyledCard = styled(Card)(({ theme }) => ({
  padding: theme.spacing(2),
  backgroundColor: theme.palette.background.paper,
}));
```

### 3. Theme-aware Colors

Access theme colors directly:

```tsx
<Typography color="primary.main">Text</Typography>
<Box sx={{ bgcolor: "secondary.dark" }}>Box</Box>
```

## Migration Strategy

### Existing Pages

The integration is **non-breaking**. Existing pages continue to work with inline styles. Gradually migrate components:

1. **Replace native buttons** → `Button` from MUI
2. **Replace inline styles** → `sx` prop or `styled` components
3. **Add layout components** → `Box`, `Stack`, `Container`
4. **Migrate tables** → `DataGrid` for complex tables
5. **Add charts** → Use `@mui/x-charts` for visualizations

### Future Refactoring

Candidate pages for MUI migration:

- **AnalyticsPage**: Replace chart visualizations with MUI X Charts
- **QueuePage**: Replace table with DataGrid
- **BrowseFilesPage**: Full migration to MUI layout and components
- **Forms**: Use MUI TextField, Select, etc. throughout

## TypeScript Integration

All MUI components are fully typed. Import types when needed:

```tsx
import type { ButtonProps } from "@mui/material/Button";
import type { GridColDef, GridRowsProp } from "@mui/x-data-grid";
```

## Build Verification

- ✅ TypeScript compilation successful
- ✅ Vite build successful (1.03s)
- ✅ Production bundle size: 1.29 MB (381 KB gzipped)
- ✅ No breaking changes to existing code
- ✅ All imports properly resolved

## Resources

- [MUI Documentation](https://mui.com/)
- [MUI X Charts](https://mui.com/x/react-charts/)
- [MUI X Data Grid](https://mui.com/x/react-data-grid/)
- [Emotion Styling](https://emotion.sh/)

## Next Steps

1. **Explore the demo**: Visit `/mui-demo` to see all components in action
2. **Gradual adoption**: Start using MUI components in new features
3. **Chart integration**: Replace analytics visualizations with MUI X Charts
4. **Table migration**: Use DataGrid for complex tabular data
5. **Design consistency**: Follow MUI patterns for new UI components
