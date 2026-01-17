/**
 * EntityBrowser - List and navigate music entities (artists, albums, etc.)
 */

import { Search } from "@mui/icons-material";
import {
    Box,
    Button,
    List,
    ListItemButton,
    ListItemText,
    MenuItem,
    Select,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { ErrorMessage, Panel } from "@shared/components/ui";

import { listEntities } from "../../../shared/api/metadata";
import type { Entity, EntityCollection } from "../../../shared/types";

import { TrackList } from "./TrackList";

interface EntityBrowserProps {
  collection: EntityCollection;
}

export function EntityBrowser({ collection }: EntityBrowserProps) {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [offset, setOffset] = useState(0);
  const [sortBy, setSortBy] = useState<"name" | "count">("name");
  const limit = 100;

  const loadEntities = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const result = await listEntities(collection, {
        limit,
        offset,
        search: searchQuery || undefined,
      });

      const sorted = [...result.entities].sort((a, b) => {
        if (sortBy === "name") {
          return a.display_name.localeCompare(b.display_name);
        } else {
          return (b.song_count || 0) - (a.song_count || 0);
        }
      });

      setEntities(sorted);
      setTotal(result.total);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load entities"
      );
      console.error("[EntityBrowser] Load error:", err);
    } finally {
      setLoading(false);
    }
  }, [collection, offset, searchQuery]);

  useEffect(() => {
    setOffset(0);
    setSelectedEntity(null);
    setSearchQuery("");
  }, [collection]);

  useEffect(() => {
    loadEntities();
  }, [loadEntities]);

  const handleSearch = () => {
    setOffset(0);
    setSelectedEntity(null);
    loadEntities();
  };

  const handleEntityClick = (entity: Entity) => {
    setSelectedEntity(entity);
  };

  const handlePrevPage = () => {
    setOffset(Math.max(0, offset - limit));
  };

  const handleNextPage = () => {
    if (offset + limit < total) {
      setOffset(offset + limit);
    }
  };

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  const getRelationType = (): string => {
    switch (collection) {
      case "artists":
        return "artist";
      case "albums":
        return "album";
      case "genres":
        return "genres";
      case "years":
        return "year";
      default:
        return collection;
    }
  };

  return (
    <Box sx={{ display: "flex", gap: 2, height: "calc(100vh - 250px)" }}>
      {/* Entity List (Left Panel) */}
      <Box sx={{ width: 350, display: "flex", flexDirection: "column" }}>
        <Panel sx={{ mb: 2 }}>
          <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
            <TextField
              placeholder={`Search ${collection}...`}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              size="small"
              fullWidth
            />
            <Button
              variant="contained"
              onClick={handleSearch}
              sx={{ minWidth: "auto" }}
            >
              <Search />
            </Button>
          </Stack>
          <Select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "name" | "count")}
            size="small"
            fullWidth
          >
            <MenuItem value="name">Sort by Name</MenuItem>
            <MenuItem value="count">Sort by Song Count</MenuItem>
          </Select>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {loading ? "Loading..." : `${total.toLocaleString()} total`}
            {total > limit && ` (Page ${currentPage} of ${totalPages})`}
          </Typography>
        </Panel>

        {error && <ErrorMessage>{error}</ErrorMessage>}

        <Panel sx={{ flex: 1, overflow: "auto", p: 0 }}>
          {entities.length === 0 && !loading && (
            <Box sx={{ p: 2, textAlign: "center" }}>
              <Typography color="text.secondary">
                No {collection} found.
              </Typography>
            </Box>
          )}

          <List dense>
            {entities.map((entity) => (
              <ListItemButton
                key={entity.id}
                selected={selectedEntity?.id === entity.id}
                onClick={() => handleEntityClick(entity)}
              >
                <ListItemText
                  primary={entity.display_name}
                  secondary={
                    entity.song_count !== undefined
                      ? `${entity.song_count} songs`
                      : undefined
                  }
                />
              </ListItemButton>
            ))}
          </List>
        </Panel>

        {total > limit && (
          <Box sx={{ mt: 1, display: "flex", justifyContent: "center", gap: 1 }}>
            <Button
              size="small"
              onClick={handlePrevPage}
              disabled={offset === 0}
            >
              Previous
            </Button>
            <Button
              size="small"
              onClick={handleNextPage}
              disabled={offset + limit >= total}
            >
              Next
            </Button>
          </Box>
        )}
      </Box>

      {/* Details Panel (Right) */}
      <Box sx={{ flex: 1 }}>
        {!selectedEntity ? (
          <Panel>
            <Typography color="text.secondary" textAlign="center">
              Select {collection === "artists" ? "an" : "a"} {collection.slice(0, -1)} to view tracks
            </Typography>
          </Panel>
        ) : (
          <TrackList
            entityId={selectedEntity.id}
            entityName={selectedEntity.display_name}
            collection={collection}
            relationType={getRelationType()}
          />
        )}
      </Box>
    </Box>
  );
}
