import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { Alert, Box, Button, IconButton } from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";
import type {
  GridColDef,
  GridRowSelectionModel,
} from "@mui/x-data-grid";
import { useCallback, useMemo, useState } from "react";

import type { TagValueItem } from "../../../shared/api/tagCuration";
import { useCurationActions } from "../hooks/useCurationActions";
import { useTagValues } from "../hooks/useTagValues";

import { MergeDialog } from "./MergeDialog";
import { SongListPanel } from "./SongListPanel";

interface TagValueGridProps {
  name?: string;
  prefix?: string;
}

export function TagValueGrid({ name, prefix }: TagValueGridProps): React.JSX.Element {
  const {
    rows,
    total,
    loading,
    page,
    setPage,
    pageSize,
    setPageSize,
    refetch,
  } = useTagValues({ name, prefix, initialPageSize: 50 });

  const {
    rename,
    merge,
    loading: actionLoading,
    error: actionError,
  } = useCurationActions({ onSuccess: refetch });

  const [expandedTagId, setExpandedTagId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false);

  const paginationModel = { page, pageSize };

  const expandedTag = expandedTagId
    ? (rows.find((r) => r.id === expandedTagId) ?? null)
    : null;

  const selectedTags = rows.filter((r) => selectedIds.includes(r.id));
  const canMerge =
    selectedTags.length >= 2 &&
    selectedTags.every((t) => t.name === selectedTags[0]?.name);

  const handleToggleExpand = useCallback((tagId: string) => {
    setExpandedTagId((prev) => (prev === tagId ? null : tagId));
  }, []);

  const processRowUpdate = useCallback(
    async (newRow: TagValueItem, oldRow: TagValueItem): Promise<TagValueItem> => {
      if (newRow.value === oldRow.value) return oldRow;
      await rename(newRow.id, newRow.value);
      return newRow;
    },
    [rename]
  );

  const columns = useMemo<GridColDef<TagValueItem>[]>(
    () => [
      {
        field: "__expand",
        headerName: "",
        width: 44,
        sortable: false,
        filterable: false,
        disableColumnMenu: true,
        renderCell: (params) => {
          const row = params.row as TagValueItem;
          if (row.name.startsWith("nom:")) return null;
          const isExpanded = expandedTagId === row.id;
          return (
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                handleToggleExpand(row.id);
              }}
              aria-label={isExpanded ? "Collapse songs" : "Expand songs"}
            >
              {isExpanded ? (
                <ExpandLessIcon fontSize="small" />
              ) : (
                <ExpandMoreIcon fontSize="small" />
              )}
            </IconButton>
          );
        },
      },
      {
        field: "name",
        headerName: "Name",
        width: 140,
        editable: false,
      },
      {
        field: "value",
        headerName: "Value",
        flex: 1,
        editable: true,
      },
      {
        field: "song_count",
        headerName: "Songs",
        width: 90,
        type: "number",
        editable: false,
      },
    ],
    [expandedTagId, handleToggleExpand]
  );

  return (
    <Box>
      {actionError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {actionError}
        </Alert>
      )}
      {canMerge && (
        <Box sx={{ mb: 1 }}>
          <Button
            variant="outlined"
            size="small"
            onClick={() => setMergeDialogOpen(true)}
            disabled={actionLoading}
          >
            Merge {selectedTags.length} tags
          </Button>
        </Box>
      )}
      <DataGrid<TagValueItem>
        rows={rows}
        columns={columns}
        rowCount={total}
        paginationMode="server"
        paginationModel={paginationModel}
        onPaginationModelChange={(model) => {
          setPage(model.page);
          setPageSize(model.pageSize);
        }}
        pageSizeOptions={[25, 50, 100]}
        checkboxSelection
        disableRowSelectionOnClick
        rowSelectionModel={{ type: 'include', ids: new Set(selectedIds) } as GridRowSelectionModel}
        onRowSelectionModelChange={(model: GridRowSelectionModel) => {
          setSelectedIds([...model.ids].map(String));
        }}
        isRowSelectable={(params) => {
          const row = params.row as TagValueItem;
          return !row.name.startsWith("nom:");
        }}
        isCellEditable={(params) => {
          const row = params.row as TagValueItem;
          return params.field === "value" && !row.name.startsWith("nom:");
        }}
        processRowUpdate={processRowUpdate}
        onProcessRowUpdateError={() => {
          // Roll back handled by DataGrid; error shown via useCurationActions
        }}
        getRowClassName={(params) => {
          const row = params.row as TagValueItem;
          return row.name.startsWith("nom:") ? "nom-row" : "";
        }}
        loading={loading}
        sx={{
          height: 520,
          "& .nom-row": {
            bgcolor: "action.disabledBackground",
            "& .MuiDataGrid-cell": {
              color: "text.disabled",
            },
          },
        }}
      />
      {expandedTag && (
        <SongListPanel
          tagId={expandedTag.id}
          tagValue={expandedTag.value}
          refetchTagValues={refetch}
        />
      )}
      {mergeDialogOpen && (
        <MergeDialog
          key={selectedIds.join(",")}
          open={mergeDialogOpen}
          sourceTags={selectedTags}
          onClose={() => setMergeDialogOpen(false)}
          onMerge={merge}
        />
      )}
    </Box>
  );
}
