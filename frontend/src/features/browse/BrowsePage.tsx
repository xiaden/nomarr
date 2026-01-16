/**
 * BrowsePage - Hierarchical music library browser
 *
 * Features:
 * - Tab-based navigation (Artists/Albums/Genres/Years)
 * - Drill-down: Entity → Songs → Tags
 * - Tag-based exploration (exact string match, closest 25 for numbers)
 */

import { Box, Tab, Tabs } from "@mui/material";
import { useState } from "react";

import { PageContainer } from "@shared/components/ui";

import type { EntityCollection } from "../../shared/types";
import { EntityBrowser } from "./components/EntityBrowser";

export function BrowsePage() {
  const [activeTab, setActiveTab] = useState<EntityCollection>("artists");

  return (
    <PageContainer title="Browse Music">
      <Box sx={{ borderBottom: 1, borderColor: "divider", mb: 2 }}>
        <Tabs
          value={activeTab}
          onChange={(_, newValue) => setActiveTab(newValue as EntityCollection)}
        >
          <Tab label="Artists" value="artists" />
          <Tab label="Albums" value="albums" />
          <Tab label="Genres" value="genres" />
          <Tab label="Years" value="years" />
        </Tabs>
      </Box>

      <EntityBrowser collection={activeTab} />
    </PageContainer>
  );
}
