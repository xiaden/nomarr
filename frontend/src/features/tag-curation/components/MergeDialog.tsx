import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Radio,
  RadioGroup,
  Typography,
} from "@mui/material";
import { useState } from "react";

import type { MergeResult, TagValueItem } from "../../../shared/api/tagCuration";

interface MergeDialogProps {
  open: boolean;
  sourceTags: TagValueItem[];
  onClose: () => void;
  onMerge: (sourceTagIds: string[], canonicalTagId: string) => Promise<MergeResult>;
}

export function MergeDialog({
  open,
  sourceTags,
  onClose,
  onMerge,
}: MergeDialogProps): React.JSX.Element {
  const [canonicalId, setCanonicalId] = useState<string>(
    sourceTags[0]?.id ?? ""
  );
  const [merging, setMerging] = useState(false);

  const totalSongs = sourceTags.reduce((sum, t) => sum + t.song_count, 0);
  const canonical = sourceTags.find((t) => t.id === canonicalId);
  const nonCanonicalCount = sourceTags
    .filter((t) => t.id !== canonicalId)
    .reduce((sum, t) => sum + t.song_count, 0);

  const handleMerge = async () => {
    if (!canonicalId) return;
    const sourceIds = sourceTags
      .filter((t) => t.id !== canonicalId)
      .map((t) => t.id);
    setMerging(true);
    try {
      await onMerge(sourceIds, canonicalId);
      onClose();
    } catch {
      // Error surfaced by useCurationActions
    } finally {
      setMerging(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Merge Tags</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Select the canonical tag. Songs from the other selected tags will be
          re-tagged with the canonical value.
        </Typography>
        <RadioGroup
          value={canonicalId}
          onChange={(e) => setCanonicalId(e.target.value)}
        >
          {sourceTags.map((tag) => (
            <FormControlLabel
              key={tag.id}
              value={tag.id}
              control={<Radio />}
              label={`"${tag.value}" — ${tag.song_count} song${
                tag.song_count !== 1 ? "s" : ""
              }`}
            />
          ))}
        </RadioGroup>
        {canonical && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            {nonCanonicalCount} song{nonCanonicalCount !== 1 ? "s" : ""} will
            be re-tagged as &quot;{canonical.value}&quot; (total after merge:{" "}
            {totalSongs} songs)
          </Typography>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={merging}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={() => void handleMerge()}
          disabled={merging || !canonicalId || sourceTags.length < 2}
        >
          {merging ? "Merging…" : "Merge"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
