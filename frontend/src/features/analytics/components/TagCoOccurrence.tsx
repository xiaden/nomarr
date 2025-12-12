/**
 * Tag Co-Occurrence Matrix component
 *
 * Features:
 * - Select tag keys and values
 * - Build X and Y axis tag lists
 * - Generate co-occurrence matrix
 * - Display results in a heatmap-style table
 */


import CloseIcon from "@mui/icons-material/Close";
import {
    Box,
    Button,
    Chip,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    Typography
} from "@mui/material";
import { useEffect, useState } from "react";

import { Panel, SectionHeader } from "@shared/components/ui";

import { api } from "../../../shared/api";
import { ComboBox } from "../../../shared/components/ComboBox";

interface TagSpec {
  key: string;
  value: string;
}

interface TagCoOccurrenceMatrix {
  x: TagSpec[];
  y: TagSpec[];
  matrix: number[][];
}

export function TagCoOccurrence() {
  const [tagKeys, setTagKeys] = useState<string[]>([]);
  const [tagValues, setTagValues] = useState<string[]>([]);

  const [selectedKey, setSelectedKey] = useState("");
  const [selectedValue, setSelectedValue] = useState("");

  const [xTags, setXTags] = useState<TagSpec[]>([]);
  const [yTags, setYTags] = useState<TagSpec[]>([]);

  const [matrix, setMatrix] = useState<TagCoOccurrenceMatrix | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load tag keys on mount
  useEffect(() => {
    loadTagKeys();
  }, []);

  // Load tag values when key changes
  useEffect(() => {
    if (selectedKey) {
      loadTagValues(selectedKey);
    } else {
      setTagValues([]);
      setSelectedValue("");
    }
  }, [selectedKey]);

  const loadTagKeys = async () => {
    try {
      const response = await api.files.getUniqueTagKeys(true);
      setTagKeys(response.tag_keys);
    } catch (err) {
      console.error("[TagCoOccurrence] Failed to load tag keys:", err);
    }
  };

  const loadTagValues = async (key: string) => {
    try {
      const response = await api.files.getUniqueTagValues(key, true);
      setTagValues(response.tag_keys); // API reuses same structure
    } catch (err) {
      console.error("[TagCoOccurrence] Failed to load tag values:", err);
      setTagValues([]);
    }
  };

  const isTagInEitherAxis = (key: string, value: string): boolean => {
    return (
      xTags.some((t) => t.key === key && t.value === value) ||
      yTags.some((t) => t.key === key && t.value === value)
    );
  };

  const addToX = () => {
    if (selectedKey && selectedValue) {
      // Check if already exists
      const exists = xTags.some(
        (t) => t.key === selectedKey && t.value === selectedValue
      );
      if (!exists && xTags.length < 16) {
        setXTags([...xTags, { key: selectedKey, value: selectedValue }]);
      }
    }
  };

  const addToY = () => {
    if (selectedKey && selectedValue) {
      const exists = yTags.some(
        (t) => t.key === selectedKey && t.value === selectedValue
      );
      if (!exists && yTags.length < 16) {
        setYTags([...yTags, { key: selectedKey, value: selectedValue }]);
      }
    }
  };

  const removeFromX = (index: number) => {
    setXTags(xTags.filter((_, i) => i !== index));
  };

  const removeFromY = (index: number) => {
    setYTags(yTags.filter((_, i) => i !== index));
  };

  const buildMatrix = async () => {
    if (xTags.length === 0 || yTags.length === 0) {
      setError("Both X and Y axes must have at least one tag");
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const result = await api.analytics.getTagCoOccurrence({
        x: xTags,
        y: yTags,
      });

      setMatrix(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to build matrix");
      console.error("[TagCoOccurrence] Matrix build error:", err);
    } finally {
      setLoading(false);
    }
  };

  const getHeatmapColor = (value: number, max: number): string => {
    if (value === 0) return "#1a1a1a";
    const intensity = Math.min(value / max, 1);
    // Blue heatmap for dark theme
    const r = Math.floor(30 + intensity * 44); // 30 -> 74
    const g = Math.floor(30 + intensity * 128); // 30 -> 158
    const b = Math.floor(30 + intensity * 225); // 30 -> 255
    return `rgb(${r}, ${g}, ${b})`;
  };

  const maxValue =
    matrix?.matrix ? Math.max(...matrix.matrix.flat(), 1) : 1;

  return (
    <Panel>
      <SectionHeader title="Tag Co-Occurrence Matrix" />

      {/* Tag Selection Controls */}
      <Stack spacing={2} sx={{ mb: 2.5 }}>
        <Box sx={{ display: "flex", gap: 1.5, alignItems: "flex-end" }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="body2" sx={{ mb: 0.5, fontWeight: 500 }}>
              Tag Key
            </Typography>
            <ComboBox
              value={selectedKey}
              onChange={setSelectedKey}
              options={tagKeys}
              placeholder="Select tag key..."
            />
          </Box>
          <Box sx={{ flex: 1 }}>
            <Typography variant="body2" sx={{ mb: 0.5, fontWeight: 500 }}>
              Tag Value
            </Typography>
            <ComboBox
              value={selectedValue}
              onChange={setSelectedValue}
              options={tagValues}
              placeholder="Select tag value..."
              disabled={!selectedKey}
            />
          </Box>
          <Button
            onClick={addToX}
            disabled={
              !selectedKey ||
              !selectedValue ||
              xTags.length >= 16 ||
              isTagInEitherAxis(selectedKey, selectedValue)
            }
            variant="contained"
            size="small"
          >
            Add to X
          </Button>
          <Button
            onClick={addToY}
            disabled={
              !selectedKey ||
              !selectedValue ||
              yTags.length >= 16 ||
              isTagInEitherAxis(selectedKey, selectedValue)
            }
            variant="contained"
            color="secondary"
            size="small"
          >
            Add to Y
          </Button>
        </Box>

        {/* X Axis Tags */}
        <Box>
          <Typography variant="body2" sx={{ mb: 0.5, fontWeight: 500 }}>
            X Axis ({xTags.length}/16)
          </Typography>
          <Box
            sx={{
              display: "flex",
              flexWrap: "wrap",
              gap: 1,
              p: 1.5,
              bgcolor: "background.default",
              border: 1,
              borderColor: "divider",
              borderRadius: 1,
              minHeight: 80,
            }}
          >
            {xTags.length === 0 && (
              <Typography variant="body2" color="text.secondary">
                No tags added to X axis yet
              </Typography>
            )}
            {xTags.map((tag, index) => (
              <Chip
                key={index}
                label={`${tag.key}: ${tag.value}`}
                onDelete={() => removeFromX(index)}
                deleteIcon={<CloseIcon />}
                size="small"
              />
            ))}
          </Box>
        </Box>

        {/* Y Axis Tags */}
        <Box>
          <Typography variant="body2" sx={{ mb: 0.5, fontWeight: 500 }}>
            Y Axis ({yTags.length}/16)
          </Typography>
          <Box
            sx={{
              display: "flex",
              flexWrap: "wrap",
              gap: 1,
              p: 1.5,
              bgcolor: "background.default",
              border: 1,
              borderColor: "divider",
              borderRadius: 1,
              minHeight: 80,
            }}
          >
            {yTags.length === 0 && (
              <Typography variant="body2" color="text.secondary">
                No tags added to Y axis yet
              </Typography>
            )}
            {yTags.map((tag, index) => (
              <Chip
                key={index}
                label={`${tag.key}: ${tag.value}`}
                onDelete={() => removeFromY(index)}
                deleteIcon={<CloseIcon />}
                size="small"
              />
            ))}
          </Box>
        </Box>

        <Button
          onClick={buildMatrix}
          disabled={loading || xTags.length === 0 || yTags.length === 0}
          variant="contained"
          fullWidth
        >
          {loading ? "Building Matrix..." : "Build Matrix"}
        </Button>
      </Stack>

      {/* Error Display */}
      {error && (
        <Typography color="error" sx={{ mb: 2 }}>
          {error}
        </Typography>
      )}

      {/* Matrix Display */}
      {matrix && (
        <Box sx={{ overflowX: "auto", mt: 2.5 }}>
          <Table size="small" sx={{ minWidth: 300 }}>
            <TableHead>
              <TableRow>
                <TableCell
                  sx={{
                    bgcolor: "background.default",
                    borderBottom: 2,
                    borderColor: "divider",
                    fontWeight: 600,
                  }}
                >
                  Y \ X
                </TableCell>
                {matrix.x.map((tag, index) => (
                  <TableCell
                    key={index}
                    sx={{
                      bgcolor: "background.default",
                      borderBottom: 2,
                      borderColor: "divider",
                      fontWeight: 600,
                    }}
                  >
                    {tag.key}:
                    <br />
                    {tag.value}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {matrix.y.map((yTag, yIndex) => (
                <TableRow key={yIndex}>
                  <TableCell
                    sx={{
                      borderColor: "divider",
                      fontWeight: 600,
                    }}
                  >
                    {yTag.key}: {yTag.value}
                  </TableCell>
                  {matrix.x.map((_, xIndex) => (
                    <TableCell
                      key={xIndex}
                      align="center"
                      sx={{
                        borderColor: "divider",
                        bgcolor: getHeatmapColor(
                          matrix.matrix[yIndex][xIndex],
                          maxValue
                        ),
                        fontWeight:
                          matrix.matrix[yIndex][xIndex] > 0 ? 600 : "normal",
                      }}
                    >
                      {matrix.matrix[yIndex][xIndex]}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Panel>
  );
}
