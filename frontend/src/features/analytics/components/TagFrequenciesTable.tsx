/**
 * TagFrequenciesTable - Display top tag frequencies
 */

import {
    Box,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
} from "@mui/material";

import { Panel, SectionHeader } from "@shared/components/ui";

interface TagFrequency {
  tag_key: string;
  total_count: number;
  unique_values: number;
}

interface TagFrequenciesTableProps {
  data: TagFrequency[];
  limit?: number;
}

export function TagFrequenciesTable({ data, limit = 50 }: TagFrequenciesTableProps) {
  return (
    <Panel>
      <SectionHeader title={`Tag Frequencies (Top ${limit})`} />
      <Box sx={{ overflowX: "auto" }}>
        <Table sx={{ minWidth: 300 }}>
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
                Tag
              </TableCell>
              <TableCell
                sx={{
                  bgcolor: "background.default",
                  borderBottom: 2,
                  borderColor: "divider",
                  fontWeight: 600,
                }}
              >
                Count
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.map((tag) => (
              <TableRow key={tag.tag_key}>
                <TableCell sx={{ borderColor: "divider" }}>
                  {tag.tag_key}
                </TableCell>
                <TableCell sx={{ borderColor: "divider" }}>
                  {tag.total_count}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Panel>
  );
}
