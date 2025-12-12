/**
 * FileTagsDataGrid - Display file tags in a MUI DataGrid
 *
 * Features:
 * - Sortable columns
 * - Quick filter search
 * - Toggle to show only Nomarr tags
 * - Chip display for Nomarr status
 * - Tooltip for long values
 */

import {
    Box,
    Chip,
    FormControlLabel,
    Stack,
    Switch,
    TextField,
    Tooltip,
    Typography,
} from "@mui/material";
import { DataGrid, type GridColDef, type GridRowsProp } from "@mui/x-data-grid";
import { useMemo, useState } from "react";

interface FileTag {
  key: string;
  value: string;
  type: string;
  is_nomarr: boolean;
}

interface FileTagsDataGridProps {
  tags: FileTag[];
}

interface TagRow {
  id: string;
  key: string;
  value: string;
  type: string;
  is_nomarr: boolean;
}

const truncateValue = (value: string, maxLength = 50): string => {
  if (value.length <= maxLength) return value;
  return value.substring(0, maxLength) + "...";
};

export function FileTagsDataGrid({ tags }: FileTagsDataGridProps) {
  const [showNomarrOnly, setShowNomarrOnly] = useState(false);
  const [quickFilter, setQuickFilter] = useState("");

  // Convert tags to DataGrid rows
  const rows: GridRowsProp<TagRow> = useMemo(() => {
    let filteredTags = tags;

    // Filter by Nomarr tags if toggle is enabled
    if (showNomarrOnly) {
      filteredTags = filteredTags.filter((tag) => tag.is_nomarr);
    }

    return filteredTags.map((tag, idx) => ({
      id: `${tag.key}-${idx}`, // Use combination of key + index for unique ID
      key: tag.key,
      value: tag.value,
      type: tag.type,
      is_nomarr: tag.is_nomarr,
    }));
  }, [tags, showNomarrOnly]);

  // Define columns
  const columns: GridColDef<TagRow>[] = [
    {
      field: "key",
      headerName: "Key",
      flex: 1,
      minWidth: 180,
      renderCell: (params) => (
        <Typography
          variant="body2"
          sx={{
            fontWeight: params.row.is_nomarr ? 600 : 400,
            color: params.row.is_nomarr ? "primary.main" : "text.primary",
          }}
        >
          {params.value}
        </Typography>
      ),
    },
    {
      field: "value",
      headerName: "Value",
      flex: 2,
      minWidth: 250,
      renderCell: (params) => {
        const fullValue = params.value as string;
        const displayValue = truncateValue(fullValue);
        const isTruncated = fullValue.length > 50;

        return isTruncated ? (
          <Tooltip title={fullValue} arrow>
            <Typography variant="body2" sx={{ cursor: "help" }}>
              {displayValue}
            </Typography>
          </Tooltip>
        ) : (
          <Typography variant="body2">{displayValue}</Typography>
        );
      },
    },
    {
      field: "type",
      headerName: "Type",
      width: 100,
      renderCell: (params) => (
        <Chip
          label={params.value}
          size="small"
          variant="outlined"
          sx={{ fontSize: "0.75rem" }}
        />
      ),
    },
    {
      field: "is_nomarr",
      headerName: "Nomarr",
      width: 100,
      type: "boolean",
      renderCell: (params) =>
        params.value ? (
          <Chip
            label="nom:"
            size="small"
            color="primary"
            sx={{ fontSize: "0.75rem" }}
          />
        ) : null,
    },
  ];

  // Apply quick filter
  const filteredRows = useMemo(() => {
    if (!quickFilter) return rows;

    const lowerFilter = quickFilter.toLowerCase();
    return rows.filter(
      (row) =>
        row.key.toLowerCase().includes(lowerFilter) ||
        row.value.toLowerCase().includes(lowerFilter) ||
        row.type.toLowerCase().includes(lowerFilter)
    );
  }, [rows, quickFilter]);

  return (
    <Box sx={{ mt: 2 }}>
      {/* Header with controls */}
      <Stack
        direction="row"
        spacing={2}
        alignItems="center"
        justifyContent="space-between"
        sx={{ mb: 2 }}
      >
        <Typography variant="h6" component="div">
          Tags ({tags.length})
        </Typography>

        <Stack direction="row" spacing={2} alignItems="center">
          <TextField
            size="small"
            placeholder="Filter tags..."
            value={quickFilter}
            onChange={(e) => setQuickFilter(e.target.value)}
            sx={{ width: 250 }}
          />

          <FormControlLabel
            control={
              <Switch
                checked={showNomarrOnly}
                onChange={(e) => setShowNomarrOnly(e.target.checked)}
                size="small"
              />
            }
            label="Nomarr only"
          />
        </Stack>
      </Stack>

      {/* DataGrid */}
      {tags.length === 0 ? (
        <Box
          sx={{
            p: 3,
            textAlign: "center",
            color: "text.secondary",
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
          }}
        >
          No tags found
        </Box>
      ) : (
        <Box sx={{ height: 400, width: "100%" }}>
          <DataGrid
            rows={filteredRows}
            columns={columns}
            initialState={{
              pagination: {
                paginationModel: { page: 0, pageSize: 25 },
              },
              sorting: {
                sortModel: [{ field: "key", sort: "asc" }],
              },
            }}
            pageSizeOptions={[10, 25, 50, 100]}
            disableRowSelectionOnClick
            density="compact"
            sx={{
              border: 1,
              borderColor: "divider",
              "& .MuiDataGrid-cell": {
                borderColor: "divider",
              },
              "& .MuiDataGrid-columnHeaders": {
                backgroundColor: "background.paper",
                borderBottom: 2,
                borderColor: "divider",
              },
            }}
          />
        </Box>
      )}
    </Box>
  );
}
