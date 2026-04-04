import { MenuItem, Select, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { getUniqueTagKeys } from "@shared/api/files";
import { PageContainer } from "@shared/components/ui";

import { CommitBar } from "./components/CommitBar";
import { TagValueGrid } from "./components/TagValueGrid";

export function TagCurationPage(): React.JSX.Element {
  const [relFilter, setRelFilter] = useState<string>("");
  const [prefixFilter, setPrefixFilter] = useState<string>("");
  const [tagKeys, setTagKeys] = useState<string[]>([]);

  useEffect(() => {
    getUniqueTagKeys()
      .then((result) => setTagKeys(result.tag_keys))
      .catch(() => {
        // Non-critical; rel filter still usable with manual selection
      });
  }, []);

  return (
    <PageContainer title="Tag Curation">
      <CommitBar />
      <Stack direction="row" spacing={2} sx={{ mb: 2 }} alignItems="center">
        <Typography variant="body2" color="text.secondary">
          Filter by:
        </Typography>
        <Select
          value={relFilter}
          onChange={(e) => {
            setRelFilter(e.target.value);
            setPrefixFilter("");
          }}
          displayEmpty
          size="small"
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="">All rels</MenuItem>
          {tagKeys.map((key) => (
            <MenuItem key={key} value={key}>
              {key}
            </MenuItem>
          ))}
        </Select>
        <Select
          value={prefixFilter}
          onChange={(e) => setPrefixFilter(e.target.value)}
          displayEmpty
          size="small"
          sx={{ minWidth: 120 }}
          disabled={!relFilter}
        >
          <MenuItem value="">All prefixes</MenuItem>
          {["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
            "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z"].map(
            (letter) => (
              <MenuItem key={letter} value={letter}>
                {letter.toUpperCase()}
              </MenuItem>
            )
          )}
        </Select>
      </Stack>
      <TagValueGrid
        rel={relFilter || undefined}
        prefix={prefixFilter || undefined}
      />
    </PageContainer>
  );
}
