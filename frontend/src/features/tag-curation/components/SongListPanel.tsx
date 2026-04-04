import { Box, Button, TextField, Typography } from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";
import type { GridColDef, GridRowSelectionModel } from "@mui/x-data-grid";
import { useState } from "react";

import type { TagSongItem } from "../../../shared/api/tagCuration";
import { useCurationActions } from "../hooks/useCurationActions";
import { useSelection } from "../hooks/useSelection";
import { useTagSongs } from "../hooks/useTagSongs";

interface SongListPanelProps {
  tagId: string;
  tagValue: string;
  refetchTagValues: () => void;
}

interface SongRow extends TagSongItem {
  id: string;
}

const PAGE_SIZE = 50;

const columns: GridColDef<SongRow>[] = [
  { field: "title", headerName: "Title", flex: 2 },
  { field: "artist", headerName: "Artist", flex: 1.5 },
  { field: "album", headerName: "Album", flex: 1.5 },
];

export function SongListPanel({
  tagId,
  tagValue,
  refetchTagValues,
}: SongListPanelProps): React.JSX.Element {
  const { songs, total, loading, page, setPage } = useTagSongs({
    tagId,
    initialPageSize: PAGE_SIZE,
  });
  const { selectedIds, toggle, deselectAll, count: selectedCount } =
    useSelection();
  const { split, loading: actionLoading } = useCurationActions({
    onSuccess: refetchTagValues,
  });
  const [newTagValue, setNewTagValue] = useState("");

  const rows: SongRow[] = songs.map((s) => ({ ...s, id: s.file_id }));
  const paginationModel = { page, pageSize: PAGE_SIZE };
  const rowSelectionModel: string[] = rows
    .filter((r) => selectedIds.has(r.id))
    .map((r) => r.id);

  const handleSelectionChange = (model: GridRowSelectionModel) => {
    const currentPageIds = new Set(rows.map((r) => r.id));
    const nowSelected = new Set([...model.ids].map(String));
    for (const id of currentPageIds) {
      const wasSelected = selectedIds.has(id);
      const isNowSelected = nowSelected.has(id);
      if (isNowSelected && !wasSelected) toggle(id);
      else if (!isNowSelected && wasSelected) toggle(id);
    }
  };

  const handleSplit = async () => {
    if (selectedCount === 0 || !newTagValue.trim()) return;
    await split(tagId, Array.from(selectedIds), newTagValue.trim());
    setNewTagValue("");
    deselectAll();
  };

  return (
    <Box
      sx={{
        p: 2,
        bgcolor: "background.paper",
        borderTop: 1,
        borderColor: "divider",
        borderLeft: 3,
        borderLeftColor: "primary.main",
      }}
    >
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Songs tagged &quot;{tagValue}&quot;
      </Typography>
      <DataGrid<SongRow>
        rows={rows}
        columns={columns}
        rowCount={total}
        paginationMode="server"
        paginationModel={paginationModel}
        onPaginationModelChange={(model) => setPage(model.page)}
        pageSizeOptions={[PAGE_SIZE]}
        checkboxSelection
        disableRowSelectionOnClick
        rowSelectionModel={{ type: 'include', ids: new Set(rowSelectionModel) } as GridRowSelectionModel}
        onRowSelectionModelChange={handleSelectionChange}
        loading={loading}
        sx={{ height: 320 }}
      />
      {selectedCount > 0 && (
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 1,
            mt: 1,
            flexWrap: "wrap",
          }}
        >
          <Typography variant="body2" color="text.secondary">
            {selectedCount} song{selectedCount !== 1 ? "s" : ""} selected
          </Typography>
          <TextField
            size="small"
            label="Re-tag selected as…"
            value={newTagValue}
            onChange={(e) => setNewTagValue(e.target.value)}
            sx={{ minWidth: 220 }}
          />
          <Button
            variant="contained"
            size="small"
            onClick={() => void handleSplit()}
            disabled={actionLoading || !newTagValue.trim()}
          >
            Split Selected
          </Button>
          <Button size="small" onClick={deselectAll} disabled={actionLoading}>
            Clear
          </Button>
        </Box>
      )}
    </Box>
  );
}
