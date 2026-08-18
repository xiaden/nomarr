import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { Alert, Box, Button, IconButton } from "@mui/material";
import { DataGrid, useGridApiRef } from "@mui/x-data-grid";
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
  const [selectedTagsById, setSelectedTagsById] = useState<Map<string, TagValueItem>>(
    () => new Map()
  );
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false);
  const apiRef = useGridApiRef();

  const paginationModel = { page, pageSize };

  // Keep the selected row data independently of the current server-side page.
  // Otherwise changing pages drops the source data needed by the merge dialog.
  const selectedTags = selectedIds
    .map((id) => selectedTagsById.get(id))
    .filter((tag): tag is TagValueItem => tag !== undefined);
  const canMerge =
    selectedTags.length >= 2 &&
    selectedTags.every((t) => t.name === selectedTags[0]?.name);

  const handleToggleExpand = useCallback((tag: TagValueItem) => {
    setExpandedTagId((prev) => (prev === tag.id ? null : tag.id));
  }, []);

  const processRowUpdate = useCallback(
    async (newRow: TagValueItem, oldRow: TagValueItem): Promise<TagValueItem> => {
      if (newRow.value === oldRow.value) return oldRow;
      try {
        await rename(newRow.id, newRow.value);
        return newRow;
      } catch (error) {
        const gridApi = apiRef.current;
        if (gridApi) {
          gridApi.updateRows([oldRow]);
          gridApi.stopCellEditMode({ id: oldRow.id, field: "value" });
        }
        throw error;
      }
    },
    [apiRef, rename]
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
                handleToggleExpand(row);
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
        apiRef={apiRef}
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
         keepNonExistentRowsSelected
         disableRowSelectionOnClick
         rowSelectionModel={{ type: 'include', ids: new Set(selectedIds) } as GridRowSelectionModel}
         onRowSelectionModelChange={(model: GridRowSelectionModel) => {
           const nextSelectedIds = [...model.ids].map(String);
           setSelectedIds(nextSelectedIds);
           setSelectedTagsById((previous) => {
             const next = new Map(previous);
             for (const row of rows) {
               if (nextSelectedIds.includes(row.id)) {
                 next.set(row.id, row);
               } else {
                 next.delete(row.id);
               }
             }
             return next;
           });
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
      {(() => {
        const expandedTag = rows.find((row) => row.id === expandedTagId);
        return expandedTag ? (
          <Box key={expandedTag.id}>
            <SongListPanel
              tagId={expandedTag.id}
              tagValue={expandedTag.value}
              refetchTagValues={refetch}
            />
          </Box>
        ) : null;
      })()}
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
