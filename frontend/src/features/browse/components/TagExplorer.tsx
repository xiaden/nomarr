/**
 * TagExplorer - Display tags and explore similar tracks
 */

import {
    Box,
    Chip,
    List,
    ListItem,
    ListItemText,
    Stack,
    Typography,
} from "@mui/material";
import { useState } from "react";

import { Panel } from "@shared/components/ui";

import type { FileTag, LibraryFile } from "../../../shared/types";
import { SimilarTracks } from "./SimilarTracks";

interface TagExplorerProps {
  track: LibraryFile;
}

export function TagExplorer({ track }: TagExplorerProps) {
  const [selectedTag, setSelectedTag] = useState<FileTag | null>(null);

  const tags = track.tags || [];
  const nomarrTags = tags.filter((t) => t.is_nomarr);
  const otherTags = tags.filter((t) => !t.is_nomarr);

  const handleTagClick = (tag: FileTag) => {
    setSelectedTag(selectedTag?.key === tag.key ? null : tag);
  };

  const isNumericTag = (tag: FileTag): boolean => {
    return tag.type === "float" || !isNaN(parseFloat(tag.value));
  };

  return (
    <Box>
      <Box sx={{ mb: 2 }}>
        <Typography variant="body2" fontWeight="bold" component="span">
          Path:
        </Typography>
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{
            mt: 0.5,
            fontFamily: "monospace",
            wordBreak: "break-all",
          }}
        >
          {track.path}
        </Typography>
      </Box>

      {tags.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No tags available for this track.
        </Typography>
      )}

      {nomarrTags.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            Nomarr Tags (Click to explore similar)
          </Typography>
          <List dense>
            {nomarrTags.map((tag) => (
              <ListItem
                key={tag.key}
                onClick={() => handleTagClick(tag)}
                sx={{
                  cursor: "pointer",
                  borderRadius: 1,
                  "&:hover": { bgcolor: "action.hover" },
                  bgcolor:
                    selectedTag?.key === tag.key
                      ? "action.selected"
                      : "transparent",
                }}
              >
                <ListItemText
                  primary={
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography variant="body2" component="span" sx={{ fontWeight: 500 }}>
                        {tag.key}:
                      </Typography>
                      <Typography variant="body2" component="span">
                        {tag.value}
                      </Typography>
                      {isNumericTag(tag) && (
                        <Chip
                          label="numeric"
                          size="small"
                          sx={{ height: 18, fontSize: "0.65rem" }}
                        />
                      )}
                    </Stack>
                  }
                />
              </ListItem>
            ))}
          </List>
        </Box>
      )}

      {otherTags.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            Other Tags
          </Typography>
          <List dense>
            {otherTags.map((tag) => (
              <ListItem key={tag.key} sx={{ pl: 0 }}>
                <ListItemText
                  primary={
                    <Typography variant="body2">
                      <Typography
                        component="span"
                        sx={{ fontWeight: 500, color: "text.secondary" }}
                      >
                        {tag.key}:
                      </Typography>{" "}
                      {tag.value}
                    </Typography>
                  }
                />
              </ListItem>
            ))}
          </List>
        </Box>
      )}

      {selectedTag && (
        <Panel sx={{ mt: 2 }}>
          <SimilarTracks
            tag={selectedTag}
            currentTrackId={track.id}
            isNumeric={isNumericTag(selectedTag)}
          />
        </Panel>
      )}
    </Box>
  );
}
